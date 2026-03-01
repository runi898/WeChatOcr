"""
Patch script – WeChat-style overlay translation
Run once: python _patch_wechat_overlay.py
"""
import sys, os

SRC = os.path.join(os.path.dirname(__file__), "screenshot_tool.py")

with open(SRC, "r", encoding="utf-8") as f:
    content = f.read()

# ── MARKERS ──────────────────────────────────────────────────────────────────
# The residue starts right after the new grab_region's closing call
RESIDUE_START = '    app.after(0, _open)\n\n\n    """在主线程中打开截图遮罩，完成后调用 callback(image_path)'
# The old InPlaceOverlay class ends here
OLD_IPO_END_MARKER = '\n\n\n\ntry:\n    import pystray as _pystray'

NEW_IPO_MARKER = (
    '\n# ─────────────────────────────────────────────\n'
    '#  原位覆盖结果层（与微信截屏翻译效果相同）\n'
    '# ─────────────────────────────────────────────\n'
    'class InPlaceOverlay(Toplevel):'
)

si = content.find(RESIDUE_START)
if si == -1:
    print("[INFO] Residue start marker not found – may already be patched")
else:
    # The block to remove is from RESIDUE_START up to and including the old
    # InPlaceOverlay class.  The old class ends at OLD_IPO_END_MARKER.
    block_start = si + len('    app.after(0, _open)\n\n\n')   # keep the trailing \n x3

    # Find where old InPlaceOverlay ends
    ipo_class_start = content.find(NEW_IPO_MARKER, block_start)
    if ipo_class_start == -1:
        print("[ERROR] Could not find old InPlaceOverlay class. Aborting.")
        sys.exit(1)

    ipo_class_end_marker = OLD_IPO_END_MARKER
    ipo_end = content.find(ipo_class_end_marker, ipo_class_start)
    if ipo_end == -1:
        print("[ERROR] Could not find end of old InPlaceOverlay. Aborting.")
        sys.exit(1)

    # Remove everything from the residue start up to (but not including)
    # the pystray import line
    remove_from = block_start
    remove_to   = ipo_end   # we replace up to the blank lines before pystray

    # Build the new InPlaceOverlay implementation
    new_ipo = '''
# ─────────────────────────────────────────────
#  原位覆盖结果层（微信同款：截图原图为背景，译文原位渲染）
# ─────────────────────────────────────────────
class InPlaceOverlay(Toplevel):
    """
    微信原生截图翻译效果：
    - 以截图原图作 Canvas 背景，背景/中文/图标等一概不变
    - 仅在 OCR 文字坐标处直接渲染译文（无任何底色块）
    - 字体颜色从截图对应区域自动采样
    ❗ 必须在主线程中创建！
    """

    def __init__(self, parent, lx1: int, ly1: int, lx2: int, ly2: int,
                 mode: str, bg_img=None, dpi_scale=(1.0, 1.0)):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="black",
                       highlightthickness=2,
                       highlightbackground="#22cc44")
        self._mode      = mode
        self._ocr_txt   = ""
        self._tr_txt    = ""
        self._parent    = parent
        self._toolbar   = None
        self._text_ids  = []
        self._bg_img    = bg_img
        self._dpi_scale = dpi_scale
        self._photo_ref = None

        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        w  = max(lx2 - lx1, 200)
        h  = max(ly2 - ly1, 40)
        self._px = max(0, min(lx1, sw - w))
        self._py = max(0, min(ly1, sh - h))
        self._win_w, self._win_h = w, h
        self.geometry(f"{w}x{h}+{self._px}+{self._py}")

        self._canvas = Canvas(self, bg="black", highlightthickness=0,
                              width=w, height=h)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        if bg_img:
            self._render_bg(bg_img, w, h)
            if mode == "translate":
                self._canvas.create_text(
                    w // 2, h // 2, text="翻译中\\u2026",
                    fill="#ffffff", font=("微软雅黑", 13), tags="loading"
                )
        else:
            self._canvas.configure(bg="white")
            self._canvas.create_text(
                w // 2, h // 2,
                text="翻译中\\u2026" if mode == "translate" else "识别中\\u2026",
                fill="#111111", font=("微软雅黑", 11), tags="loading"
            )

        self._fallback_var = tk.StringVar(value="")
        self._fallback_lbl = tk.Label(
            self, textvariable=self._fallback_var,
            bg="white", fg="#111111",
            font=("微软雅黑", 11), wraplength=w - 16,
            justify=tk.LEFT, anchor="nw", padx=8, pady=6
        )

        self._build_toolbar(sh)
        self.focus_force()

    def _render_bg(self, pil_img, w, h):
        from PIL import ImageTk
        try:
            display = pil_img.resize((w, h), Image.BILINEAR)
            photo = ImageTk.PhotoImage(display)
            self._canvas.delete("bg_img")
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags="bg_img")
            self._canvas.tag_lower("bg_img")
            self._photo_ref = photo
        except Exception:
            pass

    def _sample_text_color(self, x1, y1, x2, y2):
        if not self._bg_img:
            return "#ffffff"
        try:
            iw, ih = self._bg_img.size
            rx1, ry1 = max(0, x1), max(0, y1)
            rx2, ry2 = min(iw, x2), min(ih, y2)
            if rx2 <= rx1 or ry2 <= ry1:
                return "#ffffff"
            region = self._bg_img.crop((rx1, ry1, rx2, ry2)).convert("RGB")
            pixels = list(region.getdata())
            if not pixels:
                return "#ffffff"
            brightnesses = [(r * 299 + g * 587 + b * 114) // 1000 for r, g, b in pixels]
            avg_br = sum(brightnesses) // len(brightnesses)
            if avg_br > 128:
                cands = [pixels[i] for i, b in enumerate(brightnesses) if b < avg_br - 30]
                if not cands:
                    return "#111111"
            else:
                cands = [pixels[i] for i, b in enumerate(brightnesses) if b > avg_br + 30]
                if not cands:
                    return "#ffffff"
            r = sum(p[0] for p in cands) // len(cands)
            g = sum(p[1] for p in cands) // len(cands)
            b = sum(p[2] for p in cands) // len(cands)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#ffffff"

    def _build_toolbar(self, sh):
        tb = Toplevel(self._parent)
        tb.overrideredirect(True)
        tb.attributes("-topmost", True)
        tb.configure(bg="#2b2b2b")
        self._toolbar = tb
        TW, TH = 240, 34
        tx = self._px + (self._win_w - TW) // 2
        ty = self._py + self._win_h + 3
        if ty + TH > sh - 10:
            ty = self._py - TH - 3
        tb.geometry(f"{TW}x{TH}+{tx}+{ty}")
        bar = tk.Frame(tb, bg="#2b2b2b")
        bar.pack(fill=tk.BOTH, expand=True, padx=4, pady=3)
        self._tbtn(bar, "\\U0001f4cb 复制", self._do_copy).pack(side=tk.LEFT, padx=4)
        if self._mode == "translate":
            self._tbtn(bar, "原文", self._show_ocr).pack(side=tk.LEFT, padx=2)
        self._tbtn(bar, "\\xd7", self._close_all,
                   fg="#ff5555", bg="#3d2222").pack(side=tk.RIGHT, padx=4)
        self._tbtn(bar, "\\u2713", self._close_all,
                   fg="#44dd44", bg="#1e3323").pack(side=tk.RIGHT, padx=2)
        self.bind("<Escape>", lambda e: self._close_all())
        tb.bind("<Escape>", lambda e: self._close_all())

    def _tbtn(self, parent, text, cmd, fg="#cccccc", bg="#3a3a3a"):
        return tk.Button(parent, text=text, bg=bg, fg=fg,
                         font=("微软雅黑", 9), bd=0, relief=tk.FLAT,
                         padx=6, pady=2, cursor="hand2",
                         activebackground=bg, activeforeground=fg,
                         command=cmd)

    def set_ocr(self, text: str):
        self._ocr_txt = text
        if self._mode == "ocr":
            self._canvas.delete("loading")
            self._canvas.create_text(
                8, 8, text=text, fill="#111111",
                font=("微软雅黑", 11), anchor="nw",
                width=self._win_w - 16, tags="ocr_text"
            )

    def set_trans(self, text: str, items=None):
        self._tr_txt = text
        if self._mode != "translate":
            return

        self._canvas.delete("loading")
        for tid in self._text_ids:
            self._canvas.delete(tid)
        self._text_ids.clear()
        self._fallback_lbl.place_forget()

        dpi_sx, dpi_sy = self._dpi_scale
        w = self._win_w
        h = self._win_h

        translated_lines = [l.strip() for l in text.split("\\n") if l.strip()]
        original_lines   = [it for it in (items or []) if it.get("text", "").strip()]

        if original_lines and len(translated_lines) == len(original_lines):
            for idx, item in enumerate(original_lines):
                t_txt = translated_lines[idx]
                px1, py1 = int(item["left"]),  int(item["top"])
                px2, py2 = int(item["right"]), int(item["bottom"])
                cx  = int(px1 / dpi_sx)
                cy  = int(py1 / dpi_sy)
                row_h_px = py2 - py1
                font_pt  = max(8, min(18, int(row_h_px / dpi_sy * 0.85)))
                fg_color = self._sample_text_color(px1, py1, px2, py2)
                tid = self._canvas.create_text(
                    cx, cy, text=t_txt,
                    fill=fg_color,
                    font=("微软雅黑", font_pt),
                    anchor="nw", tags="trans_text"
                )
                self._text_ids.append(tid)
        else:
            if self._bg_img:
                self._render_bg(self._bg_img, w, h)
            self._fallback_var.set(text)
            self._fallback_lbl.configure(wraplength=w - 16)
            self._fallback_lbl.place(x=0, y=0, width=w)

    def _show_ocr(self):
        for tid in self._text_ids:
            self._canvas.delete(tid)
        self._text_ids.clear()
        self._canvas.delete("loading")
        self._fallback_lbl.place_forget()
        if self._bg_img:
            self._render_bg(self._bg_img, self._win_w, self._win_h)
        self._canvas.create_text(
            8, 8, text=self._ocr_txt,
            fill="#ccccff", font=("微软雅黑", 11),
            anchor="nw", width=self._win_w - 16, tags="ocr_text"
        )

    def _do_copy(self):
        t = self._tr_txt or self._ocr_txt
        if t:
            pyperclip.copy(t)

    def _close_all(self):
        for w in (self._toolbar, self):
            try:
                if w: w.destroy()
            except Exception:
                pass

    def destroy(self):
        try:
            if getattr(self, "_toolbar", None):
                self._toolbar.destroy()
                self._toolbar = None
        except Exception:
            pass
        super().destroy()

'''
    new_content = content[:remove_from] + new_ipo + content[remove_to:]
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[OK] Patched successfully. Removed {remove_to - remove_from} chars, inserted {len(new_ipo)} chars.")

# ── Also patch _run_ocr_translate to pass crop_img+dpi_scale ─────────────────
with open(SRC, "r", encoding="utf-8") as f:
    content = f.read()

OLD_RUN = '''    # ── OCR + 翻译 ───────────────────────────
    def _run_ocr_translate(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300):
        def _main():
            engine = self.engine_var.get()
            lang   = self.lang_var.get()
            popup  = InPlaceOverlay(self, lx1, ly1, lx2, ly2, mode="translate")'''

NEW_RUN = '''    # ── OCR + 翻译 ───────────────────────────
    def _run_ocr_translate(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300, crop_img=None):
        def _main():
            engine = self.engine_var.get()
            lang   = self.lang_var.get()
            popup  = InPlaceOverlay(self, lx1, ly1, lx2, ly2, mode="translate",
                                    bg_img=crop_img, dpi_scale=self._dpi_scale)'''

if OLD_RUN in content:
    content = content.replace(OLD_RUN, NEW_RUN, 1)
    with open(SRC, "w", encoding="utf-8") as f:
        f.write(content)
    print("[OK] _run_ocr_translate patched with crop_img+dpi_scale.")
else:
    print("[WARN] _run_ocr_translate signature not found – check manually.")

print("Patch complete.")

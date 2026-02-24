"""
微信 OCR · 截图识别 & 翻译工具
====================================
全局热键（程序最小化也有效）：
  Alt+1  →  截图翻译
  Alt+2  →  截图复制（OCR）
"""

import wcocr
import os
import threading
import tkinter as tk
from tkinter import Toplevel, Canvas, StringVar, OptionMenu
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageGrab
import pyperclip
import keyboard          # 全局热键

import sys

# ─────────────────────────────────────────────
#  路径配置
# ─────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

WECHATOCR_EXE  = os.path.join(SCRIPT_DIR, "path", "WeChatOCR", "WeChatOCR.exe")
WECHAT_LIB_DIR = os.path.join(SCRIPT_DIR, "path")
TEMP_IMG       = os.path.join(SCRIPT_DIR, "_temp_screenshot.png")

# ─────────────────────────────────────────────
#  颜色主题
# ─────────────────────────────────────────────
BG      = "#1e1e2e"
PANEL   = "#2a2a3e"
ACCENT  = "#7c6af7"
ACCENT2 = "#5bc0eb"
TEXT    = "#cdd6f4"
SUBTEXT = "#a6adc8"
SUCCESS = "#a6e3a1"
BORDER  = "#45475a"
BTN_FG  = "#ffffff"

# ─────────────────────────────────────────────
#  OCR 核心
# ─────────────────────────────────────────────
def do_ocr(image_path: str) -> str:
    try:
        wcocr.init(WECHATOCR_EXE, WECHAT_LIB_DIR)
        result = wcocr.ocr(image_path)
        lines = []
        for item in result.get("ocr_response", []):
            text = item.get("text", "")
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="ignore")
            if text.strip():
                lines.append(text)
        return "\n".join(lines) if lines else "（未识别到文字）"
    except Exception as e:
        return f"[OCR 错误] {e}"

# ─────────────────────────────────────────────
#  翻译核心（纯 urllib，零第三方依赖，国内直连）
# ─────────────────────────────────────────────
import urllib.request, urllib.parse, urllib.error, json as _json
import hmac, hashlib, time as _time

ENGINES = ["百度翻译", "有道翻译", "MyMemory"]

# 语言代码映射
_BAIDU_LANG   = {"zh":"zh","en":"en","ja":"jp","ko":"kor","fr":"fra","de":"de","es":"spa","ru":"ru","th":"th","vi":"vie"}
_YOUDAO_LANG  = {"zh":"zh-CHS","en":"en","ja":"ja","ko":"ko","fr":"fr","de":"de","es":"es","ru":"ru","th":"th","vi":"vi"}


def _load_config() -> dict:
    try:
        with open(os.path.join(SCRIPT_DIR, "config.json"), "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def _translate_baidu(text: str, to_lang: str) -> str:
    """百度翻译网页接口，国内直连，无需 API Key"""
    to = _BAIDU_LANG.get(to_lang, to_lang)
    try:
        data = urllib.parse.urlencode({
            "query": text[:2000],
            "from":  "auto",
            "to":    to,
            "source": "txt",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://fanyi.baidu.com/transapi",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer":      "https://fanyi.baidu.com/",
                "Origin":       "https://fanyi.baidu.com",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            obj = _json.loads(resp.read().decode("utf-8"))
        parts = obj.get("data", [])
        if parts:
            return "".join(p.get("dst", "") for p in parts)
    except Exception as e:
        return ""
    return ""


def _translate_youdao(text: str, to_lang: str) -> str:
    """有道翻译网页接口，国内直连，无需 API Key"""
    to = _YOUDAO_LANG.get(to_lang, to_lang)
    try:
        data = urllib.parse.urlencode({
            "q":    text[:500],
            "from": "auto",
            "to":   to,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://aidemo.youdao.com/trans",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent":   "Mozilla/5.0",
                "Referer":      "https://ai.youdao.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            obj = _json.loads(resp.read().decode("utf-8"))
        # 响应：{"translation": ["译文"]}
        t = obj.get("translation", [])
        if t and isinstance(t, list):
            return t[0] if isinstance(t[0], str) else ""
    except Exception:
        return ""
    return ""


def _translate_mymemory(text: str, to_lang: str) -> str:
    """MyMemory 公开 API，境外备用"""
    try:
        params = urllib.parse.urlencode({"q": text[:500], "langpair": f"auto|{to_lang}"})
        req = urllib.request.Request(
            f"https://api.mymemory.translated.net/get?{params}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            obj = _json.loads(resp.read().decode("utf-8"))
        return obj.get("responseData", {}).get("translatedText", "")
    except Exception:
        return ""


def do_translate(text: str, target_lang: str, engine: str = "百度翻译") -> str:
    if not text.strip() or text.startswith("[OCR 错误]"):
        return "（无内容可翻译）"

    funcs = {
        "百度翻译": _translate_baidu,
        "有道翻译": _translate_youdao,
        "MyMemory": _translate_mymemory,
    }
    order = [engine] + [e for e in ENGINES if e != engine]
    for eng in order:
        fn = funcs.get(eng)
        if fn:
            result = fn(text, target_lang)
            if result and result.strip():
                tag = f"[降级至 {eng}]\n" if eng != engine else ""
                return tag + result
    return "[翻译失败：百度/有道/MyMemory 均不可达，请检查网络]"

# ─────────────────────────────────────────────
#  截图选区（tkinter 全屏遮罩）
# ─────────────────────────────────────────────
def grab_region(app, callback):
    """在主线程中打开截图遮罩，完成后调用 callback(image_path)"""

    def _open():
        overlay = Toplevel(app)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.25)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black")
        overlay.lift()
        overlay.focus_force()

        canvas = Canvas(overlay, cursor="cross", bg="black", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        # 提示文字
        canvas.create_text(
            overlay.winfo_screenwidth() // 2,
            overlay.winfo_screenheight() // 2,
            text="拖动鼠标框选区域  ·  ESC 取消",
            fill="#ffffff", font=("微软雅黑", 18), tags="hint"
        )

        state = {"sx": 0, "sy": 0, "rect": None}

        def on_press(e):
            state["sx"], state["sy"] = e.x_root, e.y_root
            canvas.delete("hint")           # 按下后隐藏提示

        def on_drag(e):
            if state["rect"]:
                canvas.delete(state["rect"])
            rx = state["sx"] - canvas.winfo_rootx()
            ry = state["sy"] - canvas.winfo_rooty()
            state["rect"] = canvas.create_rectangle(
                rx, ry,
                e.x_root - canvas.winfo_rootx(),
                e.y_root - canvas.winfo_rooty(),
                outline="#22cc44", width=2
            )

        def on_release(e):
            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x_root, e.y_root
            overlay.destroy()
            overlay.update()

            if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
                app.after(0, lambda: app.status("框选区域太小，已取消"))
                return

            # 逻辑坐标（用于弹窗位置）
            lx1, ly1 = int(min(x1, x2)), int(min(y1, y2))
            lx2, ly2 = int(max(x1, x2)), int(max(y1, y2))

            # DPI 缩放 → 物理像素（用于截图）
            sx, sy = app._dpi_scale
            bbox = (
                int(lx1 * sx), int(ly1 * sy),
                int(lx2 * sx), int(ly2 * sy),
            )

            # 延迟 150ms 确保遗罩消失后再截图
            def _do_grab():
                import time
                time.sleep(0.15)
                img = ImageGrab.grab(bbox=bbox, all_screens=True)
                img.save(TEMP_IMG)
                # 传入逻辑坐标给 callback
                callback(TEMP_IMG, lx1, ly1, lx2, ly2)

            threading.Thread(target=_do_grab, daemon=True).start()

        canvas.bind("<ButtonPress-1>",   on_press)
        canvas.bind("<B1-Motion>",       on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", lambda e: overlay.destroy())

    app.after(0, _open)      # 必须在主线程调用 tkinter


# ─────────────────────────────────────────────
#  原位覆盖结果层（与微信截屏翻译效果相同）
# ─────────────────────────────────────────────
class InPlaceOverlay(Toplevel):
    """
    微信原生截图翻译效果：
    白色背景 + 绿色边框 + 译文直接覆盖选区 + 下方工具栏
    ❗ 必须在主线程中创建！
    """

    def __init__(self, parent, lx1: int, ly1: int, lx2: int, ly2: int, mode: str):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        # 白色背景 + 绿色边框（与微信完全一致）
        self.configure(bg="white",
                       highlightthickness=2,
                       highlightbackground="#22cc44")
        self._mode    = mode
        self._ocr_txt = ""
        self._tr_txt  = ""
        self._parent  = parent
        self._toolbar = None

        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        w  = max(lx2 - lx1, 200)
        h  = max(ly2 - ly1, 40)
        self._px = max(0, min(lx1, sw - w))
        self._py = max(0, min(ly1, sh - h))
        self._win_w, self._win_h = w, h         # 注意：不能用 self._w，那是 tkinter 内部属性
        self.geometry(f"{w}x{h}+{self._px}+{self._py}")

        # 内容标签：白底黑字，直接显示译文（与微信一致）
        init = "翻译中…" if mode == "translate" else "识别中…"
        self._text_var = tk.StringVar(value=init)
        self._lbl = tk.Label(
            self, textvariable=self._text_var,
            bg="white", fg="#111111",
            font=("微软雅黑", 11),
            wraplength=w - 16,
            justify=tk.LEFT, anchor="nw",
            padx=8, pady=6
        )
        self._lbl.pack(fill=tk.BOTH, expand=True)
        self._build_toolbar(sh)
        # 创建后立即抓取焦点，这样 ESC 无需先点击即可生效
        self.focus_force()

    def _build_toolbar(self, sh: int):
        """在选区正下方创建微信风格小工具栏"""
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
        self._tbtn(bar, "📋 复制", self._do_copy).pack(side=tk.LEFT, padx=4)
        if self._mode == "translate":
            self._tbtn(bar, "原文", self._show_ocr).pack(side=tk.LEFT, padx=2)
        self._tbtn(bar, "×", self._close_all,
                   fg="#ff5555", bg="#3d2222").pack(side=tk.RIGHT, padx=4)
        self._tbtn(bar, "✓", self._close_all,
                   fg="#44dd44", bg="#1e3323").pack(side=tk.RIGHT, padx=2)
        # ESC 关闭翻译窗
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
            self._text_var.set(text)

    def set_trans(self, text: str):
        self._tr_txt = text
        if self._mode == "translate":
            self._text_var.set(text)
            self._lbl.config(fg="#111111")

    def _show_ocr(self):
        if self._ocr_txt:
            self._text_var.set(self._ocr_txt)
            self._lbl.config(fg="#666688")

    def _do_copy(self):
        t = self._tr_txt or self._ocr_txt
        if t: pyperclip.copy(t)

    def _close_all(self):
        for w in (self._toolbar, self):
            try:
                if w: w.destroy()
            except Exception:
                pass

    def destroy(self):
        try:
            if self._toolbar:
                self._toolbar.destroy()
                self._toolbar = None
        except Exception:
            pass
        super().destroy()




try:
    import pystray as _pystray
    _PYSTRAY = True
except ImportError:
    _PYSTRAY = False
    print("[提示] 运行 pip install pystray 以启用系统托盘")

# ─────────────────────────────────────────────
#  紧凑浮动工具条（主窗口）
# ─────────────────────────────────────────────
class CompactBar(tk.Tk):
    """
    橙黄色小工具条，模仿参考图：
      [ 微信OCR ][ 提取文字 | 截图 | 译 ][ ﹣ ]
    系统托盘右键菜单：显示窗口 / 隐藏窗口 / 快捷键... / 退出
    """
    BAR_BG  = "#f5a623"
    HOV_BG  = "#d9891a"
    TXT_COL = "#1a1a1a"

    def __init__(self):
        super().__init__()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.BAR_BG)
        self.resizable(False, False)

        self._tray   = None
        self._dx = self._dy = 0
        self.engine_var = StringVar(self, value="百度翻译")
        self.lang_var   = StringVar(self, value="zh")
        self._dpi_scale = self._calc_dpi()

        # 屏幕上方居中初始位置
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"+{(sw - 330) // 2}+0")

        self._build()
        self._register_hotkeys()
        self._setup_tray()

    # ── DPI ──────────────────────────────────
    def _calc_dpi(self):
        try:
            lw = self.winfo_screenwidth()
            lh = self.winfo_screenheight()
            im = ImageGrab.grab()
            return im.width / lw, im.height / lh
        except Exception:
            return 1.0, 1.0

    # ── 工具条 UI ────────────────────────────
    def _build(self):
        # 可拖动标题
        title = tk.Label(self, text="微信 OCR",
                         bg=self.BAR_BG, fg=self.TXT_COL,
                         font=("微软雅黑", 9, "bold"),
                         padx=10, pady=6)
        title.pack(side=tk.LEFT)
        title.bind("<ButtonPress-1>", lambda e: (setattr(self,"_dx",e.x), setattr(self,"_dy",e.y)))
        title.bind("<B1-Motion>",     lambda e: self.geometry(
            f"+{self.winfo_x()+e.x-self._dx}+{self.winfo_y()+e.y-self._dy}"))
        title.bind("<Double-Button-1>", lambda e: self.hide_bar()) # 双击隐藏到托盘

        # 右键呼出设置
        self.bind("<Button-3>", lambda e: self.after(0, self._hotkeys_dialog))
        title.bind("<Button-3>", lambda e: self.after(0, self._hotkeys_dialog) or "break")

        for label, mode in [("提取文字","ocr"), ("截  图","screenshot"), ("译","translate")]:
            self._div()
            self._bb(label, lambda m=mode: self._cap(m))

        # 最小化按钮
        self._div()
        tk.Button(self, text="﹣", bg=self.BAR_BG, fg=self.TXT_COL,
                  font=("微软雅黑", 10), bd=0, padx=8, pady=5,
                  cursor="hand2", activebackground=self.HOV_BG,
                  command=self.hide_bar).pack(side=tk.LEFT)

    def _div(self):
        tk.Frame(self, bg="#cc8800", width=1).pack(
            side=tk.LEFT, fill=tk.Y, pady=3)

    def _bb(self, text, cmd):
        b = tk.Button(self, text=text,
                      bg=self.BAR_BG, fg=self.TXT_COL,
                      font=("微软雅黑", 9), bd=0, relief=tk.FLAT,
                      padx=10, pady=5, cursor="hand2",
                      activebackground=self.HOV_BG,
                      activeforeground=self.TXT_COL,
                      command=cmd)
        b.pack(side=tk.LEFT)

    # ── 热键 ─────────────────────────────────
    def _register_hotkeys(self):
        try:
            cfg = _load_config().get("hotkeys", {})
            h1 = cfg.get("translate", "alt+1")
            h2 = cfg.get("ocr", "alt+2")
            keyboard.add_hotkey(h1, lambda: self.after(0, lambda: self._cap("translate")))
            keyboard.add_hotkey(h2, lambda: self.after(0, lambda: self._cap("ocr")))
        except Exception as ex:
            print(f"[热键注册失败] {ex}（需要管理员权限，或快捷键冲突）")

    # ── 系统托盘 ─────────────────────────────
    def _setup_tray(self):
        if not _PYSTRAY:
            return
        from PIL import ImageDraw as _IDraw
        sz  = 64
        ico = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d   = _IDraw.Draw(ico)
        d.ellipse([2, 2, sz-2, sz-2], fill="#7c6af7")
        d.text((12, 18), "OCR", fill="white")

        menu = _pystray.Menu(
            # default=True 在 Windows 下绑定双击事件
            _pystray.MenuItem("显示/隐藏", lambda *_: self.after(0, self._toggle_bar), default=True),
            _pystray.Menu.SEPARATOR,
            _pystray.MenuItem("显示窗口",  lambda *_: self.after(0, self.show_bar)),
            _pystray.MenuItem("隐藏窗口",  lambda *_: self.after(0, self.hide_bar)),
            _pystray.Menu.SEPARATOR,
            _pystray.MenuItem("快捷键...", lambda *_: self.after(0, self._hotkeys_dialog)),
            _pystray.Menu.SEPARATOR,
            _pystray.MenuItem("退出",      lambda *_: self.after(0, self._quit_all)),
        )
        self._tray = _pystray.Icon("wechat_ocr", ico, "微信 OCR", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def show_bar(self):
        self.deiconify()
        self.attributes("-topmost", True)

    def hide_bar(self):
        self.withdraw()

    def _toggle_bar(self, *_):
        if self.state() == "withdrawn":
            self.show_bar()
        else:
            self.hide_bar()

    def _quit_all(self):
        if self._tray:
            try: self._tray.stop()
            except Exception: pass
        try: keyboard.unhook_all()
        except Exception: pass
        self.destroy()

    # ── 设置/快捷键对话框 ────────────────────
    def _hotkeys_dialog(self):
        if getattr(self, "_hd_open", False):
            try: self._hd.focus_force()
            except: pass
            return
        self._hd_open = True

        d = Toplevel(self)
        self._hd = d
        d.title("设置")
        d.configure(bg=BG)
        d.resizable(False, False)
        d.attributes("-topmost", True)
        d.geometry("380x440")
        
        def _on_close():
            self._hd_open = False
            d.destroy()
        d.protocol("WM_DELETE_WINDOW", _on_close)

        tk.Label(d, text="⌨  快捷键", bg=BG, fg=ACCENT,
                 font=("微软雅黑", 11, "bold")).pack(pady=(16, 4))
        tk.Label(d, text="（点击输入框后直接按下快捷键即可）", bg=BG, fg=SUBTEXT,
                 font=("微软雅黑", 8)).pack(pady=(0, 6))

        cfg_hk = _load_config().get("hotkeys", {})
        
        def _bind_hk_recorder(entry):
            def _on_key(e):
                if e.keysym in ("Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R", "Win_L", "Win_R"):
                    return "break"
                mods = []
                if e.state & 0x0004: mods.append("ctrl")
                if e.state & 131072: mods.append("alt") # Windows的Alt主要是此位 (0x20000)
                if e.state & 0x0001: mods.append("shift")
                
                k = e.keysym.lower()
                if k.startswith("mouse") or not k: return "break"
                
                km = {"prior": "page up", "next": "page down", "return": "enter", "escape": "esc"}
                k = km.get(k, k)
                hk = "+".join(mods + [k])
                entry.delete(0, tk.END)
                entry.insert(0, hk)
                return "break"
            entry.bind("<Key>", _on_key)

        row1 = tk.Frame(d, bg=BG)
        row1.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row1, text="截图翻译:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk1_entry = tk.Entry(row1, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk1_entry.pack(side=tk.RIGHT)
        hk1_entry.insert(0, cfg_hk.get("translate", "alt+1"))
        _bind_hk_recorder(hk1_entry)

        row2 = tk.Frame(d, bg=BG)
        row2.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row2, text="提取文字 (截图复制):", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk2_entry = tk.Entry(row2, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk2_entry.pack(side=tk.RIGHT)
        hk2_entry.insert(0, cfg_hk.get("ocr", "alt+2"))
        _bind_hk_recorder(hk2_entry)

        tk.Frame(d, bg=BORDER, height=1).pack(fill=tk.X, padx=16, pady=6)
        tk.Label(d, text="🌐  翻译设置", bg=BG, fg=ACCENT,
                 font=("微软雅黑", 11, "bold")).pack()

        row2 = tk.Frame(d, bg=BG)
        row2.pack(fill=tk.X, padx=24, pady=6)
        tk.Label(row2, text="引擎:", bg=BG, fg=SUBTEXT,
                 font=("微软雅黑", 9), width=5, anchor="w").pack(side=tk.LEFT)
        OptionMenu(row2, self.engine_var, *ENGINES).pack(side=tk.LEFT, padx=4)
        tk.Label(row2, text="语言:", bg=BG, fg=SUBTEXT,
                 font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=(8, 0))
        OptionMenu(row2, self.lang_var,
                   "zh","en","ja","ko","fr","de","es","ru","th","vi").pack(side=tk.LEFT, padx=4)

        tk.Button(d, text="保存并关闭", bg=ACCENT, fg=BTN_FG,
                  font=("微软雅黑", 10), bd=0, padx=16, pady=6,
                  cursor="hand2", command=lambda: save_and_close(d)).pack(pady=10)

        def save_and_close(window):
            new_cfg = _load_config()
            new_cfg["hotkeys"] = {
                "translate": hk1_entry.get().strip() or "alt+1",
                "ocr": hk2_entry.get().strip() or "alt+2"
            }
            try:
                with open(os.path.join(SCRIPT_DIR, "config.json"), "w", encoding="utf-8") as f:
                    _json.dump(new_cfg, f, indent=4, ensure_ascii=False)
            except Exception:
                pass
            
            # 重新注册热键
            try:
                keyboard.unhook_all()
                self._register_hotkeys()
            except Exception:
                pass
                
            self._hd_open = False
            window.destroy()

    # ── 截图入口 ─────────────────────────────
    def _cap(self, mode: str):
        # 截图提取文字/翻译时不再隐藏工具条
        # self.withdraw()  
        cb_map = {
            "ocr":        self._run_ocr_only,
            "translate":  self._run_ocr_translate,
            "screenshot": self._run_screenshot,
        }
        self.after(200, lambda: grab_region(self, cb_map.get(mode, self._run_ocr_only)))

    # ── 提取文字（OCR 复制）────────────────
    def _run_ocr_only(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300):
        def _main():
            def worker():
                text = do_ocr(img_path)
                if text and not text.startswith("["):
                    pyperclip.copy(text)
                    self.after(0, lambda: self._toast(f"✅ 已复制 {len(text)} 字符"))
                else:
                    self.after(0, lambda: self._toast(f"识别失败"))
            threading.Thread(target=worker, daemon=True).start()
        self.after(0, _main)

    # ── 截图到剪贴板 ─────────────────────────
    def _run_screenshot(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300):
        import subprocess
        def _main():
            try:
                ps = (f'Add-Type -AssemblyName System.Windows.Forms,System.Drawing;'
                      f'[System.Windows.Forms.Clipboard]::SetImage('
                      f'[System.Drawing.Image]::FromFile("{img_path}"))')
                subprocess.run(["powershell", "-Command", ps],
                               capture_output=True, timeout=6)
                self.after(0, lambda: self._toast("✅ 截图已复制到剪贴板"))
            except Exception as ex:
                self.after(0, lambda: self._toast(f"截图失败: {ex}"))
        self.after(0, _main)

    # ── OCR + 翻译 ───────────────────────────
    def _run_ocr_translate(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300):
        def _main():
            engine = self.engine_var.get()
            lang   = self.lang_var.get()
            popup  = InPlaceOverlay(self, lx1, ly1, lx2, ly2, mode="translate")

            def worker():
                text = do_ocr(img_path)
                self.after(0, lambda: popup.set_ocr(text))
                translated = do_translate(text, target_lang=lang, engine=engine)
                self.after(0, lambda: popup.set_trans(translated))
            threading.Thread(target=worker, daemon=True).start()
        self.after(0, _main)

    # ── Toast 通知 ───────────────────────────
    def _toast(self, msg: str, ms: int = 2500):
        t = Toplevel(self)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg="#333344")
        tk.Label(t, text=msg, bg="#333344", fg="#ffffff",
                 font=("微软雅黑", 10), padx=14, pady=8).pack()
        t.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        tw, th = t.winfo_width(), t.winfo_height()
        t.geometry(f"+{(sw-tw)//2}+{sh-th-70}")
        self.after(ms, t.destroy)

    def status(self, msg: str): pass   # stub

    def destroy(self):
        try: keyboard.unhook_all()
        except Exception: pass
        super().destroy()


# ─────────────────────────────────────────────
if __name__ == "__main__":
    app = CompactBar()
    app.mainloop()

# EOF

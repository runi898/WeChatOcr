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
import ctypes
from ctypes import wintypes
# 移除 keyboard 组件，改用 Win32 API 稳定方案（无系统静默挂起问题）

import sys

# ─────────────────────────────────────────────
#  路径配置
# ─────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    # PyInstaller 单文件模式：资源解压到临时目录 sys._MEIPASS
    _RES_DIR = sys._MEIPASS
else:
    _RES_DIR = os.path.dirname(os.path.abspath(__file__))

# 可写目录：%APPDATA%/wechatocr
_appdata = os.getenv('APPDATA') or os.path.expanduser('~\\AppData\\Roaming')
_WRITE_DIR = os.path.join(_appdata, 'wechatocr')
os.makedirs(_WRITE_DIR, exist_ok=True)

SCRIPT_DIR     = _WRITE_DIR          # 保持兼容（config.json 路径用）
WECHATOCR_EXE  = os.path.join(_RES_DIR, "path", "WeChatOCR", "WeChatOCR.exe")
WECHAT_LIB_DIR = os.path.join(_RES_DIR, "path")
TEMP_IMG       = os.path.join(_WRITE_DIR, "_temp_screenshot.png")

HOTKEY_LOG = os.path.join(_WRITE_DIR, "hotkey_debug.log")

def _kbd_state_snapshot():
    return "[kbd状态] 使用 Win32 API 原生热键，已解决静默失效问题"

def _hklog(msg: str, level: str = "info", with_kbd_state: bool = True):
    """写入热键诊断日志，带时间戳、级别标签和可选的键盘系统状态快照"""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 限制日志大小，超过 2MB 则截断前一半（避免积留过大文件）
    try:
        if os.path.exists(HOTKEY_LOG) and os.path.getsize(HOTKEY_LOG) > 2 * 1024 * 1024:
            with open(HOTKEY_LOG, "r", encoding="utf-8") as f:
                lines = f.readlines()
            with open(HOTKEY_LOG, "w", encoding="utf-8") as f:
                f.writelines(lines[len(lines)//2:])
    except Exception:
        pass

    kbd_info = f"  {_kbd_state_snapshot()}" if with_kbd_state else ""
    full_msg = f"{now} [{level.upper()}] {msg}{kbd_info}\n"

    try:
        with open(HOTKEY_LOG, "a", encoding="utf-8") as f:
            f.write(full_msg)
    except Exception:
        pass
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

# 修复：wcocr.init 只能调用一次，每次重新启动 WeChatOCR.exe
# 子进程在 Win10 Defender 或杀毒软件扫描下可能阻塞数秒乃至更久，
# 从而卡死 OCR worker 线程（表现：截图后程序假死/转圈）。
# 改为全局只初始化一次，之后所有调用复用同一进程通道。
_wcocr_initialized = False
_wcocr_init_lock   = threading.Lock()

def _ensure_wcocr_init():
    global _wcocr_initialized
    if _wcocr_initialized:
        return
    with _wcocr_init_lock:
        if not _wcocr_initialized:  # double-check
            wcocr.init(WECHATOCR_EXE, WECHAT_LIB_DIR)
            _wcocr_initialized = True

def do_ocr(image_path: str) -> str:
    res = do_ocr_raw(image_path)
    if isinstance(res, str):
        return res
    lines = [item["text"] for item in res if item["text"].strip()]
    return "\n".join(lines) if lines else "（未识别到文字）"

def do_ocr_raw(image_path: str):
    """返回原始结果: [{'text': 'abc', 'left': x, 'top': y, 'right': x, 'bottom': y}, ...]"""
    try:
        _ensure_wcocr_init()
        result = wcocr.ocr(image_path)
        items = []
        for item in result.get("ocr_response", []):
            text = item.get("text", "")
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="ignore")
            if text.strip():
                items.append({
                    "text": text,
                    "left": item.get("left", 0),
                    "top": item.get("top", 0),
                    "right": item.get("right", 0),
                    "bottom": item.get("bottom", 0)
                })
        return items
    except Exception as e:
        return f"[OCR 错误] {e}"

# ─────────────────────────────────────────────
#  翻译核心（纯 urllib，零第三方依赖，国内直连）
# ─────────────────────────────────────────────
import urllib.request, urllib.parse, urllib.error, json as _json
import hmac, hashlib, time as _time

ENGINES = ["腾讯翻译", "百度翻译", "有道翻译", "MyMemory"]

# 语言代码映射
_TENCENT_LANG = {
    "zh": "zh", "en": "en", "ja": "ja", "ko": "ko",
    "fr": "fr", "de": "de", "es": "es", "ru": "ru",
    "th": "th", "vi": "vi",
}
_BAIDU_LANG   = {"zh":"zh","en":"en","ja":"jp","ko":"kor","fr":"fra","de":"de","es":"spa","ru":"ru","th":"th","vi":"vie"}
_YOUDAO_LANG  = {"zh":"zh-CHS","en":"en","ja":"ja","ko":"ko","fr":"fr","de":"de","es":"es","ru":"ru","th":"th","vi":"vi"}


def _load_config() -> dict:
    try:
        with open(os.path.join(SCRIPT_DIR, "config.json"), "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return {}


def _translate_tencent(text: str, to_lang: str) -> str:
    """腾讯云机器翻译 API，TC3-HMAC-SHA256 签名"""
    cfg        = _load_config().get("tencent", {})
    secret_id  = cfg.get("secret_id",  "")
    secret_key = cfg.get("secret_key", "")
    region     = cfg.get("region", "ap-beijing")
    if not secret_id or not secret_key or "填入" in secret_id:
        return ""   # 密鑰未配置

    to      = _TENCENT_LANG.get(to_lang, to_lang)
    payload = _json.dumps({"SourceText": text[:2000], "Source": "auto",
                           "Target": to, "ProjectId": 0}, ensure_ascii=False)
    host    = "tmt.tencentcloudapi.com"
    service = "tmt"
    ts      = int(_time.time())
    date    = _time.strftime("%Y-%m-%d", _time.gmtime(ts))

    hp  = hashlib.sha256(payload.encode()).hexdigest()
    ch  = f"content-type:application/json; charset=utf-8\nhost:{host}\n"
    sh  = "content-type;host"
    cr  = "\n".join(["POST", "/", "", ch, sh, hp])
    cs  = f"{date}/{service}/tc3_request"
    hcr = hashlib.sha256(cr.encode()).hexdigest()
    s2s = "\n".join(["TC3-HMAC-SHA256", str(ts), cs, hcr])

    def _h(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    sk  = _h(_h(_h(("TC3"+secret_key).encode(), date), service), "tc3_request")
    sig = hmac.new(sk, s2s.encode(), hashlib.sha256).hexdigest()
    auth = (f"TC3-HMAC-SHA256 Credential={secret_id}/{cs}, "
            f"SignedHeaders={sh}, Signature={sig}")
    try:
        req = urllib.request.Request(
            f"https://{host}", data=payload.encode(),
            headers={"Authorization": auth,
                     "Content-Type": "application/json; charset=utf-8",
                     "Host": host, "X-TC-Action": "TextTranslate",
                     "X-TC-Timestamp": str(ts), "X-TC-Version": "2018-03-21",
                     "X-TC-Region": region})
        with urllib.request.urlopen(req, timeout=10) as resp:
            obj = _json.loads(resp.read().decode())
        return obj.get("Response", {}).get("TargetText", "")
    except Exception:
        return ""


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


def do_translate(text: str, target_lang: str, engine: str = "腾讯翻译") -> str:
    if not text.strip() or text.startswith("[OCR 错误]"):
        return "（无内容可翻译）"

    funcs = {
        "腾讯翻译": _translate_tencent,
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

    return "（已收到识别结果直接展示）\n\n[翻译失败：所有免费接口（百度/有道/MyMemory）均不可达或被频率限制，请稍微检查网络后再试]"

# ─────────────────────────────────────────────
#  截图选区（tkinter 全屏遮罩）
# ─────────────────────────────────────────────
def grab_region(app, callback, mode_name=""):
    """在主线程中打开截图遮罩，完成后调用 callback(image_path)
    支持多显示器：遮罩覆盖全部屏幕（含副屏/负坐标显示器）
    支持右键或 ESC 取消截图
    """

    def _open():
        # ── 获取虚拟屏幕范围（所有显示器合并后的总区域）──────
        try:
            import ctypes
            SM_XVIRTUALSCREEN  = 76   # 虚拟屏幕左边界（副屏在左时为负）
            SM_YVIRTUALSCREEN  = 77   # 虚拟屏幕上边界（副屏在上时为负）
            SM_CXVIRTUALSCREEN = 78   # 虚拟屏幕总宽度
            SM_CYVIRTUALSCREEN = 79   # 虚拟屏幕总高度
            u32 = ctypes.windll.user32
            vx  = u32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            vy  = u32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            vw  = u32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            vh  = u32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        except Exception:
            vx, vy = 0, 0
            vw = app.winfo_screenwidth()
            vh = app.winfo_screenheight()

        overlay = Toplevel(app)
        overlay.overrideredirect(True)                    # 无边框
        overlay.geometry(f"{vw}x{vh}+{vx}+{vy}")         # 覆盖全部显示器
        overlay.attributes("-alpha",   0.25)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black")
        overlay.lift()
        overlay.focus_force()

        canvas = Canvas(overlay, cursor="cross", bg="black",
                        highlightthickness=0, width=vw, height=vh)
        canvas.pack(fill=tk.BOTH, expand=True)

        # 提示文字（显示在虚拟屏幕中心）
        hint_str = "拖动鼠标框选区域"
        if mode_name:
            hint_str = f"[{mode_name}] " + hint_str
        hint_str += "  ·  右键 或 ESC 取消"
        
        canvas.create_text(
            vw // 2, vh // 2,
            text=hint_str,
            fill="#ffffff", font=("微软雅黑", 18), tags="hint"
        )

        state = {"sx": 0, "sy": 0, "rect": None}

        def on_press(e):
            state["sx"], state["sy"] = e.x_root, e.y_root
            canvas.delete("hint")           # 按下后隐藏提示

        def on_drag(e):
            if state["rect"]:
                canvas.delete(state["rect"])
            # e.x_root/y_root 是绝对屏幕坐标，转为 canvas 内坐标
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

            # 逻辑坐标（用于弹窗位置，可能包含<0的副屏坐标）
            lx1, ly1 = int(min(x1, x2)), int(min(y1, y2))
            lx2, ly2 = int(max(x1, x2)), int(max(y1, y2))

            # DPI 缩放 → 物理像素（用于截图，all_screens=True 支持负坐标）
            sx, sy = app._dpi_scale
            bbox = (
                int(lx1 * sx), int(ly1 * sy),
                int(lx2 * sx), int(ly2 * sy),
            )

            # 延迟 150ms 确保遮罩消失后再截图
            # 修复：callback 必须在主线程（tkinter 要求），
            # 子线程只负责截图 I/O，完成后通过 app.after() 调度回主线程执行 callback。
            def _do_grab():
                import time
                time.sleep(0.15)
                img = ImageGrab.grab(bbox=bbox, all_screens=True)
                img.save(TEMP_IMG)
                # 回到主线程再调用 callback，彻底避免跨线程 tkinter 操作
                app.after(0, lambda: callback(TEMP_IMG, lx1, ly1, lx2, ly2))

            threading.Thread(target=_do_grab, daemon=True).start()

        def _cancel(e=None):
            overlay.destroy()
            app.status("已取消截图")
            return "break"

        def _rclick_press(e):
            return "break"   # 消耗右键按下事件，防止弹出底层的系统菜单

        def _rclick_release(e):
            return _cancel()

        canvas.bind("<ButtonPress-1>",   on_press)
        canvas.bind("<B1-Motion>",       on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        
        # 右键退出绑定（必须同时吸收 Press 和 Release，避免底层冒泡）
        canvas.bind("<ButtonPress-3>",   _rclick_press)
        canvas.bind("<ButtonRelease-3>", _rclick_release)
        overlay.bind("<ButtonPress-3>",  _rclick_press)
        overlay.bind("<ButtonRelease-3>",_rclick_release)
        
        overlay.bind("<Escape>", _cancel)

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
        self._trans_labels = []

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

    def set_trans(self, text: str, items=None):
        self._tr_txt = text
        if self._mode == "translate":
            self._lbl.config(fg="#111111")
            
            # 清理旧的独立标签
            for lbl in self._trans_labels:
                lbl.destroy()
            self._trans_labels.clear()
            
            # 基础宽高
            w = self.winfo_width()
            sw = self.winfo_screenwidth()
            
            # ========================
            # 多排版智能渲染（如果有坐标+行数对应）
            # ========================
            if items:
                # 把原文和翻译结果按行拆分进行数量比对
                translated_lines = [l.strip() for l in text.split("\n") if l.strip()]
                original_lines = [item for item in items if item.get("text", "").strip()]
                
                if len(translated_lines) == len(original_lines) and len(original_lines) > 0:
                    # ✅ 美好情况：翻译结果的行数和原文一致！完美执行原位覆盖！
                    # 我们先把原本用于显示大段落的大 Label 隐藏掉：
                    self._text_var.set("")
                    self._lbl.config(wraplength=0) # 禁用
                    
                    # 为了确定新窗口大小，追踪最底部的文字边界
                    max_bottom = 0
                    min_left = sw
                    max_right = 0
                    
                    for idx, item in enumerate(original_lines):
                        t_txt = translated_lines[idx]
                        
                        # 解析原本的坐标
                        left = int(item["left"])
                        top = int(item["top"])
                        right = int(item["right"])
                        bot = int(item["bottom"])
                        
                        # 行高和最大宽度
                        row_h = bot - top
                        row_w = max(50, right - left) # 宽度给足一点
                        
                        # 为了避免完全遮挡原来图片的间隙，给个细微修正
                        lbl = tk.Label(self, text=t_txt,
                                     bg="#eef2f5", fg="#111111", 
                                     font=("微软雅黑", max(9, min(14, int(row_h * 0.7)))),
                                     justify=tk.LEFT, anchor="nw", 
                                     wraplength=row_w + 100)
                        
                        # 覆盖在原图片的准确位置上，向外拓宽一点点视觉效果更好
                        x_pos = max(0, left - 4)
                        y_pos = max(0, top - 2)
                        
                        lbl.place(x=x_pos, y=y_pos)
                        self._trans_labels.append(lbl)
                        
                        # 修复：update_idletasks 必须在主线程调用，
                        # 用 winfo_reqheight/width 前先安全地刷新布局
                        try:
                            lbl.update_idletasks()
                        except Exception:
                            pass
                        l_reqh = lbl.winfo_reqheight()
                        
                        max_bottom = max(max_bottom, y_pos + l_reqh)
                        min_left = min(min_left, x_pos)
                        max_right = max(max_right, x_pos + lbl.winfo_reqwidth())
                        
                    req_h = max_bottom + 16
                    new_w = max(w, max_right - min_left + 10)
                else:
                    # ❌ 糟糕情况：遇到大长句，翻译引擎把它合并成了1段或重新分段了。
                    # 回退到我们以前的中心展示模式
                    self._text_var.set(text)
                    self._lbl.config(wraplength=max(200, w - 20))
                    self.update_idletasks()
                    req_h = self._lbl.winfo_reqheight() + 16
                    new_w = w
            else:
                self._text_var.set(text)
                self._lbl.config(wraplength=max(200, w - 20))
                self.update_idletasks()
                req_h = self._lbl.winfo_reqheight() + 16
                new_w = w

            new_h = max(self._win_h, req_h)
            new_w = max(new_w, self.winfo_width())
            
            x = self.winfo_x()
            y = self.winfo_y()
            if x + new_w > sw - 10:
                x = max(10, sw - new_w - 10)
            
            self.geometry(f"{new_w}x{new_h}+{x}+{y}")
            self._win_h = new_h
            
            if getattr(self, "_toolbar", None):
                tb_w, tb_h = 240, 34
                tx = x + (new_w - tb_w) // 2
                ty = y + new_h + 3
                if ty + tb_h > self.winfo_screenheight() - 10:
                    ty = y - tb_h - 3
                self._toolbar.geometry(f"{tb_w}x{tb_h}+{tx}+{ty}")

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
            if getattr(self, "_toolbar", None):
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

class Win32HotkeyManager:
    """原生的 Win32 消息循环热键管理器，系统级接管，彻底解决因为卡顿或UAC导致的钩子静默丢弃问题。"""
    def __init__(self, app, callback):
        self.app = app
        self.callback = callback
        self._thread = None
        self._thread_id = None
        
    def _parse_hotkey(self, hk_str):
        mods, vk = 0, 0
        parts = str(hk_str).lower().split('+')
        # MOD_ALT=1, MOD_CTRL=2, MOD_SHIFT=4, MOD_WIN=8
        vk_map = {'page up': 0x21, 'page down': 0x22, 'end': 0x23, 'home': 0x24,
                  'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28, 'enter': 0x0D, 'esc': 0x1B}
        for p in parts:
            p = p.strip()
            if not p: continue
            if p == 'ctrl': mods |= 2
            elif p in ('alt', 'option'): mods |= 1
            elif p == 'shift': mods |= 4
            elif p in ('win', 'windows', 'command'): mods |= 8
            elif p in vk_map: vk = vk_map[p]
            elif len(p) == 1: vk = ord(p.upper())
            elif p.startswith('f') and p[1:].isdigit(): vk = 0x6F + int(p[1:])
        return mods, vk

    def start(self, hotkeys_dict):
        self.stop()
        started = threading.Event()
        
        def _run():
            try:
                self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
                user32 = ctypes.windll.user32
                actions = {}
                for icls, (mode, hk_str) in enumerate(hotkeys_dict.items(), 1):
                    mods, vk = self._parse_hotkey(hk_str)
                    if vk:
                        user32.RegisterHotKey(None, icls, mods | 0x4000, vk) # 0x4000=MOD_NOREPEAT
                        actions[icls] = mode
                
                started.set()
                msg = wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == 0x0312:  # WM_HOTKEY
                        action = actions.get(msg.wParam)
                        if action:
                            # 必须通过 tkinter.after 在主线程执行，避免跨线程调用异常
                            self.app.after(0, lambda a=action: self.callback(a))
                    elif msg.message == 0x0012: # WM_QUIT
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                    
                for icls in actions:
                    user32.UnregisterHotKey(None, icls)
            except Exception as e:
                import traceback
                traceback.print_exc()
        
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        started.wait(timeout=2.0)

    def stop(self):
        if self._thread and self._thread.is_alive() and getattr(self, '_thread_id', None):
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
            self._thread.join(timeout=1.0)
            self._thread_id = None

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
        self.engine_var = StringVar(self, value="腾讯翻译")
        self.lang_var   = StringVar(self, value="zh")
        self._dpi_scale = self._calc_dpi()
        
        # 设置窗口图标
        ico_path = os.path.join(_RES_DIR, "icon.ico")
        try:
            self.iconbitmap(ico_path)
        except Exception:
            pass

        # 屏幕上方居中初始位置
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        self.geometry(f"+{(sw - 330) // 2}+0")

        self._build()
        self._registered_hotkeys = {}   # 记录已注册热键 {action: combo}
        self._hotkey_mgr = Win32HotkeyManager(self, self._cap)
        self._register_hotkeys()
        self._setup_tray()
        # watchdog 不再需要，Win32 API 安全稳定不再掉签

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

        for label, mode in [("提取文字","ocr"), ("截  图","screenshot"), ("译","translate"), ("扫  码","qrcode"), ("生成QR","gen_qr")]:
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
        _hklog(">>> _register_hotkeys() 调用开始 (Win32 API)")
        try:
            cfg = _load_config().get("hotkeys", {})
            h1 = cfg.get("translate", "alt+1")
            h2 = cfg.get("ocr", "alt+2")
            h3 = cfg.get("screenshot", "alt+3")
            h4 = cfg.get("qrcode", "alt+4")
            h5 = cfg.get("gen_qr", "alt+5")
            _hklog(f"    准备注册 (Win32): translate={h1!r}  ocr={h2!r} screenshot={h3!r} qrcode={h4!r} gen_qr={h5!r}")
            
            self._registered_hotkeys = {"translate": h1, "ocr": h2, "screenshot": h3, "qrcode": h4, "gen_qr": h5}
            self._hotkey_mgr.start(self._registered_hotkeys)
            
            _hklog(f"    热键注册成功: {self._registered_hotkeys}")
        except Exception as ex:
            _hklog(f"!!! 热键注册失败: {ex}", "error")
            print(f"[热键注册失败] {ex}")

    def _hotkey_watchdog(self):
        pass # 已废弃，因为我们改用了原生稳定的 Win32HotkeyManager

    # ── 系统托盘 ─────────────────────────────
    def _setup_tray(self):
        if not _PYSTRAY:
            return
        
        ico_path = os.path.join(_RES_DIR, "icon.ico")
        try:
            ico = Image.open(ico_path)
        except Exception:
            # 兼容处理
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
        try: getattr(self, '_hotkey_mgr', None) and self._hotkey_mgr.stop()
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
        d.geometry("380x560")
        
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

        row3 = tk.Frame(d, bg=BG)
        row3.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row3, text="简单截图 (复制):", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk3_entry = tk.Entry(row3, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk3_entry.pack(side=tk.RIGHT)
        hk3_entry.insert(0, cfg_hk.get("screenshot", "alt+3"))
        _bind_hk_recorder(hk3_entry)

        row4 = tk.Frame(d, bg=BG)
        row4.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row4, text="识别二维码:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk4_entry = tk.Entry(row4, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk4_entry.pack(side=tk.RIGHT)
        hk4_entry.insert(0, cfg_hk.get("qrcode", "alt+4"))
        _bind_hk_recorder(hk4_entry)

        row5 = tk.Frame(d, bg=BG)
        row5.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row5, text="生成二维码:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk5_entry = tk.Entry(row5, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk5_entry.pack(side=tk.RIGHT)
        hk5_entry.insert(0, cfg_hk.get("gen_qr", "alt+5"))
        _bind_hk_recorder(hk5_entry)

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

        tc_frame = tk.Frame(d, bg=BG)
        cfg = _load_config().get("tencent", {})
        tk.Label(tc_frame, text="SecretId:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(anchor="w", padx=24)
        id_entry = tk.Entry(tc_frame, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9))
        id_entry.pack(fill=tk.X, padx=24, pady=2)
        id_entry.insert(0, cfg.get("secret_id", ""))
        tk.Label(tc_frame, text="SecretKey:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(anchor="w", padx=24, pady=(4,0))
        key_entry = tk.Entry(tc_frame, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), show="*")
        key_entry.pack(fill=tk.X, padx=24, pady=2)
        key_entry.insert(0, cfg.get("secret_key", ""))

        def _update_tc_frame(*args):
            if self.engine_var.get() == "腾讯翻译":
                tc_frame.pack(fill=tk.X, pady=6)
            else:
                tc_frame.pack_forget()

        self.engine_var.trace_add("write", _update_tc_frame)
        _update_tc_frame() # initial call

        btn_frame = tk.Frame(d, bg=BG)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="保存并关闭", bg=ACCENT, fg=BTN_FG,
                  font=("微软雅黑", 10), bd=0, padx=16, pady=6,
                  cursor="hand2", command=lambda: save_and_close(d)).pack(side=tk.LEFT, padx=6)

        tk.Button(btn_frame, text="📋 查看诊断日志", bg="#2a2a3e", fg="#a6adc8",
                  font=("微软雅黑", 9), bd=0, padx=10, pady=6,
                  cursor="hand2", command=self._show_log_dialog).pack(side=tk.LEFT, padx=6)

        def save_and_close(window):
            new_cfg = _load_config()
            new_cfg["tencent"] = {
                "secret_id": id_entry.get().strip(),
                "secret_key": key_entry.get().strip(),
                "region": cfg.get("region", "ap-beijing")
            }
            new_cfg["hotkeys"] = {
                "translate": hk1_entry.get().strip() or "alt+1",
                "ocr": hk2_entry.get().strip() or "alt+2",
                "screenshot": hk3_entry.get().strip() or "alt+3",
                "qrcode": hk4_entry.get().strip() or "alt+4",
                "gen_qr": hk5_entry.get().strip() or "alt+5"
            }
            try:
                with open(os.path.join(SCRIPT_DIR, "config.json"), "w", encoding="utf-8") as f:
                    _json.dump(new_cfg, f, indent=4, ensure_ascii=False)
            except Exception:
                pass
            
            # 重新注册热键
            try:
                self._register_hotkeys()
            except Exception:
                pass
                
            self._hd_open = False
            window.destroy()

    # ── 诊断日志查看器 ────────────────────────
    def _show_log_dialog(self):
        """打开一个简单的日志查看窗口，显示 hotkey_debug.log 内容"""
        lw = Toplevel(self)
        lw.title(f"热键诊断日志  ({HOTKEY_LOG})")
        lw.configure(bg=BG)
        lw.geometry("780x480")
        lw.attributes("-topmost", True)

        # 顶部说明
        info_frame = tk.Frame(lw, bg=BG)
        info_frame.pack(fill=tk.X, padx=10, pady=(8, 0))
        tk.Label(info_frame, text="📄 热键诊断日志",
                 bg=BG, fg=ACCENT, font=("微软雅黑", 11, "bold")).pack(side=tk.LEFT)
        tk.Label(info_frame, text=f"  {HOTKEY_LOG}",
                 bg=BG, fg=SUBTEXT, font=("微软雅黑", 8)).pack(side=tk.LEFT)

        # 日志文本框
        txt = ScrolledText(lw, bg="#0d0d1a", fg="#ccddcc",
                           font=("Consolas", 9), wrap=tk.NONE,
                           relief=tk.FLAT, padx=6, pady=6)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        def _load():
            txt.config(state=tk.NORMAL)
            txt.delete(1.0, tk.END)
            try:
                if os.path.exists(HOTKEY_LOG):
                    with open(HOTKEY_LOG, "r", encoding="utf-8") as f:
                        txt.insert(tk.END, f.read())
                else:
                    txt.insert(tk.END, "(日志文件尚不存在，还没产生过错误或运行记录。)\n")
            except Exception as e:
                txt.insert(tk.END, f"读取日志失败: {e}\n")
            txt.see(tk.END)
            txt.config(state=tk.DISABLED)

        _load()

        # 底部按钮区
        bar = tk.Frame(lw, bg=BG)
        bar.pack(fill=tk.X, padx=10, pady=6)

        def _clear_log():
            try:
                if os.path.exists(HOTKEY_LOG):
                    os.remove(HOTKEY_LOG)
                _load()
            except Exception as e:
                pass

        def _open_folder():
            import subprocess
            try:
                subprocess.Popen(['explorer', '/select,', HOTKEY_LOG])
            except Exception:
                pass

        tk.Button(bar, text="刷新", bg=PANEL, fg=TEXT,
                  font=("微软雅黑", 9), bd=0, padx=10, pady=4,
                  cursor="hand2", command=_load).pack(side=tk.LEFT, padx=4)
        tk.Button(bar, text="清空", bg=PANEL, fg=TEXT,
                  font=("微软雅黑", 9), bd=0, padx=10, pady=4,
                  cursor="hand2", command=_clear_log).pack(side=tk.LEFT, padx=4)
        tk.Button(bar, text="打开所在文件夹", bg=PANEL, fg=TEXT,
                  font=("微软雅黑", 9), bd=0, padx=10, pady=4,
                  cursor="hand2", command=_open_folder).pack(side=tk.LEFT, padx=4)

        tk.Button(bar, text="关闭", bg=PANEL, fg=SUBTEXT,
                  font=("微软雅黑", 9), bd=0, padx=10, pady=4,
                  cursor="hand2", command=lw.destroy).pack(side=tk.RIGHT, padx=4)

    # ── 截图入口 ─────────────────────────────
    def _cap(self, mode: str):
        # 截图提取文字/翻译时不再隐藏工具条
        # self.withdraw()
        _hklog(f"[触发] mode={mode!r}  来源=快捷键或按钮")
        cb_map = {
            "ocr":        self._run_ocr_only,
            "translate":  self._run_ocr_translate,
            "screenshot": self._run_screenshot,
            "qrcode":     self._run_qrcode,
            "gen_qr":     self._run_gen_qrcode,
        }
        name_map = {
            "ocr":        "提取文字",
            "translate":  "截图翻译",
            "screenshot": "系统截图",
            "qrcode":     "识别二维码",
            "gen_qr":     "生成二维码",
        }
        action = cb_map.get(mode, self._run_ocr_only)
        m_name = name_map.get(mode, "")

        if mode == "gen_qr":
            self.after(0, action)
        else:
            self.after(200, lambda: grab_region(self, action, mode_name=m_name))

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
                # 使用 raw 返回来保留左、右、上、下的真实坐标点阵
                res = do_ocr_raw(img_path)
                
                # 网络出错或者未能正常提取结果的分支
                if isinstance(res, str):
                    self.after(0, lambda: popup.set_ocr(res))
                    self.after(0, lambda: popup.set_trans(f"识别或翻译中断。原因：{res}"))
                    return
                
                # 处理所有的提取原文并使用换行符重组
                lines = [item["text"] for item in res if item["text"].strip()]
                if not lines:
                    self.after(0, lambda: popup.set_ocr("未识别到文字（空）"))
                    self.after(0, lambda: popup.set_trans("（无需翻译）"))
                    return
                    
                full_text = "\n".join(lines)
                self.after(0, lambda: popup.set_ocr(full_text))
                
                # 调用你已有的翻译接口，翻译这个带 \n 换行的长文本
                translated = do_translate(full_text, target_lang=lang, engine=engine)
                # 交给支持智能按坐标摆放的新 set_trans
                self.after(0, lambda: popup.set_trans(translated, items=res))
                
            threading.Thread(target=worker, daemon=True).start()
        self.after(0, _main)

    # ── 扫码（微信 OpenCV QR） ────────────────
    def _run_qrcode(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300):
        def _main():
            def worker():
                try:
                    import cv2
                    import numpy as np
                except ImportError:
                    self.after(0, lambda: self._toast("缺少扫码引擎库。尝试在后台安装 opencv..."))
                    return
                try:
                    detector = cv2.wechat_qrcode_WeChatQRCode()
                    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if img is None:
                        self.after(0, lambda: self._toast("读取截图失败"))
                        return
                    res, points = detector.detectAndDecode(img)
                    if res:
                        # 获取所有结果拼接
                        text = "\n".join(res)
                        pyperclip.copy(text)
                        
                        # 兼容多行通知的显示情况
                        display_text = text if len(text) < 40 else text[:40] + "..."
                        self.after(0, lambda: self._toast(f"✅ 已复制二维码内容:\n{display_text}", ms=3500))
                    else:
                        self.after(0, lambda: self._toast("未能从选区识别到二维码"))
                except Exception as ex:
                    self.after(0, lambda: self._toast(f"扫码异常: {ex}"))
            threading.Thread(target=worker, daemon=True).start()
        self.after(0, _main)
        
    # ── 生成二维码 ───────────────────────────
    def _run_gen_qrcode(self):
        try:
            content = pyperclip.paste().strip()
            if not content:
                content = "请输入要生成二维码的内容"
        except Exception:
            content = "请输入要生成二维码的内容"
            
        try:
            import qrcode
        except ImportError:
            self.after(0, lambda: self._toast("你的电脑上没安装此功能所需的模块。\n不用担心，下次重启程序将自动恢复。"))
            return
            
        w = Toplevel(self)
        w.title("生成二维码")
        w.configure(bg="#1e1e2e")
        w.attributes("-topmost", True)
        w.geometry(f"320x420+{self.winfo_x()}+{self.winfo_y() + self.winfo_height() + 10}")

        img_lbl = tk.Label(w, bg="#1e1e2e")
        img_lbl.pack(pady=20)
        
        entry = tk.Entry(w, bg="#11111b", fg="#cdd6f4", insertbackground="#cdd6f4", 
                         font=("微软雅黑", 10), relief=tk.FLAT, justify="center")
        entry.pack(fill=tk.X, padx=20, pady=10, ipady=4)
        entry.insert(0, content)
        
        def _on_focus_in(event):
            if entry.get() == "请输入要生成二维码的内容":
                entry.delete(0, tk.END)
                
        entry.bind("<FocusIn>", _on_focus_in)
        
        btn_frame = tk.Frame(w, bg="#1e1e2e")
        btn_frame.pack(fill=tk.X, padx=20, pady=10)
        
        from PIL import ImageTk
        
        def _update_qr(*_):
            text = entry.get().strip() or "empty"
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            # 保存到临时文件
            img_path = os.path.join(_WRITE_DIR, "_temp_qr.png")
            img.save(img_path)
            
            photo = ImageTk.PhotoImage(img)
            img_lbl.config(image=photo)
            img_lbl.image = photo 
            img_lbl.qr_path = img_path
            
        def _copy_img():
            import subprocess
            path = getattr(img_lbl, 'qr_path', '')
            if not path or not os.path.exists(path): return
            try:
                ps = (f'Add-Type -AssemblyName System.Windows.Forms,System.Drawing;'
                      f'[System.Windows.Forms.Clipboard]::SetImage('
                      f'[System.Drawing.Image]::FromFile("{path}"))')
                subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=6)
                self._toast("✅ 二维码图片已复制到剪贴板")
            except Exception as e:
                self._toast(f"复制失败: {e}")
                
        def _save_img():
            from tkinter import filedialog
            path = getattr(img_lbl, 'qr_path', '')
            if not path or not os.path.exists(path): return
            tgt = filedialog.asksaveasfilename(defaultextension=".png", 
                                             initialfile="qrcode.png",
                                             filetypes=[("PNG图片", "*.png")])
            if tgt:
                import shutil
                shutil.copy2(path, tgt)
                self._toast("✅ 二维码已保存")

        _update_qr()
        entry.bind("<KeyRelease>", _update_qr)
        
        tk.Button(btn_frame, text="复制图片", bg="#f5a623", fg="#1a1a1a", 
                  font=("微软雅黑", 9, "bold"), bd=0, cursor="hand2", padx=10, pady=5, 
                  command=_copy_img).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        tk.Button(btn_frame, text="另存为...", bg="#313244", fg="#cdd6f4", 
                  font=("微软雅黑", 9), bd=0, cursor="hand2", padx=10, pady=5, 
                  command=_save_img).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))

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
        try: getattr(self, '_hotkey_mgr', None) and self._hotkey_mgr.stop()
        except Exception: pass
        super().destroy()


# ─────────────────────────────────────────────
if __name__ == "__main__":
    import ctypes
    from tkinter import messagebox
    
    # 互斥体名称，确保唯一
    mutex_name = "WeChatOCR_Tool_Instance_Mutex"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    last_error = ctypes.windll.kernel32.GetLastError()
    
    if last_error == 183: # ERROR_ALREADY_EXISTS
        # 创建一个临时隐藏的根窗口来弹窗
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showwarning("提示", "WeChat OCR 截图工具已经在运行中了！\\n请检查系统右下角托盘图标，切勿重复打开。")
        root.destroy()
        sys.exit(0)
        
    _hklog("=" * 60, with_kbd_state=False)
    _hklog(f">>> 程序启动  PID={os.getpid()}  Python={sys.version.split()[0]}")
    _hklog(f"    HOTKEY_LOG={HOTKEY_LOG}", with_kbd_state=False)

    app = CompactBar()
    app.mainloop()

# EOF

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
from tkinter import Toplevel, Canvas, StringVar, OptionMenu, font as tkfont
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageGrab
from translation_layout import layout_translation_block, layout_translation_lines
from ocr_postprocess import postprocess_ocr_items
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
TEMP_OCR_IMG   = os.path.join(_WRITE_DIR, "_temp_screenshot_ocr.png")

HOTKEY_LOG = os.path.join(_WRITE_DIR, "hotkey_debug.log")


def _resolve_icon_path(*names: str) -> str:
    for name in names:
        if not name:
            continue
        candidate = os.path.join(_RES_DIR, name)
        if os.path.exists(candidate):
            return candidate
        local_candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        if os.path.exists(local_candidate):
            return local_candidate
    return os.path.join(_RES_DIR, names[0]) if names else ""

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


def _get_virtual_screen_bounds(widget=None):
    try:
        u32 = ctypes.windll.user32
        left = int(u32.GetSystemMetrics(76))
        top = int(u32.GetSystemMetrics(77))
        width = int(u32.GetSystemMetrics(78))
        height = int(u32.GetSystemMetrics(79))
        if width > 0 and height > 0:
            return left, top, width, height
    except Exception:
        pass

    if widget is not None:
        try:
            return 0, 0, int(widget.winfo_screenwidth()), int(widget.winfo_screenheight())
        except Exception:
            pass
    return 0, 0, 1920, 1080


def _clamp_rect_to_bounds(x: int, y: int, width: int, height: int, bounds):
    left, top, bound_w, bound_h = bounds
    max_x = left + max(0, bound_w - width)
    max_y = top + max(0, bound_h - height)
    return max(left, min(int(x), max_x)), max(top, min(int(y), max_y))


def _edge_average_color(pil_img):
    img = pil_img.convert("RGB")
    w, h = img.size
    if w <= 0 or h <= 0:
        return (255, 255, 255)

    band_x = max(1, min(3, w // 6 or 1))
    band_y = max(1, min(3, h // 6 or 1))
    strips = [
        img.crop((0, 0, w, band_y)),
        img.crop((0, max(0, h - band_y), w, h)),
        img.crop((0, 0, band_x, h)),
        img.crop((max(0, w - band_x), 0, w, h)),
    ]
    pixels = []
    for strip in strips:
        pixels.extend(strip.getdata())
    if not pixels:
        return (255, 255, 255)
    return tuple(sum(pixel[idx] for pixel in pixels) // len(pixels) for idx in range(3))


def _prepare_ocr_input(image_path: str, crop_img=None):
    try:
        img = crop_img.copy() if crop_img is not None else Image.open(image_path)
        img = img.convert("RGB")
        w, h = img.size
        if w <= 0 or h <= 0:
            return image_path, 0, 0

        base = min(w, h)
        pad = max(4, min(12, int(round(base * 0.18))))
        pad_x = max(6, pad)
        pad_y = max(4, pad)

        padded = Image.new("RGB", (w + pad_x * 2, h + pad_y * 2), _edge_average_color(img))
        padded.paste(img, (pad_x, pad_y))
        padded.save(TEMP_OCR_IMG)
        return TEMP_OCR_IMG, pad_x, pad_y
    except Exception:
        return image_path, 0, 0
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
    processed = postprocess_ocr_items(res)
    return processed.text if processed.text else "（未识别到文字）"


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
#  智能窗口检测 (Win32 EnumWindows)
# ─────────────────────────────────────────────
def _enum_visible_windows():
    """枚举所有可见窗口矩形，按 Z-order（前→后）排序。
    返回 [(x1, y1, x2, y2), ...] 屏幕坐标。"""
    user32 = ctypes.windll.user32
    rects = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):
            return True
        # 跳过桌面窗口
        cls_buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls_buf, 64)
        if cls_buf.value in ("Progman", "WorkerW"):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w < 50 or h < 30:
            return True
        rects.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumWindows(_cb, 0)
    return rects

# ─────────────────────────────────────────────
#  截图选区（微信风格：截图背景 + 框选区域亮显 + 智能窗口检测）
# ─────────────────────────────────────────────
def grab_region(app, callback, mode_name=""):
    """在主线程中打开截图遮罩，完成后调用 callback(image_path, lx1,ly1,lx2,ly2, crop_img)
    策略：立即弹出旧式 alpha 遮罩（不阻塞主线程），后台截全屏并升级为 PIL 合成图。
    """
    from PIL import ImageTk

    def _open():
        # ── 获取虚拟屏幕范围 ──────────────────────
        try:
            u32 = ctypes.windll.user32
            vx  = u32.GetSystemMetrics(76)
            vy  = u32.GetSystemMetrics(77)
            vw  = u32.GetSystemMetrics(78)
            vh  = u32.GetSystemMetrics(79)
        except Exception:
            vx, vy = 0, 0
            vw = app.winfo_screenwidth()
            vh = app.winfo_screenheight()

        dpi_sx, dpi_sy = app._dpi_scale

        # ── 枚举可见窗口（遮罩创建前，避免把遮罩自身列入）──
        _pre_win_rects = _enum_visible_windows()

        # ── 1. 立即弹出旧式半透明遮罩（不阻塞主线程）──
        overlay = Toplevel(app)
        overlay.overrideredirect(True)
        overlay.geometry(f"{vw}x{vh}+{vx}+{vy}")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.25)   # 和旧版完全一样，立即可见
        overlay.configure(bg="black")
        overlay.lift()
        overlay.focus_force()

        canvas = Canvas(overlay, cursor="cross", bg="black",
                        highlightthickness=0, width=vw, height=vh)
        canvas.pack(fill=tk.BOTH, expand=True)

        # _ref 在后台线程和主线程之间共享数据
        _ref = {
            "photo":       None,    # 当前 canvas PhotoImage（防 GC）
            "pending":     False,   # 是否有待处理的重绘
            "full_img":    None,    # 原始物理像素截图
            "full_canvas": None,    # 逻辑像素缩放版
            "dim_base":    None,    # 预合成暗色底图
            "ready":       False,   # PIL 素材是否就绪
            "windows":     _pre_win_rects,  # 窗口矩形列表
            "hover_rect":  None,    # 当前悬停的窗口矩形
            "dragging":    False,   # 是否正在拖拽选区
            "hover_pending": False, # 悬停重绘节流
        }

        def _update_canvas(pil_img):
            """主线程：把 PIL Image 渲染到 canvas 背景"""
            photo = ImageTk.PhotoImage(pil_img)
            canvas.delete("bg")
            canvas.create_image(0, 0, anchor="nw", image=photo, tags="bg")
            canvas.tag_lower("bg")
            _ref["photo"] = photo

        def _init_bg():
            """后台线程：截全屏 → 准备合成底图（不阻塞 UI）"""
            try:
                sc_bbox = (
                    int(vx * dpi_sx), int(vy * dpi_sy),
                    int((vx + vw) * dpi_sx), int((vy + vh) * dpi_sy),
                )
                full_img    = ImageGrab.grab(bbox=sc_bbox, all_screens=True)
                full_canvas = full_img.resize((vw, vh), Image.LANCZOS)
                dark_overlay = Image.new("RGB", (vw, vh), (0, 0, 0))
                dim_base    = Image.blend(full_canvas, dark_overlay, 0.40)
                _ref["full_img"]    = full_img
                _ref["full_canvas"] = full_canvas
                _ref["dim_base"]    = dim_base
                _ref["ready"]       = True
                # 切换到 PIL 合成模式（去掉窗口 alpha，改用图像控制亮度）
                overlay.after(0, _activate_composite)
            except Exception:
                pass   # 保持旧式 alpha 模式即可

        def _activate_composite():
            """主线程：PIL 就绪后，切换到合成图模式"""
            try:
                overlay.attributes("-alpha", 1.0)   # 不再用窗口 alpha
                _update_canvas(_ref["dim_base"])
            except Exception:
                pass

        threading.Thread(target=_init_bg, daemon=True).start()

        state = {"sx": 0, "sy": 0}

        def on_press(e):
            state["sx"], state["sy"] = e.x_root, e.y_root
            _ref["dragging"] = True
            canvas.delete("hint")
            canvas.delete("hover_border")

        def _redraw(cx1, cy1, cx2, cy2):
            """主线程：选区亮显（仅 PIL 就绪后才合成）"""
            if _ref["ready"] and _ref["full_canvas"] and _ref["dim_base"]:
                composite = _ref["dim_base"].copy()
                bx1, by1 = max(0, int(cx1)), max(0, int(cy1))
                bx2, by2 = min(vw, int(cx2)), min(vh, int(cy2))
                if bx2 > bx1 and by2 > by1:
                    patch = _ref["full_canvas"].crop((bx1, by1, bx2, by2))
                    composite.paste(patch, (bx1, by1))
                _update_canvas(composite)
            # 绿色选框
            canvas.delete("sel_rect")
            canvas.create_rectangle(
                int(cx1), int(cy1), int(cx2), int(cy2),
                outline="#4a90d9", width=1, tags="sel_rect"
            )
            canvas.tag_raise("sel_rect")
            _ref["pending"] = False

        def _redraw_hover(cx1, cy1, cx2, cy2):
            """高亮悬停的窗口区域（PIL 合成）"""
            if not _ref["ready"] or _ref["dragging"]:
                _ref["hover_pending"] = False
                return
            composite = _ref["dim_base"].copy()
            bx1, by1 = max(0, int(cx1)), max(0, int(cy1))
            bx2, by2 = min(vw, int(cx2)), min(vh, int(cy2))
            if bx2 > bx1 and by2 > by1:
                patch = _ref["full_canvas"].crop((bx1, by1, bx2, by2))
                composite.paste(patch, (bx1, by1))
            _update_canvas(composite)
            canvas.delete("hover_border")
            canvas.create_rectangle(
                int(cx1), int(cy1), int(cx2), int(cy2),
                outline="#4a90d9", width=1, tags="hover_border"
            )
            canvas.tag_raise("hover_border")
            _ref["hover_pending"] = False

        def on_move(e):
            """鼠标悬停时自动检测并高亮窗口"""
            if _ref["dragging"] or not _ref["ready"] or _ref["hover_pending"]:
                return
            mx, my = e.x_root, e.y_root
            hit = None
            for wrect in _ref["windows"]:
                wx1, wy1, wx2, wy2 = wrect
                if wx1 <= mx <= wx2 and wy1 <= my <= wy2:
                    hit = wrect
                    break
            if hit == _ref["hover_rect"]:
                return  # 同一个窗口，不重绘
            _ref["hover_rect"] = hit
            if hit:
                _ref["hover_pending"] = True
                cx1, cy1 = hit[0] - vx, hit[1] - vy
                cx2, cy2 = hit[2] - vx, hit[3] - vy
                overlay.after(16, lambda a=cx1, b=cy1, c=cx2, d=cy2: _redraw_hover(a, b, c, d))
            else:
                _update_canvas(_ref["dim_base"])
                canvas.delete("hover_border")

        def on_drag(e):
            if _ref["pending"]:
                return
            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x_root, e.y_root
            cx1 = min(x1, x2) - vx
            cy1 = min(y1, y2) - vy
            cx2 = max(x1, x2) - vx
            cy2 = max(y1, y2) - vy
            if cx2 - cx1 < 3 or cy2 - cy1 < 3:
                return
            _ref["pending"] = True
            overlay.after(20, lambda a=cx1,b=cy1,c=cx2,d=cy2: _redraw(a, b, c, d))

        def on_release(e):
            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x_root, e.y_root

            # 单击（几乎没有拖拽）且有悬停窗口 → 直接选择该窗口
            if abs(x2 - x1) < 5 and abs(y2 - y1) < 5 and _ref["hover_rect"]:
                x1, y1, x2, y2 = _ref["hover_rect"]

            lx1, ly1 = int(min(x1, x2)), int(min(y1, y2))
            lx2, ly2 = int(max(x1, x2)), int(max(y1, y2))

            if abs(lx2 - lx1) < 5 or abs(ly2 - ly1) < 5:
                overlay.destroy()
                app.after(0, lambda: app.status("框选区域太小，已取消"))
                return

            # ── 翻译模式：保留遮罩（无缝过渡），其他模式：立即销毁 ──
            if getattr(app, '_keep_overlay', False):
                # 保持 OCR/翻译严格使用用户实际框选区域，避免相邻行被误带入
                # 冻结遮罩：禁用所有交互事件，保留视觉效果
                for evt in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>",
                            "<Motion>", "<ButtonPress-3>", "<ButtonRelease-3>"):
                    canvas.unbind(evt)
                overlay.unbind("<ButtonPress-3>")
                overlay.unbind("<ButtonRelease-3>")
                overlay.unbind("<Escape>")
                app._pending_overlay = overlay
                app._keep_overlay = False
            else:
                overlay.destroy()

            def _do_grab():
                full_img = _ref.get("full_img")
                if full_img:
                    fx1 = max(0, min(int((lx1 - vx) * dpi_sx), full_img.width))
                    fy1 = max(0, min(int((ly1 - vy) * dpi_sy), full_img.height))
                    fx2 = max(0, min(int((lx2 - vx) * dpi_sx), full_img.width))
                    fy2 = max(0, min(int((ly2 - vy) * dpi_sy), full_img.height))
                    crop_img = full_img.crop((fx1, fy1, fx2, fy2))
                    crop_img.save(TEMP_IMG)
                else:
                    import time
                    time.sleep(0.15)
                    bbox = (int(lx1*dpi_sx), int(ly1*dpi_sy),
                            int(lx2*dpi_sx), int(ly2*dpi_sy))
                    crop_img = ImageGrab.grab(bbox=bbox, all_screens=True)
                    crop_img.save(TEMP_IMG)
                app.after(0, lambda: callback(TEMP_IMG, lx1, ly1, lx2, ly2, crop_img))

            threading.Thread(target=_do_grab, daemon=True).start()

        def _cancel(e=None):
            overlay.destroy()
            app._keep_overlay = False
            app._pending_overlay = None
            app._capturing = False   # 释放单例锁
            app.status("已取消截图")
            return "break"

        def _rclick_press(e):   return "break"
        def _rclick_release(e): return _cancel()

        canvas.bind("<ButtonPress-1>",   on_press)
        canvas.bind("<B1-Motion>",       on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        canvas.bind("<Motion>",          on_move)
        canvas.bind("<ButtonPress-3>",   _rclick_press)
        canvas.bind("<ButtonRelease-3>", _rclick_release)
        overlay.bind("<ButtonPress-3>",  _rclick_press)
        overlay.bind("<ButtonRelease-3>",_rclick_release)
        overlay.bind("<Escape>", _cancel)

    app.after(0, _open)




# ─────────────────────────────────────────────
#  原位覆盖结果层（微信同款增强版：沉浸式翻译）
# ─────────────────────────────────────────────
class InPlaceOverlay(Toplevel):
    """
    微信原生截图翻译效果（增强版）：
    - LANCZOS 高清渲染
    - 高斯模糊 In-painting 背景擦除
    - 自适应字号/宽度/颜色匹配
    - 悬停高亮 + 原文对比交互
    """

    def __init__(self, parent, lx1: int, ly1: int, lx2: int, ly2: int,
                 mode: str, bg_img=None, dpi_scale=(1.0, 1.0)):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="black",
                       highlightthickness=1,
                       highlightbackground="#4a90d9")
        self._mode      = mode
        self._ocr_txt   = ""
        self._tr_txt    = ""
        self._last_items     = None
        self._showing_original = False
        self._toggle_btn     = None
        self._parent    = parent
        self._toolbar   = None
        self._dim_bg    = None
        self._text_ids  = []
        self._hover_ids = []
        self._trans_rects = []
        self._bg_img    = bg_img
        self._erased_img = None
        self._dpi_scale = dpi_scale
        self._photo_ref = None
        self._font_cache = {}

        self._screen_bounds = _get_virtual_screen_bounds(parent)
        w  = max(lx2 - lx1, 200)
        h  = max(ly2 - ly1, 40)
        self._px, self._py = _clamp_rect_to_bounds(lx1, ly1, w, h, self._screen_bounds)
        self._win_w, self._win_h = w, h
        self._base_win_w, self._base_win_h = w, h
        self.geometry(f"{w}x{h}+{self._px}+{self._py}")

        self._canvas = Canvas(self, bg="black", highlightthickness=0,
                              width=w, height=h)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        if bg_img:
            self._render_bg(bg_img, w, h)
            if mode == "translate":
                self._canvas.create_text(
                    w // 2, h // 2, text="翻译中\u2026",
                    fill="#ffffff", font=("微软雅黑", 13), tags="loading"
                )
        else:
            self._canvas.configure(bg="white")
            self._canvas.create_text(
                w // 2, h // 2,
                text="翻译中\u2026" if mode == "translate" else "识别中\u2026",
                fill="#111111", font=("微软雅黑", 11), tags="loading"
            )

        self._fallback_var = tk.StringVar(value="")
        self._fallback_lbl = tk.Label(
            self, textvariable=self._fallback_var,
            bg="white", fg="#111111",
            font=("微软雅黑", 11), wraplength=w - 16,
            justify=tk.LEFT, anchor="nw", padx=8, pady=6
        )

        self._canvas.bind("<Motion>", self._on_hover)
        self._canvas.bind("<Leave>",  self._on_leave)

        self._build_toolbar(self._screen_bounds[3])
        self.focus_force()

    def _render_bg(self, pil_img, w, h):
        from PIL import ImageTk
        try:
            base_h = min(h, self._base_win_h)
            display = pil_img.resize((w, base_h), Image.LANCZOS)
            if h > base_h:
                pad_color = self._background_pad_color(display)
                padded = Image.new("RGB", (w, h), pad_color)
                padded.paste(display, (0, 0))
                display = padded
            photo = ImageTk.PhotoImage(display)
            self._canvas.delete("bg_img")
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags="bg_img")
            self._canvas.tag_lower("bg_img")
            self._photo_ref = photo
        except Exception:
            pass

    def _background_pad_color(self, img):
        try:
            sample_h = min(4, img.height)
            if sample_h <= 0:
                return (245, 245, 245)
            sample = img.crop((0, img.height - sample_h, img.width, img.height)).convert("RGB")
            pixels = list(sample.getdata())
            if not pixels:
                return (245, 245, 245)
            return tuple(sum(pixel[idx] for pixel in pixels) // len(pixels) for idx in range(3))
        except Exception:
            return (245, 245, 245)

    def _position_toolbar(self):
        if not self._toolbar:
            return
        left, top, screen_w, screen_h = self._screen_bounds
        dpi_sx, dpi_sy = self._dpi_scale
        toolbar_w, toolbar_h = int(280 * dpi_sx), int(36 * dpi_sy)
        tx = self._px + (self._win_w - toolbar_w) // 2
        ty = self._py + self._win_h + 4
        if ty + toolbar_h > top + screen_h - 10:
            ty = self._py - toolbar_h - 4
        tx, ty = _clamp_rect_to_bounds(tx, ty, toolbar_w, toolbar_h, self._screen_bounds)
        self._toolbar.geometry(f"{toolbar_w}x{toolbar_h}+{tx}+{ty}")

    def _max_overlay_height(self):
        return max(self._base_win_h, self._screen_bounds[3] - 20)

    def _resize_overlay(self, new_height: int):
        target_h = max(self._base_win_h, min(int(new_height), self._max_overlay_height()))
        if target_h == self._win_h:
            return
        self._win_h = target_h
        self._px, self._py = _clamp_rect_to_bounds(
            self._px, self._py, self._win_w, self._win_h, self._screen_bounds
        )
        self.geometry(f"{self._win_w}x{self._win_h}+{self._px}+{self._py}")
        self._canvas.configure(width=self._win_w, height=self._win_h)
        self._position_toolbar()

    def _erase_text_regions(self, pil_img, items):
        """背景擦除：采样边缘像素平均色填充，消除原文像素"""
        from PIL import ImageDraw
        img  = pil_img.copy().convert("RGB")
        draw = ImageDraw.Draw(img)
        iw, ih = img.size
        B = 3
        for item in items:
            x1 = max(0, int(item.get("left",  0)))
            y1 = max(0, int(item.get("top",   0)))
            x2 = min(iw, int(item.get("right", 0)))
            y2 = min(ih, int(item.get("bottom", 0)))
            if x2 <= x1 or y2 <= y1:
                continue
            # 采样四条边外侧像素
            pixels = []
            for strip in [
                img.crop((max(0,x1-B), max(0,y1-B), min(iw,x2+B), max(1,y1))),
                img.crop((max(0,x1-B), min(ih-1,y2), min(iw,x2+B), min(ih,y2+B))),
                img.crop((max(0,x1-B), y1, max(1,x1), y2)),
                img.crop((min(iw-1,x2), y1, min(iw,x2+B), y2)),
            ]:
                if strip.size[0] > 0 and strip.size[1] > 0:
                    pixels.extend(list(strip.getdata()))
            if pixels:
                # 使用每条通道的中位数值，而不是均值
                # 极大避免被占比很小的底色、细线、下划线污染背景色
                rs = sorted([p[0] for p in pixels])
                gs = sorted([p[1] for p in pixels])
                bs = sorted([p[2] for p in pixels])
                mid = len(pixels) // 2
                avg = (rs[mid], gs[mid], bs[mid])
            else:
                avg = (240, 240, 240)
            # 扩展实心填充边界，更好地完全覆盖被抗锯齿或者连笔溢出的原文
            draw.rectangle(
                [max(0, x1 - 3), max(0, y1 - 3),
                 min(iw, x2 + 3), min(ih, y2 + 4)],
                fill=avg
            )
        return img

    def _sample_text_color(self, x1, y1, x2, y2):
        """根据原图对应位置智能采样文字颜色，确保对比度"""
        bg = self._erased_img or self._bg_img
        if not bg:
            return "#ffffff"
        try:
            iw, ih = bg.size
            rx1, ry1 = max(0, x1), max(0, y1)
            rx2, ry2 = min(iw, x2), min(ih, y2)
            if rx2 <= rx1 or ry2 <= ry1:
                return "#ffffff"
            region = bg.crop((rx1, ry1, rx2, ry2)).convert("RGB")
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
        tb.configure(bg="#f7f7f7",
                     highlightthickness=1,
                     highlightbackground="#d0d0d0")
        self._toolbar = tb
        self._position_toolbar()
        bar = tk.Frame(tb, bg="#f7f7f7")
        bar.pack(fill=tk.BOTH, expand=True, padx=6, pady=2)
        self._tbtn(bar, "\U0001f4cb \u590d\u5236", self._do_copy).pack(side=tk.LEFT, padx=4)
        if self._mode == "translate":
            btn = self._tbtn(bar, "\u539f\u6587", self._toggle_view)
            btn.pack(side=tk.LEFT, padx=4)
            self._toggle_btn = btn
        self._tbtn(bar, " \xd7 ", self._close_all,
                   fg="#e04040", bg="#f0e0e0").pack(side=tk.RIGHT, padx=6)
        self._tbtn(bar, " \u2713 ", self._do_copy_screenshot,
                   fg="#40a040", bg="#e0f0e0").pack(side=tk.RIGHT, padx=6)
        self.bind("<Escape>", lambda e: self._close_all())
        tb.bind("<Escape>", lambda e: self._close_all())

    def _tbtn(self, parent, text, cmd, fg="#333333", bg="#eeeeee"):
        return tk.Button(parent, text=text, bg=bg, fg=fg,
                         font=("微软雅黑", 9), bd=0, relief=tk.FLAT,
                         padx=8, pady=2, cursor="hand2",
                         activebackground="#ddd", activeforeground=fg,
                         command=cmd)

    def _get_font(self, size: int):
        size = max(1, int(size))
        font = self._font_cache.get(size)
        if font is None:
            font = tkfont.Font(family="\u5fae\u8f6f\u96c5\u9ed1", size=size)
            self._font_cache[size] = font
        return font

    def _measure_text_width(self, text: str, font_size: int) -> int:
        return self._get_font(font_size).measure(text)

    def _measure_line_height(self, font_size: int) -> int:
        return self._get_font(font_size).metrics("linespace")

    def _draw_translation_layout(self, layout):
        for placement in layout.placements:
            px1, py1, px2, py2 = placement.source_box
            fg_color = self._sample_text_color(px1, py1, px2, py2)
            draw_y = placement.y if placement.anchor == "nw" else placement.y + placement.actual_height // 2
            draw_kwargs = {"width": placement.render_width} if placement.wrapped else {}
            tid = self._canvas.create_text(
                placement.x, draw_y,
                text=placement.text,
                fill=fg_color,
                font=("\u5fae\u8f6f\u96c5\u9ed1", placement.font_size),
                anchor=placement.anchor,
                tags="trans_text",
                **draw_kwargs,
            )
            self._text_ids.append(tid)
            self._trans_rects.append({
                "tid": tid,
                "cx1": placement.x,
                "cy1": placement.y,
                "cx2": placement.right,
                "cy2": placement.bottom,
                "orig": placement.original_text,
            })

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
        self._last_items = items
        self._showing_original = False
        if self._toggle_btn:
            self._toggle_btn.config(text="\u539f\u6587")
        if self._mode != "translate":
            return

        self._canvas.delete("loading")
        for tid in self._text_ids:
            self._canvas.delete(tid)
        self._text_ids.clear()
        self._trans_rects.clear()
        self._fallback_lbl.place_forget()

        w = self._win_w
        h = self._win_h
        translated_lines = [line.strip() for line in text.split("\n") if line.strip()]
        original_lines = [item for item in (items or []) if item.get("text", "").strip()]

        if not original_lines:
            if self._bg_img:
                self._render_bg(self._bg_img, w, h)
            self._fallback_var.set(text)
            self._fallback_lbl.configure(wraplength=w - 16)
            self._fallback_lbl.place(x=0, y=0, width=w)
            return

        if self._bg_img:
            erased = self._erase_text_regions(self._bg_img, original_lines)
            self._erased_img = erased
            self._render_bg(erased, w, h)

        if len(translated_lines) == len(original_lines):
            layout = layout_translation_lines(
                translated_lines=translated_lines,
                original_lines=original_lines,
                overlay_width=w,
                overlay_height=h,
                measure_width=self._measure_text_width,
                line_height=self._measure_line_height,
                dpi_scale=self._dpi_scale,
            )
        else:
            layout = layout_translation_block(
                text=text,
                original_lines=original_lines,
                overlay_width=w,
                overlay_height=h,
                measure_width=self._measure_text_width,
                line_height=self._measure_line_height,
                dpi_scale=self._dpi_scale,
            )

        if layout.required_height > h:
            prev_height = self._win_h
            self._resize_overlay(layout.required_height)
            if self._win_h != prev_height:
                self.set_trans(text, items)
                return

        self._draw_translation_layout(layout)

    def _do_copy_screenshot(self):
        """\u2713 按钮：截取当前翻译窗口内容为图片，复制到系统剪贴板后关闭"""
        try:
            import io
            self.update_idletasks()
            x = self.winfo_rootx()
            y = self.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            dpi_sx, dpi_sy = self._dpi_scale
            # 抓取窗口区域的屏幕像素
            grab_box = (int(x * dpi_sx), int(y * dpi_sy),
                        int((x + w) * dpi_sx), int((y + h) * dpi_sy))
            shot = ImageGrab.grab(bbox=grab_box, all_screens=True)
            
            # 写入 Windows 剪贴板 (BMP 格式)
            output = io.BytesIO()
            shot.convert("RGB").save(output, "BMP")
            bmp_data = output.getvalue()[14:]  # 去掉 BMP 文件头
            output.close()
            
            import ctypes
            CF_DIB = 8
            u32 = ctypes.windll.user32
            k32 = ctypes.windll.kernel32
            u32.OpenClipboard(0)
            u32.EmptyClipboard()
            h_mem = k32.GlobalAlloc(0x0042, len(bmp_data))
            p = k32.GlobalLock(h_mem)
            ctypes.memmove(p, bmp_data, len(bmp_data))
            k32.GlobalUnlock(h_mem)
            u32.SetClipboardData(CF_DIB, h_mem)
            u32.CloseClipboard()
            
            self._parent.after(0, lambda: self._parent.status("✓ 翻译截图已复制到剪贴板"))
        except Exception as ex:
            self._parent.after(0, lambda: self._parent.status(f"截图复制失败: {ex}"))
        self._close_all()

    # ── 悬停交互：已移除 ────────────
    def _on_hover(self, e):
        pass

    def _on_leave(self, e):
        for hid in self._hover_ids:
            self._canvas.delete(hid)
        self._hover_ids.clear()

    def _toggle_view(self):
        if self._showing_original:
            self._showing_original = False
            if self._toggle_btn:
                self._toggle_btn.config(text="原文")
            self._canvas.delete("ocr_text")
            for tid in self._text_ids:
                self._canvas.delete(tid)
            self._text_ids.clear()
            self._trans_rects.clear()
            self._fallback_lbl.place_forget()
            self.set_trans(self._tr_txt, self._last_items)
        else:
            self._showing_original = True
            if self._toggle_btn:
                self._toggle_btn.config(text="译文")
            self._show_ocr()

    def _show_ocr(self):
        for tid in self._text_ids:
            self._canvas.delete(tid)
        self._text_ids.clear()
        self._trans_rects.clear()
        for hid in self._hover_ids:
            self._canvas.delete(hid)
        self._hover_ids.clear()
        self._canvas.delete("loading")
        self._canvas.delete("ocr_text")
        self._fallback_lbl.place_forget()
        if self._bg_img:
            self._render_bg(self._bg_img, self._win_w, self._win_h)


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
        # 清理全屏暗色遮罩
        try:
            if getattr(self, '_dim_bg', None):
                self._dim_bg.destroy()
                self._dim_bg = None
        except Exception:
            pass

    def destroy(self):
        try:
            if getattr(self, "_toolbar", None):
                self._toolbar.destroy()
                self._toolbar = None
        except Exception:
            pass
        try:
            if getattr(self, "_dim_bg", None):
                self._dim_bg.destroy()
                self._dim_bg = None
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
                  'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28, 'enter': 0x0D, 'esc': 0x1B,
                  'num 0': 0x60, 'num 1': 0x61, 'num 2': 0x62, 'num 3': 0x63,
                  'num 4': 0x64, 'num 5': 0x65, 'num 6': 0x66, 'num 7': 0x67,
                  'num 8': 0x68, 'num 9': 0x69}
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
        cfg = _load_config()
        translation_cfg = cfg.get("translation", {})
        engine = translation_cfg.get("engine", ENGINES[0])
        if engine not in ENGINES:
            engine = ENGINES[0]
        lang = translation_cfg.get("lang", "zh")
        if lang not in {"zh", "en", "ja", "ko", "fr", "de", "es", "ru", "th", "vi"}:
            lang = "zh"
        self.engine_var = StringVar(self, value=engine)
        self.lang_var   = StringVar(self, value=lang)
        self._dpi_scale = self._calc_dpi()
        
        # 设置窗口图标
        ico_path = _resolve_icon_path("icon.ico", "wxocr.ico")
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
            _, _, lw, lh = _get_virtual_screen_bounds(self)
            im = ImageGrab.grab(all_screens=True)
            return im.width / max(lw, 1), im.height / max(lh, 1)
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

        # 按钮顺序：翻译 → 提取文字 → 截图 → 扫码 → 生成QR
        for label, mode in [
            ("译",       "translate"),
            ("提取文字", "ocr"),
            ("截  图",   "screenshot"),
            ("扫  码",   "qrcode"),
            ("生成QR",   "gen_qr"),
        ]:
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
        """创建工具栏按钮（简洁版，无快捷键提示）"""
        container = tk.Frame(self, bg=self.BAR_BG, cursor="hand2")
        container.pack(side=tk.LEFT)

        btn = tk.Button(
            container, text=text,
            bg=self.BAR_BG, fg=self.TXT_COL,
            font=("微软雅黑", 9), bd=0, relief=tk.FLAT,
            padx=8, pady=6, cursor="hand2",
            activebackground=self.HOV_BG,
            activeforeground=self.TXT_COL,
            command=cmd
        )
        btn.pack(side=tk.TOP)
        container.bind("<Button-1>", lambda e: cmd())


    # ── 热键 ─────────────────────────────────
    def _register_hotkeys(self):
        _hklog(">>> _register_hotkeys() 调用开始 (Win32 API)")
        try:
            cfg = _load_config().get("hotkeys", {})
            h1 = cfg.get("translate",  "alt+1")
            h2 = cfg.get("ocr",        "alt+2")
            h3 = cfg.get("screenshot", "alt+3")
            h4 = cfg.get("qrcode",    "alt+4")
            h5 = cfg.get("gen_qr",    "alt+5")
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
        
        ico_path = _resolve_icon_path("icon.ico", "wxocr.ico")
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
        d.resizable(True, True)
        d.attributes("-topmost", True)
        d.transient(self)
        screen_left, screen_top, screen_w, screen_h = _get_virtual_screen_bounds(self)
        dialog_w = min(max(420, int(screen_w * 0.32)), max(320, screen_w - 80))
        dialog_h = min(max(620, int(screen_h * 0.72)), max(420, screen_h - 80))
        parent_x = self.winfo_rootx()
        parent_y = self.winfo_rooty()
        parent_w = max(self.winfo_width(), 330)
        pos_x = parent_x + (parent_w - dialog_w) // 2
        pos_y = parent_y + 40
        pos_x, pos_y = _clamp_rect_to_bounds(pos_x, pos_y, dialog_w, dialog_h, (screen_left, screen_top, screen_w, screen_h))
        d.geometry(f"{dialog_w}x{dialog_h}+{pos_x}+{pos_y}")
        d.minsize(360, 420)
        
        def _clear_engine_trace():
            trace_id = getattr(self, "_settings_engine_trace", None)
            if trace_id:
                try:
                    self.engine_var.trace_remove("write", trace_id)
                except Exception:
                    pass
                self._settings_engine_trace = None

        def _on_close():
            _clear_engine_trace()
            self._hd_open = False
            d.destroy()
        d.protocol("WM_DELETE_WINDOW", _on_close)
        d.bind("<Escape>", lambda e: _on_close())
        d.lift()
        d.focus_force()

        body_wrap = tk.Frame(d, bg=BG)
        body_wrap.pack(fill=tk.BOTH, expand=True)

        body_canvas = tk.Canvas(body_wrap, bg=BG, highlightthickness=0, bd=0)
        body_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        body_scroll = tk.Scrollbar(body_wrap, orient=tk.VERTICAL, command=body_canvas.yview)
        body_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        body_canvas.configure(yscrollcommand=body_scroll.set)

        content = tk.Frame(body_canvas, bg=BG)
        content_window = body_canvas.create_window((0, 0), window=content, anchor="nw")

        def _sync_scroll_region(_event=None):
            body_canvas.configure(scrollregion=body_canvas.bbox("all"))

        def _sync_content_width(event):
            body_canvas.itemconfigure(content_window, width=event.width)

        def _on_mousewheel(event):
            if event.delta:
                body_canvas.yview_scroll(int(-event.delta / 120), "units")

        content.bind("<Configure>", _sync_scroll_region)
        body_canvas.bind("<Configure>", _sync_content_width)
        d.bind("<MouseWheel>", _on_mousewheel, add="+")

        tk.Label(content, text="⌨  快捷键", bg=BG, fg=ACCENT,
                 font=("微软雅黑", 11, "bold")).pack(pady=(16, 4))
        tk.Label(content, text="（点击输入框后直接按下快捷键即可）", bg=BG, fg=SUBTEXT,
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
                
                # 强制修复 Windows 下由于按住 Alt 导致的键位识别错乱 (比如变成 `??` 或被当成 ascii 自定义输入)
                if getattr(e, "keycode", 0):
                    if 96 <= e.keycode <= 105:
                        k = f"num {e.keycode - 96}"
                    elif 48 <= e.keycode <= 57:
                        k = str(e.keycode - 48)
                if k.startswith("mouse") or not k: return "break"
                
                km = {"prior": "page up", "next": "page down", "return": "enter", "escape": "esc", "kp_1": "num 1", "kp_2": "num 2", "kp_3": "num 3", "kp_4": "num 4", "kp_5": "num 5", "kp_6": "num 6", "kp_7": "num 7", "kp_8": "num 8", "kp_9": "num 9", "kp_0": "num 0"}
                k = km.get(k, k)
                hk = "+".join(mods + [k])
                entry.delete(0, tk.END)
                entry.insert(0, hk)
                return "break"
            entry.bind("<Key>", _on_key)

        row1 = tk.Frame(content, bg=BG)
        row1.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row1, text="截图翻译:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk1_entry = tk.Entry(row1, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk1_entry.pack(side=tk.RIGHT)
        hk1_entry.insert(0, cfg_hk.get("translate", "alt+1"))
        _bind_hk_recorder(hk1_entry)

        row2 = tk.Frame(content, bg=BG)
        row2.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row2, text="提取文字 (截图复制):", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk2_entry = tk.Entry(row2, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk2_entry.pack(side=tk.RIGHT)
        hk2_entry.insert(0, cfg_hk.get("ocr", "alt+2"))
        _bind_hk_recorder(hk2_entry)

        row3 = tk.Frame(content, bg=BG)
        row3.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row3, text="简单截图 (复制):", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk3_entry = tk.Entry(row3, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk3_entry.pack(side=tk.RIGHT)
        hk3_entry.insert(0, cfg_hk.get("screenshot", "alt+3"))
        _bind_hk_recorder(hk3_entry)

        row4 = tk.Frame(content, bg=BG)
        row4.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row4, text="识别二维码:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk4_entry = tk.Entry(row4, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk4_entry.pack(side=tk.RIGHT)
        hk4_entry.insert(0, cfg_hk.get("qrcode", "alt+4"))
        _bind_hk_recorder(hk4_entry)

        row5 = tk.Frame(content, bg=BG)
        row5.pack(fill=tk.X, padx=30, pady=3)
        tk.Label(row5, text="生成二维码:", bg=BG, fg=TEXT, font=("微软雅黑", 9)).pack(side=tk.LEFT)
        hk5_entry = tk.Entry(row5, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, font=("微软雅黑", 9), width=15)
        hk5_entry.pack(side=tk.RIGHT)
        hk5_entry.insert(0, cfg_hk.get("gen_qr", "alt+5"))
        _bind_hk_recorder(hk5_entry)

        tk.Frame(content, bg=BORDER, height=1).pack(fill=tk.X, padx=16, pady=6)
        tk.Label(content, text="🌐  翻译设置", bg=BG, fg=ACCENT,
                 font=("微软雅黑", 11, "bold")).pack()

        row2 = tk.Frame(content, bg=BG)
        row2.pack(fill=tk.X, padx=24, pady=6)
        tk.Label(row2, text="引擎:", bg=BG, fg=SUBTEXT,
                 font=("微软雅黑", 9), width=5, anchor="w").pack(side=tk.LEFT)
        OptionMenu(row2, self.engine_var, *ENGINES).pack(side=tk.LEFT, padx=4)
        tk.Label(row2, text="语言:", bg=BG, fg=SUBTEXT,
                 font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=(8, 0))
        OptionMenu(row2, self.lang_var,
                   "zh","en","ja","ko","fr","de","es","ru","th","vi").pack(side=tk.LEFT, padx=4)

        tc_frame = tk.Frame(content, bg=BG)
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

        _clear_engine_trace()
        self._settings_engine_trace = self.engine_var.trace_add("write", _update_tc_frame)
        _update_tc_frame() # initial call

        footer = tk.Frame(d, bg=BG)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(footer, bg=BORDER, height=1).pack(fill=tk.X, padx=12, pady=(0, 10))

        btn_frame = tk.Frame(footer, bg=BG)
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 12))

        tk.Button(btn_frame, text="保存并关闭", bg=ACCENT, fg=BTN_FG,
                  font=("微软雅黑", 10), bd=0, padx=16, pady=6,
                  cursor="hand2", command=lambda: save_and_close(d)).pack(side=tk.LEFT, padx=6)

        tk.Button(btn_frame, text="📋 查看诊断日志", bg="#2a2a3e", fg="#a6adc8",
                  font=("微软雅黑", 9), bd=0, padx=10, pady=6,
                  cursor="hand2", command=self._show_log_dialog).pack(side=tk.RIGHT)

        def save_and_close(window):
            new_cfg = _load_config()
            new_cfg["translation"] = {
                "engine": self.engine_var.get().strip() or ENGINES[0],
                "lang": self.lang_var.get().strip() or "zh",
            }
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
                
            _clear_engine_trace()
            self._hd_open = False
            window.destroy()

    # ── 诊断日志查看器 ────────────────────────
    def _show_log_dialog(self):
        """打开一个简单的日志查看窗口，显示 hotkey_debug.log 内容"""
        lw = Toplevel(self)
        lw.title(f"热键诊断日志  ({HOTKEY_LOG})")
        lw.configure(bg=BG)
        lw.attributes("-topmost", True)
        bounds = _get_virtual_screen_bounds(self)
        win_w, win_h = 780, 480
        pos_x = self.winfo_rootx() + 30
        pos_y = self.winfo_rooty() + 30
        pos_x, pos_y = _clamp_rect_to_bounds(pos_x, pos_y, win_w, win_h, bounds)
        lw.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")

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

    # ── 截图入口（全局单例：先关旧弹窗再开新的）────
    def _cap(self, mode: str):
        _hklog(f"[触发] mode={mode!r}  来源=快捷键或按钮")

        # ── 全局单例锁：选区遮罩打开期间忽略所有重复热键 ──
        if getattr(self, "_capturing", False) and mode != "gen_qr":
            _hklog(f"[忽略] 正在框选中，跳过 mode={mode!r}")
            return

        # 关闭上一次未关的结果弹窗
        old = getattr(self, "_active_popup", None)
        if old:
            try:
                old.destroy()
            except Exception:
                pass
            self._active_popup = None

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
        action  = cb_map.get(mode, self._run_ocr_only)
        m_name  = name_map.get(mode, "")

        if mode == "gen_qr":
            self.after(0, action)
        else:
            # 设置锁；用 wrapper 确保 callback 完成时释放锁（无论成功或 cancel）
            self._capturing = True
            self._keep_overlay = (mode == "translate")  # 翻译模式保留遮罩
            original_action = action
            def _action_done(*args, **kwargs):
                self._capturing = False
                original_action(*args, **kwargs)
            self.after(200, lambda: grab_region(self, _action_done, mode_name=m_name))


    # ── 提取文字（OCR 复制）────────────────
    def _run_ocr_only(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300, crop_img=None):
        def _main():
            def worker():
                ocr_img_path, _, _ = _prepare_ocr_input(img_path, crop_img)
                text = do_ocr(ocr_img_path)
                if text and not text.startswith("["):
                    pyperclip.copy(text)
                    self.after(0, lambda: self._toast(f"✅ 已复制 {len(text)} 字符"))
                else:
                    self.after(0, lambda: self._toast(f"识别失败"))
            threading.Thread(target=worker, daemon=True).start()
        self.after(0, _main)

    # ── 截图到剪贴板 ─────────────────────────
    def _run_screenshot(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300, crop_img=None):
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

    # ── OCR + 翻译 ───────────────────────
    def _run_ocr_translate(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300, crop_img=None):
        def _main():
            engine = self.engine_var.get()
            lang   = self.lang_var.get()

            # ── 微信翻译风格：复用截图遮罩实现无缝过渡 ──
            pending_ov = getattr(self, '_pending_overlay', None)
            self._pending_overlay = None

            if pending_ov:
                # 无缝过渡：直接复用截图遮罩（暗色背景 + 选区高亮已就绪）
                dim_bg = pending_ov
            else:
                # 回退：创建新的全屏遮罩
                try:
                    u32 = ctypes.windll.user32
                    _vx = u32.GetSystemMetrics(76)
                    _vy = u32.GetSystemMetrics(77)
                    _vw = u32.GetSystemMetrics(78)
                    _vh = u32.GetSystemMetrics(79)
                except Exception:
                    _vx, _vy = 0, 0
                    _vw = self.winfo_screenwidth()
                    _vh = self.winfo_screenheight()
                dim_bg = Toplevel(self)
                dim_bg.overrideredirect(True)
                dim_bg.attributes("-topmost", True)
                dim_bg.attributes("-alpha", 0.45)
                dim_bg.configure(bg="black")
                dim_bg.geometry(f"{_vw}x{_vh}+{_vx}+{_vy}")

            popup  = InPlaceOverlay(self, lx1, ly1, lx2, ly2, mode="translate",
                                    bg_img=crop_img, dpi_scale=self._dpi_scale)
            popup._dim_bg = dim_bg   # 传递遮罩引用，关闭时一起销毁
            self._active_popup = popup   # 登记当前弹窗

            # ── 防卡屏：遮罩层事件绑定 ──
            def _dismiss_dim(e=None):
                try: popup._close_all()
                except Exception: pass

            # 点击遮罩空白区域 / 按 ESC / 右键 → 关闭翻译（微信同款行为）
            dim_bg.bind("<Button-1>",  _dismiss_dim)
            dim_bg.bind("<Button-3>",  _dismiss_dim)
            dim_bg.bind("<Escape>",    _dismiss_dim)

            # 遮罩意外获得焦点时，自动将弹窗和工具栏提升到最前
            def _relift(e=None):
                try:
                    popup.lift()
                    if popup._toolbar:
                        popup._toolbar.lift()
                    popup.focus_force()
                except Exception:
                    pass
            dim_bg.bind("<FocusIn>", _relift)

            # 确保弹窗在遮罩上方
            popup.lift()
            if popup._toolbar:
                popup._toolbar.lift()
            popup.focus_force()

            def worker():
                # 使用 raw 返回来保留左、右、上、下的真实坐标点阵
                ocr_img_path, pad_x, pad_y = _prepare_ocr_input(img_path, crop_img)
                res = do_ocr_raw(ocr_img_path)
                
                # 网络出错或者未能正常提取结果的分支
                if isinstance(res, str):
                    self.after(0, lambda: popup.set_ocr(res))
                    self.after(0, lambda: popup.set_trans(f"识别或翻译中断。原因：{res}"))
                    return

                if pad_x or pad_y:
                    max_right = crop_img.width if crop_img is not None else None
                    max_bottom = crop_img.height if crop_img is not None else None
                    adjusted = []
                    for item in res:
                        adjusted_item = dict(item)
                        adjusted_item["left"] = max(0, int(item.get("left", 0)) - pad_x)
                        adjusted_item["top"] = max(0, int(item.get("top", 0)) - pad_y)
                        adjusted_item["right"] = max(adjusted_item["left"], int(item.get("right", 0)) - pad_x)
                        adjusted_item["bottom"] = max(adjusted_item["top"], int(item.get("bottom", 0)) - pad_y)
                        if max_right is not None:
                            adjusted_item["left"] = min(adjusted_item["left"], max_right)
                            adjusted_item["right"] = min(adjusted_item["right"], max_right)
                        if max_bottom is not None:
                            adjusted_item["top"] = min(adjusted_item["top"], max_bottom)
                            adjusted_item["bottom"] = min(adjusted_item["bottom"], max_bottom)
                        adjusted.append(adjusted_item)
                    res = adjusted
                
                processed = postprocess_ocr_items(res)
                merged_res = processed.lines
                full_text = processed.text

                if not merged_res:
                    self.after(0, lambda: popup.set_ocr("未识别到文字（空）"))
                    self.after(0, lambda: popup.set_trans("（无需翻译）"))
                    return

                self.after(0, lambda: popup.set_ocr(full_text))

                translated = do_translate(full_text, target_lang=lang, engine=engine)
                self.after(0, lambda: popup.set_trans(translated, items=merged_res))

            threading.Thread(target=worker, daemon=True).start()
        self.after(0, _main)


    # ── 扫码（微信 OpenCV QR） ────────────────
    def _run_qrcode(self, img_path, lx1=0, ly1=0, lx2=400, ly2=300, crop_img=None):
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
        w.resizable(False, False)
        w.geometry(f"320x420+{self.winfo_x()}+{self.winfo_y() + self.winfo_height() + 10}")
        self._active_popup = w     # 单例登记
        w.protocol("WM_DELETE_WINDOW", lambda: (w.destroy(), setattr(self, '_active_popup', None)))
        w.bind("<Escape>", lambda e: (w.destroy(), setattr(self, '_active_popup', None)))

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
            try:
                qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                                   box_size=4, border=2)
                qr.add_data(text)
                qr.make(fit=True)
                img = qr.make_image(fill_color="black", back_color="white")
                # 固定显示尺寸 260x260，避免满屏
                pil_img = img.get_image() if hasattr(img, 'get_image') else img
                pil_img = pil_img.resize((260, 260), Image.LANCZOS)
            except Exception:
                import qrcode as _qr
                qr2 = _qr.QRCode(box_size=4, border=2)
                qr2.add_data(text)
                qr2.make(fit=True)
                pil_img = qr2.make_image(fill_color="black", back_color="white")
                from PIL import Image as _PImage
                pil_img = pil_img.resize((260, 260), _PImage.LANCZOS)

            # 保存到临时文件
            img_path = os.path.join(_WRITE_DIR, "_temp_qr.png")
            pil_img.save(img_path)

            photo = ImageTk.PhotoImage(pil_img)
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
        tw, th = t.winfo_width(), t.winfo_height()
        bounds = _get_virtual_screen_bounds(self)
        pos_x = self.winfo_rootx() + max(0, (self.winfo_width() - tw) // 2)
        pos_y = self.winfo_rooty() + self.winfo_height() + 12
        pos_x, pos_y = _clamp_rect_to_bounds(pos_x, pos_y, tw, th, bounds)
        t.geometry(f"+{pos_x}+{pos_y}")
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
    
    # 开启物理像素级 DPI 感知，防止 Windows 缩放导致截图模糊变糊
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2) # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        pass
    
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

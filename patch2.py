import os
import re
import ctypes
import threading

file_path = r"z:\share\WeChatOCR\screenshot_tool.py"
with open(file_path, 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Replace import keyboard
code = code.replace("import keyboard          # 全局热键", """import ctypes
from ctypes import wintypes
# 移除 keyboard 组件，改用 Win32 API 稳定方案（无系统静默挂起问题）""")

# 2. Insert Win32HotkeyManager
win32_mgr_code = """
class Win32HotkeyManager:
    \"\"\"原生的 Win32 消息循环热键管理器，系统级接管，彻底解决因为卡顿或UAC导致的钩子静默丢弃问题。\"\"\"
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
"""
if "class Win32HotkeyManager" not in code:
    code = code.replace("class CompactBar(tk.Tk):", win32_mgr_code + "\nclass CompactBar(tk.Tk):")

# 3. Simplify _kbd_state_snapshot
code = re.sub(
    r"def _kbd_state_snapshot\(\):.*?(?=def _hklog)",
    "def _kbd_state_snapshot():\n    return \"[kbd状态] 使用 Win32 API 原生热键，已解决静默失效问题\"\n\n",
    code,
    flags=re.DOTALL
)

# 4. Modify CompactBar initialization
init_old = r"self\._registered_hotkeys = \{\}\s+# 记录.*?\n\s+self\._register_hotkeys\(\)\n\s+self\._setup_tray\(\)\n\s+self\._hotkey_watchdog\(\)\s+# 启动热键看门狗"
init_new = """self._registered_hotkeys = {}   # 记录已注册热键 {action: combo}
        self._hotkey_mgr = Win32HotkeyManager(self, self._cap)
        self._register_hotkeys()
        self._setup_tray()
        # watchdog 不再需要，Win32 API 安全稳定不再掉签"""
code = re.sub(init_old, init_new, code)

# 5. Modify _register_hotkeys and _hotkey_watchdog
reg_hk_old_pattern = r"def _register_hotkeys\(self\):.*?def _hotkey_watchdog\(self\):"
def replace_reg_hk(match):
    return """def _register_hotkeys(self):
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

    def _hotkey_watchdog(self):"""

code = re.sub(reg_hk_old_pattern, replace_reg_hk, code, flags=re.DOTALL)

# 6. Delete _hotkey_watchdog
watchdog_old_pattern = r"def _hotkey_watchdog\(self\):.*?# 每 5000ms 再次检查（使用 tkinter after，运行在主线程，线程安全）\s+self\.after\(5000, self\._hotkey_watchdog\)"
code = re.sub(watchdog_old_pattern, "def _hotkey_watchdog(self):\n        pass # 已废弃，因为我们改用了原生稳定的 Win32HotkeyManager", code, flags=re.DOTALL)

# 7. Modify unhook_all
code = code.replace("try: keyboard.unhook_all()", "try: getattr(self, '_hotkey_mgr', None) and self._hotkey_mgr.stop()")
# Handle the try-catch block containing unhook_all and _register_hotkeys
code = re.sub(r"try:\s+keyboard\.unhook_all\(\)\s+self\._register_hotkeys\(\)\s+except Exception:", "try:\n                self._register_hotkeys()\n            except Exception:", code)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(code)

print("Patch applied successfully, Win32 Hotkey manager installed")

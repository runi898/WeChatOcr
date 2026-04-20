# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['screenshot_tool.py'],
    pathex=[],
    binaries=[('wcocr.pyd', '.')],
    datas=[('path', 'path'), ('icon.ico', '.'), ('wxocr.ico', '.')],
    hiddenimports=['pystray', 'qrcode', 'cv2', 'numpy', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WeChatOCR_Tool_v25',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['wxocr.ico'],
    version='version_info_v25.txt',
)

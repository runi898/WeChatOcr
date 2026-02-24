---
description: 单文件 exe 打包指令及依赖内嵌说明
---

# PyInstaller 打包单文件 exe 完整指令

在基于 WeChatOCR 开发截图工具或后续扩展时，如果需要将 Python 代码和相关的所有依赖环境（如微信 OCR 运行时模块、图片图标等资源）一并打包成体积小巧、绿色免安装、拖到任意电脑上都能直接双击运行的 **独立可执行单文件(exe)**，必须使用带有内嵌参数的 `pyinstaller` 指令。

## 完整指令（请在项目根目录运行）：
```powershell
pyinstaller -F -y -w `
  --add-data "path;path" `
  --add-binary "wcocr.pyd;." `
  --icon="wxocr.ico" `
  --name "WeChatOCR_Tool_v5" `
  screenshot_tool.py
```

## 核心打包参数讲解：
1. **`-F / --onefile`**: 这是最关键的参数，它指示 PyInstaller 将所有内容打包成单独的一个 `.exe`。
2. **`-w / --windowed`**: 打包为 GUI 视窗程序，双击运行时后台不会弹出黑乎乎的控制台（Console）窗口。
3. **`-y / --noconfirm`**: 覆盖打包输出目录中已存在的旧文件，自动确认无需询问。
4. **`--add-data "path;path"`**: 【内嵌数据】将外层的 `path` 文件夹及其子目录（如 WeChatOCR 离线模型核心）塞入 exe！左边是本地路径源，右边是解压后在临时系统运行目录 `sys._MEIPASS` 中的目标位置。
5. **`--add-binary "wcocr.pyd;."`**: 【内嵌二进制库】将核心的 Pyd 扩展包嵌入到根运行环境。
6. **`--icon="wxocr.ico"`**: 【生成图标】对生成的 EXE 可执行文件应用美观的桌面图标。
7. **`--name`**: 最终构建输出的名称定义。

## 代码运行时配合说明

执行这种深度内嵌打包后，被嵌在 exe 自体内部的（如上面定义的 `path`）在实机运行时其实是被系统暂时解压抛入了一个叫作 `_MEIPASS` 的临时环境之中。

因此如果在源码读取必须做如下判断，不能直接用 `./` 强读本地：
```python
import sys, os
if getattr(sys, 'frozen', False):
    # 打包运行环境，资源会在这：
    _RES_DIR = sys._MEIPASS
    # 需要存配置之类的本地可写环境不能放这里，推荐使用 APPDATA
else:
    # 本地跑代码时直接读取当前：
    _RES_DIR = os.path.dirname(os.path.abspath(__file__))
```

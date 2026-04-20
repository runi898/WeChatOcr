import os
import json
import urllib.request
import urllib.parse
from urllib.error import HTTPError

token = os.environ.get("GITHUB_TOKEN")
if not token:
    raise ValueError("Missing GITHUB_TOKEN")

repo = "runi898/WeChatOcr"
tag = "v1.0.2"
title = "WeChat OCR v1.0.2"
body = """# 🚀 更新日志 (v1.0.2)
1. **悬浮窗快捷键可视增强**：增加白色加粗文字和更深的对比色强调了悬浮球中的快捷键显示，并在设置窗口自定义之后能立即热更新生效！
2. **重排按钮顺序**：将常用功能进行合理排布（翻译 → 提取文字 → 截图 → 扫码 → 生成QR）。
3. **生成QR体验改进**：限定二维码弹窗使用最优固定比例防止在大屏幕上“满屏杀”；添加 ESC 快捷键退出监听。
4. **单例模式强化**：彻底解决了多次手抖连按快捷键导致页面无限叠加的 Bug。
5. **小键盘热键拦截修复**：修复了在 Windows 下按下 `Alt + 右侧小键盘数字（Numpad）` 时被默认转化出乱码 `??` 导致快捷键失效的问题，已能完全识别 `numpad1` - `numpad0`。
"""

headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Mozilla/5.0"
}

release_url = f"https://api.github.com/repos/{repo}/releases"
data = json.dumps({"tag_name": tag, "name": title, "body": body, "draft": False, "prerelease": False}).encode("utf-8")

print("Creating release...")
try:
    req = urllib.request.Request(release_url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as response:
        release_info = json.loads(response.read().decode())
        print("Release created successfully.")
except HTTPError as e:
    if e.code == 422: # Already exists
        print("Release already exists. Fetching info...")
        req = urllib.request.Request(f"{release_url}/tags/{tag}", headers=headers)
        with urllib.request.urlopen(req) as response:
            release_info = json.loads(response.read().decode())
    else:
        raise Exception(f"HTTPError: {e.code} {e.read().decode()}")

upload_url = release_info["upload_url"].split("{")[0]

exe_path = r"Z:\share\WeChatOCR\dist\wechatocr.exe"
print(f"Uploading assets from {exe_path} ...")

with open(exe_path, "rb") as f:
    exe_data = f.read()

upload_headers = headers.copy()
upload_headers["Content-Type"] = "application/octet-stream"

# Append ?name=wechatocr.exe
upload_req_url = f"{upload_url}?name=wechatocr.exe"

req_upload = urllib.request.Request(upload_req_url, data=exe_data, headers=upload_headers, method="POST")
try:
    with urllib.request.urlopen(req_upload) as response:
        print("Upload successful!")
except HTTPError as e:
    if e.code == 422:
        print("Asset already exists. Maybe deleting it first is needed.")
    else:
        print(f"Upload failed: HTTP {e.code} {e.read().decode()}")

print("Done!")

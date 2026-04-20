import os
import json
import urllib.request
from urllib.error import HTTPError

token = os.environ.get("GITHUB_TOKEN")
if not token:
    raise ValueError("Missing GITHUB_TOKEN")

repo = "runi898/WeChatOcr"
tag = "v1.0.4"
title = "WeChat OCR v1.0.4"
body = """# 更新日志 (v1.0.4)
1. 修复设置窗口在高 DPI / 高分屏下显示不全的问题，支持滚动与完整保存设置。
2. 改进副屏与虚拟桌面坐标适配，设置窗、日志窗、提示和翻译浮层会跟随当前屏幕位置。
3. 修复截图翻译自动扩边导致相邻行被一并识别的问题，OCR 现在严格使用用户实际框选区域。
4. 改进紧贴边缘的小范围 OCR 识别，给 OCR 输入增加背景留白，降低英文首尾字符丢失概率。
"""

headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Mozilla/5.0",
}

release_url = f"https://api.github.com/repos/{repo}/releases"
data = json.dumps(
    {"tag_name": tag, "name": title, "body": body, "draft": False, "prerelease": False}
).encode("utf-8")

print("Creating release...")
try:
    req = urllib.request.Request(release_url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as response:
        release_info = json.loads(response.read().decode())
        print("Release created successfully.")
except HTTPError as e:
    if e.code == 422:
        print("Release already exists. Fetching info...")
        req = urllib.request.Request(f"{release_url}/tags/{tag}", headers=headers)
        with urllib.request.urlopen(req) as response:
            release_info = json.loads(response.read().decode())
    else:
        raise Exception(f"HTTPError: {e.code} {e.read().decode()}")

upload_url = release_info["upload_url"].split("{")[0]

exe_path = r"Z:\share\WeChatOCR\dist\WeChatOCR_Tool_v104.exe"
print(f"Uploading assets from {exe_path} ...")

with open(exe_path, "rb") as f:
    exe_data = f.read()

upload_headers = headers.copy()
upload_headers["Content-Type"] = "application/octet-stream"

upload_req_url = f"{upload_url}?name=WeChatOCR_Tool_v104.exe"

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

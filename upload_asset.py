import os, json, urllib.request
from urllib.error import HTTPError

token = os.environ.get("GITHUB_TOKEN")
repo = "runi898/WeChatOcr"
tag = "v1.0.4"
headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Mozilla/5.0"
}

# 获取 release 信息
print("Fetching release info...")
req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=headers)
with urllib.request.urlopen(req) as resp:
    release_info = json.loads(resp.read().decode())

upload_url = release_info["upload_url"].split("{")[0]
print(f"Upload URL: {upload_url}")

# 上传 exe
exe_path = r"Z:\share\WeChatOCR\dist\WeChatOCR_Tool_v104.exe"
print(f"Reading {exe_path} ...")
with open(exe_path, "rb") as f:
    data = f.read()
print(f"File size: {len(data)} bytes")

upload_headers = headers.copy()
upload_headers["Content-Type"] = "application/octet-stream"

print("Uploading...")
req = urllib.request.Request(f"{upload_url}?name=WeChatOCR_Tool_v104.exe", data=data, headers=upload_headers, method="POST")
with urllib.request.urlopen(req, timeout=300) as resp:
    result = json.loads(resp.read().decode())
    print(f"Done! Download URL: {result.get('browser_download_url')}")

import json
import os
import urllib.parse
import urllib.request
from urllib.error import HTTPError


TOKEN = os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    raise ValueError("Missing GITHUB_TOKEN")

REPO = "runi898/WeChatOcr"
TAG = "v1.0.4"
TITLE = "WeChat OCR v1.0.4"
ASSET_NAME = "WeChat OCR v1.0.4.exe"
ASSET_PATH = r"Z:\share\WeChatOCR\dist\WeChat OCR v1.0.4.exe"
BODY = """# 更新日志 (v1.0.4)
1. 修复设置窗口在高 DPI / 高分屏下显示不全的问题，支持滚动与完整保存设置。
2. 改进副屏与虚拟桌面坐标适配，设置窗、日志窗、提示和翻译浮层会跟随当前屏幕位置。
3. 修复截图翻译自动扩边导致相邻行被一并识别的问题，OCR 现在严格使用用户实际框选区域。
4. 改进紧贴边缘的小范围 OCR 识别，给 OCR 输入增加背景留白，降低英文首尾字符丢失概率。
5. 修复翻译文本在原选区底部被裁切的问题，覆盖层会按排版需要自动增高。
"""

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "Mozilla/5.0",
}


def request_json(url: str, method: str = "GET", data: dict | None = None) -> dict:
    payload = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=HEADERS, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_release() -> dict:
    base = f"https://api.github.com/repos/{REPO}/releases"
    try:
        release = request_json(f"{base}/tags/{TAG}")
        print("Release exists, updating metadata...")
        return request_json(
            f"{base}/{release['id']}",
            method="PATCH",
            data={"name": TITLE, "body": BODY, "draft": False, "prerelease": False},
        )
    except HTTPError as err:
        if err.code != 404:
            raise
        print("Release not found, creating...")
        return request_json(
            base,
            method="POST",
            data={"tag_name": TAG, "name": TITLE, "body": BODY, "draft": False, "prerelease": False},
        )


def delete_existing_asset(release: dict) -> None:
    for asset in release.get("assets", []):
        if asset.get("name") == ASSET_NAME:
            print(f"Deleting existing asset: {ASSET_NAME}")
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/assets/{asset['id']}",
                headers=HEADERS,
                method="DELETE",
            )
            with urllib.request.urlopen(req):
                pass
            return


def upload_asset(release: dict) -> None:
    upload_url = release["upload_url"].split("{")[0]
    with open(ASSET_PATH, "rb") as f:
        exe_data = f.read()

    headers = HEADERS.copy()
    headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(
        f"{upload_url}?name={urllib.parse.quote(ASSET_NAME)}",
        data=exe_data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    print("Upload successful!")
    print(result.get("browser_download_url", ""))


if __name__ == "__main__":
    release = ensure_release()
    delete_existing_asset(release)
    refreshed = request_json(f"https://api.github.com/repos/{REPO}/releases/{release['id']}")
    upload_asset(refreshed)

import wcocr
import json
import os

img_path = os.path.abspath("test.png")
wcocr.init(os.path.abspath("path/WeChatOCR/WeChatOCR.exe"), os.path.abspath("path"))
print("OCR INIT DONE")
result = wcocr.ocr(img_path)
print("JSON OUTPUT:")
print(json.dumps(result, indent=2))

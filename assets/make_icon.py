# icon.png → icon.ico 변환 스크립트
# 실행: python assets/make_icon.py
from PIL import Image
import os

src = os.path.join(os.path.dirname(__file__), "icon.png")
dst = os.path.join(os.path.dirname(__file__), "icon.ico")

img = Image.open(src).convert("RGBA")
sizes = [256, 128, 64, 48, 32, 16]
img.save(dst, format="ICO", sizes=[(s, s) for s in sizes])
print(f"Saved: {dst}")

# -*- coding: utf-8 -*-
"""
从 assets/icon.png 生成 Windows 程序图标 assets/app.ico

- 原图是竖版人物立绘，程序图标需要正方形，因此以头部为中心做正方形裁剪
- 输出多尺寸 ico（16/32/48/64/128/256），保证任务栏、桌面、文件管理器各处都清晰
- 同时输出一张 icon_preview.png 便于肉眼确认裁剪效果

用法：.venv\\Scripts\\python.exe tools\\make_icon.py
"""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "icon.png")
DST_ICO = os.path.join(ROOT, "assets", "app.ico")
DST_PNG = os.path.join(ROOT, "assets", "icon_preview.png")
# 界面顶栏用的圆形头像
DST_AVATAR = os.path.join(ROOT, "web", "avatar.png")
AVATAR_SIZE = 128

SIZES = [256, 128, 64, 48, 32, 16]

# 裁剪参数：以头部为中心（按原图比例估算，可用 preview 核对）
SIDE_RATIO = 0.63      # 正方形边长 = 短边 × 该比例
CENTER_X_RATIO = 0.47  # 头部中心横向位置
CENTER_Y_RATIO = 0.27  # 头部中心纵向位置


def main():
    im = Image.open(SRC).convert("RGBA")
    w, h = im.size

    side = int(min(w, h) * SIDE_RATIO)
    cx, cy = int(w * CENTER_X_RATIO), int(h * CENTER_Y_RATIO)
    left = max(0, min(cx - side // 2, w - side))
    top = max(0, min(cy - side // 2, h - side))
    box = (left, top, left + side, top + side)

    sq = im.crop(box).resize((256, 256), Image.LANCZOS)
    sq.save(DST_PNG)
    sq.save(DST_ICO, format="ICO", sizes=[(s, s) for s in SIZES])
    # 顶栏头像（略小即可）
    sq.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS).save(DST_AVATAR)

    print("原图尺寸 : %dx%d" % (w, h))
    print("裁剪区域 : %s  边长 %d" % (box, side))
    print("已生成   : %s" % DST_ICO)
    print("预览图   : %s" % DST_PNG)
    print("界面头像 : %s" % DST_AVATAR)


if __name__ == "__main__":
    main()

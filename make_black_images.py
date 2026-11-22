# -*- coding: utf-8 -*-
import os, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = '1688_1041092037687'
OUT = '淘宝主图_黑色极简'
os.makedirs(OUT, exist_ok=True)

BOLD = r'C:\Windows\Fonts\msyhbd.ttc'
REG = r'C:\Windows\Fonts\msyh.ttc'
INK = (28, 28, 28)
GRAY = (150, 145, 140)
ROSE = (232, 70, 124)

def F(p, s):
    return ImageFont.truetype(p, s)

def whiten_bg(im, lo=196, hi=224):
    a = np.asarray(im).astype(np.float32)
    mn = a.min(axis=2, keepdims=True)
    t = np.clip((mn - lo) / (hi - lo), 0, 1)
    t = t * t * (3 - 2 * t)
    out = a * (1 - t) + 255.0 * t
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))

def crop_resize(im, box, w, h):
    im = im.crop(box)
    return im.resize((w, h), Image.LANCZOS)

def dashed_ellipse(draw, bbox, color, width=3, dash=16, gap=10):
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    total = math.pi * (3 * (rx + ry) - math.sqrt((3 * rx + ry) * (rx + 3 * ry)))
    n = max(1, int(total / (dash + gap)))
    for i in range(n):
        a0 = i * 2 * math.pi / n
        a1 = a0 + (dash / total) * 2 * math.pi
        pts = []
        for k in range(25):
            a = a0 + (a1 - a0) * k / 24
            pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        draw.line(pts, fill=color, width=width, joint='curve')

def footer(canvas, main, sub):
    d = ImageDraw.Draw(canvas)
    d.rectangle([46, 712, 56, 722], fill=ROSE)
    d.text((74, 696), main, font=F(BOLD, 30), fill=INK)
    d.text((74, 742), sub, font=F(REG, 20), fill=GRAY)

def with_footer(photo, main, sub):
    canvas = Image.new('RGB', (800, 800), (255, 255, 255))
    canvas.paste(photo, (0, 0))
    footer(canvas, main, sub)
    return canvas

def save(canvas, name):
    canvas.save(os.path.join(OUT, name), quality=93)
    print(name, 'ok')

src27 = Image.open(os.path.join(ROOT, '详情页图', '详情_27.jpg')).convert('RGB')
src28 = Image.open(os.path.join(ROOT, '详情页图', '详情_28.jpg')).convert('RGB')
src29 = Image.open(os.path.join(ROOT, '详情页图', '详情_29.jpg')).convert('RGB')

# 1 首图：纯白底、无文字（白底图流量位）
photo = crop_resize(src29, (0, 25, 790, 1015), 623, 800)
photo = whiten_bg(photo)
photo = ImageEnhance.Contrast(photo).enhance(1.02)
canvas = Image.new('RGB', (800, 800), (255, 255, 255))
canvas.paste(photo, ((800 - 623) // 2, 0))
save(canvas, '黑1_首图_白底无字.jpg')

# 2 口袋细节
photo = crop_resize(src28, (0, 100, 790, 781), 800, 690)
photo = whiten_bg(photo)
save(with_footer(photo, '侧边隐形口袋', '手机钥匙随身放 运动不累赘'), '黑2_口袋细节.jpg')

# 3 背面提臀
photo = crop_resize(src28, (0, 1150, 790, 1831), 800, 690)
photo = whiten_bg(photo)
save(with_footer(photo, 'M型提臀弧线', '蜜桃臀 穿出来'), '黑3_背面提臀.jpg')

# 4 高腰版型
photo = crop_resize(src27, (0, 1350, 790, 2031), 800, 690)
photo = whiten_bg(photo)
save(with_footer(photo, '高腰收腹 无尴尬线', '高弹贴合 不卷边'), '黑4_高腰版型.jpg')

# 5 面料细节
photo = crop_resize(src27, (250, 1150, 750, 1583), 800, 690)
photo = whiten_bg(photo)
arr = np.clip(np.asarray(photo).astype(np.float32) / 255.0, 0, 1) ** 0.9
photo = Image.fromarray((arr * 255).astype(np.uint8))
photo = ImageEnhance.Sharpness(photo).enhance(1.4)
save(with_footer(photo, '双面裸感面料', '75%锦纶 25%氨纶 · 高弹回弹'), '黑5_面料细节.jpg')

# 校验白底
for f in sorted(os.listdir(OUT)):
    im = Image.open(os.path.join(OUT, f))
    a = np.asarray(im)
    corners = [tuple(a[2, 2]), tuple(a[2, 797]), tuple(a[797, 2]), tuple(a[797, 797])]
    print(f, im.size, 'corners:', corners)

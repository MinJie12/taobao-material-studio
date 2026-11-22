# -*- coding: utf-8 -*-
import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = '1688_1041092037687'
OUT = '淘宝详情页_黑色高清'
os.makedirs(OUT, exist_ok=True)

W, H = 1200, 1600
BOLD = r'C:\Windows\Fonts\msyhbd.ttc'
REG = r'C:\Windows\Fonts\msyh.ttc'
INK = (26, 26, 26)
ROSE = (232, 70, 124)
WARM = (247, 244, 240)
WHITE = (255, 255, 255)
DARKROSE = (110, 40, 66)


def F(path, size):
    return ImageFont.truetype(path, size)


def load(path, enhance=True):
    im = Image.open(path).convert('RGB')
    if enhance:
        im = ImageEnhance.Color(im).enhance(1.06)
        im = ImageEnhance.Contrast(im).enhance(1.03)
        im = ImageEnhance.Brightness(im).enhance(1.02)
    return im


def fit(im, crop, w, h):
    out = im.crop(crop).resize((w, h), Image.LANCZOS)
    return ImageEnhance.Sharpness(out).enhance(1.15)


def text_sh(d, xy, txt, font, fill=WHITE, anchor='la', off=3, shadow=(0, 0, 0, 120)):
    x, y = xy
    d.text((x + off, y + off), txt, font=font, fill=shadow, anchor=anchor)
    d.text((x, y), txt, font=font, fill=fill, anchor=anchor)


def band(h, top, bottom):
    g = Image.new('RGBA', (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)))
    return g.resize((W, h))


def dashed_ellipse(d, bbox, color, width=7, dash=28, gap=18):
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
        d.line(pts, fill=color, width=width, joint='curve')


def arrow(d, p1, p2, color, width=7, head=24):
    d.line([p1, p2], fill=color, width=width)
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    for da in (math.radians(155), math.radians(-155)):
        d.line([p2, (p2[0] + head * math.cos(ang + da), p2[1] + head * math.sin(ang + da))], fill=color, width=width)


def save(canvas, name):
    canvas.save(os.path.join(OUT, name), quality=93, subsampling=0)
    print(name)


front = load(os.path.join(ROOT, '详情页图', '详情_29.jpg'))
back = load(os.path.join(ROOT, '详情页图', '详情_28.jpg'))
fabric = load(os.path.join(ROOT, '详情页图', '详情_27.jpg'))
black = load(os.path.join(ROOT, 'sku图', 'SKU_03_黑色.jpg'))


def section1():
    canvas = Image.new('RGB', (W, H), WARM)
    canvas.paste(fit(front, (0, 120, 720, 1720), 720, H), (0, 0))
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.rectangle([716, 0, 720, H], fill=ROSE + (70,))
    d.text((760, 170), '黑色高腰', font=F(BOLD, 88), fill=INK)
    d.text((750, 286), '提臀三分裤', font=F(BOLD, 84), fill=ROSE)
    d.rectangle([760, 420, 900, 430], fill=ROSE)
    items = ['高腰收腹 显瘦有型', '侧边口袋 随身收纳', '裸感面料 高弹不勒']
    for i, t in enumerate(items):
        y = 500 + i * 130
        d.rounded_rectangle([748, y, 1160, y + 90], radius=30, fill=(255, 255, 255, 230))
        d.ellipse([774, y + 32, 794, y + 52], fill=ROSE)
        d.text((814, y + 45), t, font=F(BOLD, 34), fill=INK, anchor='lm')
    d.rounded_rectangle([748, 1320, 1160, 1400], radius=40, fill=ROSE)
    d.text((954, 1360), '运动通勤 一裤多穿', font=F(BOLD, 34), fill=WHITE, anchor='mm')
    save(canvas, '详情1_黑色高腰提臀.jpg')


def section2():
    canvas = fit(back, (0, 700, 790, 1753), W, H)
    d = ImageDraw.Draw(canvas, 'RGBA')
    top = band(340, (0, 0, 0, 170), (0, 0, 0, 0))
    canvas.paste(top, (0, 0), top)
    text_sh(d, (70, 60), 'M型提臀弧线', F(BOLD, 76), WHITE)
    text_sh(d, (72, 170), '蜜桃臀 穿出来', F(REG, 42), (255, 235, 242))
    dashed_ellipse(d, (330, 520, 900, 1060), (255, 255, 255, 240), width=7)
    arrow(d, (1060, 430), (900, 560), WHITE, width=7)
    text_sh(d, (1070, 395), '3D提拉', F(BOLD, 36), WHITE, anchor='lm')
    d.rounded_rectangle([60, 1300, 1140, 1530], radius=36, fill=(255, 255, 255, 235))
    feats = ['高弹贴合', '不卷边', '不卡裆']
    for i, t in enumerate(feats):
        x = 120 + i * 360
        d.ellipse([x, 1370, x + 28, 1398], fill=ROSE)
        d.text((x + 50, 1384), t, font=F(BOLD, 38), fill=INK, anchor='lm')
    save(canvas, '详情2_M型提臀弧线.jpg')


def section3():
    canvas = Image.new('RGB', (W, H), WARM)
    photo = black.resize((1000, 1000), Image.LANCZOS)
    photo = ImageEnhance.Sharpness(photo).enhance(1.15)
    canvas.paste(photo, (100, 100))
    d = ImageDraw.Draw(canvas, 'RGBA')
    dashed_ellipse(d, (600, 410, 1010, 900), ROSE + (235,), width=7)
    d.text((100, 1200), '侧边隐形口袋', font=F(BOLD, 76), fill=INK)
    d.text((102, 1310), '手机钥匙随身放 运动不累赘', font=F(REG, 40), fill=(110, 104, 100))
    d.rounded_rectangle([100, 1400, 1100, 1490], radius=45, fill=DARKROSE)
    d.text((600, 1445), '高腰收腹 · 无尴尬线 · 出门不带包', font=F(BOLD, 32), fill=WHITE, anchor='mm')
    save(canvas, '详情3_侧边隐形口袋.jpg')


def section4():
    canvas = Image.new('RGB', (W, H), WARM)
    canvas.paste(fit(fabric, (80, 300, 710, 1626), 760, H), (0, 0))
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.text((800, 150), '双面裸感面料', font=F(BOLD, 60), fill=INK)
    d.text((802, 270), '触肤即柔 如第二层肌肤', font=F(REG, 32), fill=(110, 104, 100))
    d.rounded_rectangle([800, 390, 1160, 650], radius=32, fill=(255, 255, 255, 235))
    d.text((980, 460), '75%', font=F(BOLD, 64), fill=ROSE, anchor='mm')
    d.text((980, 540), '锦纶 Nylon', font=F(REG, 30), fill=INK, anchor='mm')
    d.line([(850, 590), (1110, 590)], fill=(226, 218, 210), width=3)
    d.text((980, 625), '25% 氨纶 Spandex', font=F(REG, 28), fill=(110, 104, 100), anchor='mm')
    feats = ['软糯亲肤', '高弹回弹', '吸湿排汗', '轻薄透气']
    for i, t in enumerate(feats):
        x = 800 + (i % 2) * 190
        y = 720 + (i // 2) * 150
        d.rounded_rectangle([x, y, x + 170, y + 110], radius=26, fill=(255, 255, 255, 230))
        d.text((x + 85, y + 55), t, font=F(BOLD, 26), fill=INK, anchor='mm')
    d.rectangle([0, 1480, W, H], fill=DARKROSE + (255,))
    d.text((600, 1540), '轻薄裸感 · 高弹不勒 · 运动无负担', font=F(BOLD, 34), fill=WHITE, anchor='mm')
    save(canvas, '详情4_双面裸感面料.jpg')


def section5():
    colors = [
        ('奶油黄', 'SKU_01_奶油黄.jpg'),
        ('石英玫瑰', 'SKU_02_石英玫瑰.jpg'),
        ('黑色', 'SKU_03_黑色.jpg'),
        ('白色', 'SKU_04_白色.jpg'),
        ('橄榄绿', 'SKU_05_橄榄绿.jpg'),
        ('浅粉', 'SKU_06_浅粉.jpg'),
        ('海军蓝', 'SKU_07_海军蓝.jpg'),
    ]
    canvas = Image.new('RGB', (W, H), WARM)
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.text((600, 100), '7色可选', font=F(BOLD, 86), fill=INK, anchor='ma')
    d.text((600, 220), 'COLOR OPTIONS · 运动通勤一色一件', font=F(REG, 36), fill=(130, 120, 116), anchor='ma')
    d.rectangle([540, 286, 660, 294], fill=ROSE)
    tile, gap, cols = 250, 24, 4
    x0 = (W - (tile * cols + gap * (cols - 1))) // 2
    y0 = 360
    mask = Image.new('L', (tile, tile), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile - 1, tile - 1], radius=28, fill=255)
    for i, (name, fn) in enumerate(colors):
        im = load(os.path.join(ROOT, 'sku图', fn))
        im = im.resize((tile, tile), Image.LANCZOS)
        x = x0 + (i % cols) * (tile + gap)
        y = y0 + (i // cols) * (tile + gap + 64)
        canvas.paste(im, (x, y), mask)
        d.text((x + tile // 2, y + tile + 34), name, font=F(BOLD, 32), fill=(70, 64, 62), anchor='mm')
    lx = x0 + 3 * (tile + gap)
    ly = y0 + (tile + gap + 64)
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=28, fill=WHITE)
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=28, outline=(226, 218, 210), width=3)
    d.text((lx + tile // 2, ly + 90), '更多', font=F(BOLD, 44), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + 150), '颜色', font=F(BOLD, 44), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + 210), '进店选购', font=F(REG, 26), fill=(150, 140, 136), anchor='mm')
    d.rounded_rectangle([200, 1420, 1000, 1510], radius=45, fill=INK)
    d.text((600, 1465), '高腰提臀 · 侧边口袋 · 裸感面料', font=F(BOLD, 34), fill=WHITE, anchor='mm')
    save(canvas, '详情5_七色可选.jpg')


section1()
section2()
section3()
section4()
section5()

parts = [
    '详情1_黑色高腰提臀.jpg',
    '详情2_M型提臀弧线.jpg',
    '详情3_侧边隐形口袋.jpg',
    '详情4_双面裸感面料.jpg',
    '详情5_七色可选.jpg',
]
long_canvas = Image.new('RGB', (W, H * len(parts)), WARM)
for i, name in enumerate(parts):
    long_canvas.paste(Image.open(os.path.join(OUT, name)).convert('RGB'), (0, i * H))
long_canvas.save(os.path.join(OUT, '详情页_黑色高清_长图.jpg'), quality=91, subsampling=0)
print('DETAIL PAGES DONE')

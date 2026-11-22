# -*- coding: utf-8 -*-
import os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = '1688_1041092037687'
OUT = '淘宝详情页_新版参考'
os.makedirs(OUT, exist_ok=True)

W, H = 1200, 1600
BOLD = r'C:\Windows\Fonts\msyhbd.ttc'
REG = r'C:\Windows\Fonts\msyh.ttc'
INK = (26, 26, 26)
ROSE = (232, 70, 124)
WARM = (247, 244, 240)
WHITE = (255, 255, 255)
GRAY = (110, 104, 100)
DARKROSE = (110, 40, 66)


def F(path, size):
    return ImageFont.truetype(path, size)


def load(path):
    im = Image.open(path).convert('RGB')
    im = ImageEnhance.Color(im).enhance(1.06)
    im = ImageEnhance.Contrast(im).enhance(1.03)
    im = ImageEnhance.Brightness(im).enhance(1.02)
    return im


def cover(im, size):
    tw, th = size
    w, h = im.size
    target = tw / th
    if w / h > target:
        nw = int(h * target)
        x = (w - nw) // 2
        im = im.crop((x, 0, x + nw, h))
    else:
        nh = int(w / target)
        y = (h - nh) // 2
        im = im.crop((0, y, w, y + nh))
    out = im.resize(size, Image.LANCZOS)
    return ImageEnhance.Sharpness(out).enhance(1.15)


def text_sh(d, xy, txt, font, fill=WHITE, anchor='la', off=3):
    x, y = xy
    d.text((x + off, y + off), txt, font=font, fill=(0, 0, 0, 110), anchor=anchor)
    d.text((x, y), txt, font=font, fill=fill, anchor=anchor)


def save(canvas, name):
    canvas.save(os.path.join(OUT, name), quality=93, subsampling=0)
    print(name)


def photo_section(photo_name, title, subtitle, bullets, out_name, badge):
    canvas = Image.new('RGB', (W, H), WARM)
    canvas.paste(cover(load(os.path.join(ROOT, '主图', photo_name)), (760, 1400)), (40, 100))
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.rectangle([796, 100, 800, 1500], fill=ROSE + (70,))
    d.rounded_rectangle([810, 160, 1160, 226], radius=32, fill=ROSE)
    d.text((985, 193), badge, font=F(BOLD, 30), fill=WHITE, anchor='mm')
    d.text((810, 300), title, font=F(BOLD, 56), fill=INK)
    d.text((800, 400), subtitle, font=F(REG, 28), fill=GRAY)
    d.rectangle([810, 480, 910, 488], fill=ROSE)
    for i, t in enumerate(bullets):
        y = 550 + i * 150
        d.rounded_rectangle([810, y, 1160, y + 110], radius=28, fill=(255, 255, 255, 230))
        d.ellipse([834, y + 41, 856, y + 63], fill=ROSE)
        d.text((876, y + 52), t, font=F(BOLD, 28), fill=INK, anchor='lm')
    d.rectangle([0, 1500, W, H], fill=DARKROSE + (255,))
    d.text((600, 1550), '高腰提臀 · 侧边口袋 · 裸感面料', font=F(BOLD, 34), fill=WHITE, anchor='mm')
    save(canvas, out_name)


photo_section(
    '主图_04.jpg',
    '高腰提臀',
    '三分瑜伽裤 运动通勤都能穿',
    ['高腰收腹 显瘦有型', '侧边口袋 随身收纳', '高弹裸感 不勒不卷'],
    '新详情1_产品总览.jpg',
    'PRODUCT OVERVIEW',
)

photo_section(
    '主图_02.jpg',
    'M型提臀线',
    '后腰立体剪裁 自然提拉',
    ['蜜桃臀线条', '贴合不卡裆', '运动不卷边'],
    '新详情2_提臀版型.jpg',
    'HIP LIFT',
)

photo_section(
    '主图_01.jpg',
    '侧边隐形口袋',
    '手机钥匙随身放 出门不带包',
    ['侧边深口袋', '高腰收腹', '无尴尬线'],
    '新详情3_侧边口袋.jpg',
    'POCKET',
)

photo_section(
    '主图_03.jpg',
    '双面裸感面料',
    '触肤即柔 如第二层肌肤',
    ['75%锦纶 25%氨纶', '吸湿排汗 轻薄透气', '软糯亲肤 高弹回弹'],
    '新详情4_面料细节.jpg',
    'FABRIC',
)


def colors_section():
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
    d.text((600, 90), '7色可选', font=F(BOLD, 84), fill=INK, anchor='ma')
    d.text((600, 210), 'COLOR OPTIONS · 运动通勤一色一件', font=F(REG, 34), fill=GRAY, anchor='ma')
    d.rectangle([540, 280, 660, 288], fill=ROSE)
    tile, gap, cols = 240, 24, 4
    x0 = (W - (tile * cols + gap * (cols - 1))) // 2
    y0 = 350
    mask = Image.new('L', (tile, tile), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile - 1, tile - 1], radius=28, fill=255)
    for i, (name, fn) in enumerate(colors):
        im = load(os.path.join(ROOT, 'sku图', fn)).resize((tile, tile), Image.LANCZOS)
        x = x0 + (i % cols) * (tile + gap)
        y = y0 + (i // cols) * (tile + gap + 62)
        canvas.paste(im, (x, y), mask)
        d.text((x + tile // 2, y + tile + 34), name, font=F(BOLD, 30), fill=INK, anchor='mm')
    lx = x0 + 3 * (tile + gap)
    ly = y0 + (tile + gap + 62)
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=28, fill=WHITE)
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=28, outline=(226, 218, 210), width=3)
    d.text((lx + tile // 2, ly + 88), '更多', font=F(BOLD, 42), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + 148), '颜色', font=F(BOLD, 42), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + 204), '进店选购', font=F(REG, 24), fill=GRAY, anchor='mm')
    d.rounded_rectangle([200, 1420, 1000, 1510], radius=45, fill=INK)
    d.text((600, 1465), '高腰提臀 · 侧边口袋 · 裸感面料', font=F(BOLD, 34), fill=WHITE, anchor='mm')
    save(canvas, '新详情5_多色可选.jpg')


def reference_section():
    canvas = Image.new('RGB', (W, H), WARM)
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.text((600, 90), '原详情页实拍参考', font=F(BOLD, 78), fill=INK, anchor='ma')
    d.text((600, 205), '基于商品详情页素材重新排版', font=F(REG, 34), fill=GRAY, anchor='ma')
    items = [
        ('详情_01.jpg', '实拍展示'),
        ('详情_02.jpg', '版型细节'),
        ('详情_03.jpg', '穿着效果'),
        ('详情_05.jpg', '面料细节'),
    ]
    for i, (fn, cap) in enumerate(items):
        x = 60 + (i % 2) * 580
        y = 300 + (i // 2) * 590
        im = cover(load(os.path.join(ROOT, '详情页图', fn)), (520, 500))
        canvas.paste(im, (x, y))
        d.rounded_rectangle([x, y + 500, x + 520, y + 560], radius=24, fill=(255, 255, 255, 235))
        d.text((x + 260, y + 530), cap, font=F(BOLD, 30), fill=INK, anchor='mm')
    d.rectangle([0, 1500, W, H], fill=DARKROSE + (255,))
    d.text((600, 1550), '实拍素材 · 新版排版 · 多色呈现', font=F(BOLD, 34), fill=WHITE, anchor='mm')
    save(canvas, '新详情6_原页实拍参考.jpg')


colors_section()
reference_section()

parts = [
    '新详情1_产品总览.jpg',
    '新详情2_提臀版型.jpg',
    '新详情3_侧边口袋.jpg',
    '新详情4_面料细节.jpg',
    '新详情5_多色可选.jpg',
    '新详情6_原页实拍参考.jpg',
]
long_canvas = Image.new('RGB', (W, H * len(parts)), WARM)
for i, name in enumerate(parts):
    long_canvas.paste(Image.open(os.path.join(OUT, name)).convert('RGB'), (0, i * H))
long_canvas.save(os.path.join(OUT, '新版详情页_长图.jpg'), quality=91, subsampling=0)
print('DETAIL REFERENCE DONE')

# -*- coding: utf-8 -*-
import os, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = '1688_1041092037687'
OUT = '淘宝主图_黑色爆款'
os.makedirs(OUT, exist_ok=True)

BOLD = r'C:\Windows\Fonts\msyhbd.ttc'
REG = r'C:\Windows\Fonts\msyh.ttc'
INK = (26, 23, 21)
CREAM = (247, 240, 230)
CORAL = (255, 77, 46)
YELLOW = (255, 205, 60)
WHITE = (255, 255, 255)
GRAY = (110, 104, 100)
RNG = np.random.default_rng(42)

def F(p, s):
    return ImageFont.truetype(p, s)

def load(path):
    return Image.open(path).convert('RGB')

def crop_resize(im, box, w, h):
    return im.crop(box).resize((w, h), Image.LANCZOS)

def warm_grade(im, sat=1.05, lift=6):
    a = np.asarray(im).astype(np.float32)
    a[..., 0] *= 1.035
    a[..., 2] *= 0.945
    a = a * 0.975 + lift
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return ImageEnhance.Color(out).enhance(sat)

def grain(im, strength=3.2):
    a = np.asarray(im).astype(np.int16)
    n = RNG.normal(0, strength, (a.shape[0], a.shape[1], 1)).astype(np.int16)
    return Image.fromarray(np.clip(a + n, 0, 255).astype(np.uint8))

def panel(d, box, fill=(247, 240, 230, 250), radius=18):
    d.rounded_rectangle(box, radius=radius, fill=fill)

def check(d, x, y, s, color, w=4):
    d.line([(x, y + s * 0.52), (x + s * 0.34, y + s * 0.86)], fill=color, width=w)
    d.line([(x + s * 0.34, y + s * 0.86), (x + s, y + s * 0.18)], fill=color, width=w)

def bottom_bar(canvas, text, fg=WHITE, bg=(26, 23, 21, 232)):
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.rounded_rectangle([36, 700, 764, 762], radius=31, fill=bg)
    d.text((400, 731), text, font=F(BOLD, 26), fill=fg, anchor='mm')

def sticker(txt, font, fg, bg, angle=-6, padx=20, pady=10, radius=10):
    probe = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    w = int(probe.textlength(txt, font=font))
    h = font.size + 2 * pady
    img = Image.new('RGBA', (w + 2 * padx, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(img)
    dd.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=radius, fill=bg)
    dd.text((img.width // 2, img.height // 2), txt, font=font, fill=fg, anchor='mm')
    return img.rotate(angle, expand=True, resample=Image.BICUBIC)

def place(canvas, img, xy):
    canvas.paste(img, xy, img)

def save(canvas, name):
    canvas.save(os.path.join(OUT, name), quality=93)
    print(name, 'ok')

src27 = load(os.path.join(ROOT, '详情页图', '详情_27.jpg'))
src28 = load(os.path.join(ROOT, '详情页图', '详情_28.jpg'))
src29 = load(os.path.join(ROOT, '详情页图', '详情_29.jpg'))
sku03 = load(os.path.join(ROOT, 'sku图', 'SKU_03_黑色.jpg'))

# 1 首图：产品占比高 + 暖调 + 大字短词
photo = crop_resize(src29, (0, 240, 790, 1030), 800, 800)
photo = grain(warm_grade(photo))
d = ImageDraw.Draw(photo, 'RGBA')
panel(d, [30, 34, 452, 208])
d.text((54, 48), '高腰提臀', font=F(BOLD, 66), fill=INK)
d.text((56, 132), '显瘦三分裤', font=F(BOLD, 40), fill=CORAL)
d.rectangle([56, 184, 170, 190], fill=CORAL)
st = sticker('7色可选', F(BOLD, 30), INK, YELLOW, angle=-6)
place(photo, st, (600, 34))
bottom_bar(photo, '侧边口袋 · 裸感高弹 · 高腰显瘦')
save(photo, '爆款1_首图_高腰提臀.jpg')

# 2 提臀卖点
photo = crop_resize(src28, (0, 1150, 790, 1940), 800, 800)
photo = grain(warm_grade(photo))
d = ImageDraw.Draw(photo, 'RGBA')
# 珊瑚色圈注（先画，避免压住文字板）
d.ellipse([285, 112, 615, 336], outline=(255, 77, 46, 235), width=5)
panel(d, [30, 34, 440, 190])
d.text((54, 46), 'M型提臀', font=F(BOLD, 64), fill=INK)
d.text((56, 124), '蜜桃臀 穿出来', font=F(BOLD, 34), fill=CORAL)
d.line([(56, 172), (166, 172)], fill=CORAL, width=5)
st = sticker('3D提拉', F(BOLD, 26), WHITE, CORAL, angle=-6)
place(photo, st, (596, 150))
bottom_bar(photo, '高弹贴合 · 不卷边 · 不卡裆')
save(photo, '爆款2_提臀卖点.jpg')

# 3 口袋卖点
photo = sku03.resize((800, 800), Image.LANCZOS)
photo = grain(warm_grade(photo, sat=1.03))
d = ImageDraw.Draw(photo, 'RGBA')
panel(d, [30, 34, 470, 196])
d.text((54, 46), '侧边口袋', font=F(BOLD, 64), fill=INK)
d.text((56, 126), '手机钥匙 随身放', font=F(BOLD, 32), fill=CORAL)
d.line([(56, 178), (166, 178)], fill=CORAL, width=5)
d.ellipse([470, 430, 780, 700], outline=(255, 77, 46, 235), width=5)
st = sticker('隐形收纳', F(BOLD, 26), WHITE, CORAL, angle=-6)
place(photo, st, (612, 352))
bottom_bar(photo, '运动不累赘 · 出门不带包')
save(photo, '爆款3_口袋卖点.jpg')

# 4 面料卖点
photo = crop_resize(src27, (150, 1160, 740, 1750), 800, 800)
photo = grain(warm_grade(photo, sat=1.02, lift=8))
photo = ImageEnhance.Sharpness(photo).enhance(1.25)
d = ImageDraw.Draw(photo, 'RGBA')
panel(d, [30, 34, 470, 200])
d.text((54, 46), '双面裸感', font=F(BOLD, 64), fill=INK)
d.text((56, 128), '高弹亲肤 第二层肌肤', font=F(BOLD, 30), fill=CORAL)
d.line([(56, 178), (166, 178)], fill=CORAL, width=5)
st = sticker('75%锦纶 · 25%氨纶', F(BOLD, 24), WHITE, (26, 23, 21, 240), angle=-4)
place(photo, st, (462, 40))
feats = ['软糯亲肤', '高弹回弹', '吸湿排汗', '轻薄透气']
bw, gap = 168, 13
x0 = (800 - bw * 4 - gap * 3) // 2
for i, t in enumerate(feats):
    x = x0 + i * (bw + gap)
    d.rounded_rectangle([x, 700, x + bw, 756], radius=28, fill=(255, 255, 255, 225))
    check(d, x + 18, 712, 30, CORAL, w=4)
    d.text((x + 58, 728), t, font=F(BOLD, 23), fill=INK, anchor='lm')
save(photo, '爆款4_面料卖点.jpg')

# 5 多色展示
colors = [
    ('黑色', 'SKU_03_黑色.jpg'),
    ('奶油黄', 'SKU_01_奶油黄.jpg'),
    ('石英玫瑰', 'SKU_02_石英玫瑰.jpg'),
    ('白色', 'SKU_04_白色.jpg'),
    ('橄榄绿', 'SKU_05_橄榄绿.jpg'),
    ('浅粉', 'SKU_06_浅粉.jpg'),
    ('海军蓝', 'SKU_07_海军蓝.jpg'),
]
canvas = Image.new('RGB', (800, 800), CREAM)
d = ImageDraw.Draw(canvas, 'RGBA')
d.text((400, 36), '7色可选', font=F(BOLD, 62), fill=INK, anchor='ma')
d.text((400, 112), '运动通勤 一色一件不重样', font=F(BOLD, 26), fill=CORAL, anchor='ma')
d.rectangle([368, 152, 432, 158], fill=CORAL)
tile, gap, cols = 176, 12, 4
x0 = (800 - tile * cols - gap * (cols - 1)) // 2
y0 = 188
mask = Image.new('L', (tile, tile), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile, tile], radius=18, fill=255)
for i, (name, fn) in enumerate(colors):
    im = load(os.path.join(ROOT, 'sku图', fn))
    im = crop_resize(im, (0, 0, im.width, im.height), tile, tile)
    x = x0 + (i % cols) * (tile + gap)
    y = y0 + (i // cols) * (tile + gap + 44)
    canvas.paste(im, (x, y), mask)
    d.text((x + tile // 2, y + tile + 22), name, font=F(BOLD, 24), fill=INK, anchor='mm')
lx = x0 + 3 * (tile + gap)
ly = y0 + (tile + gap + 44)
d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=18, fill=WHITE)
d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=18, outline=(255, 205, 60), width=3)
d.text((lx + tile // 2, ly + 62), '更多', font=F(BOLD, 34), fill=CORAL, anchor='mm')
d.text((lx + tile // 2, ly + 106), '颜色', font=F(BOLD, 34), fill=CORAL, anchor='mm')
d.text((lx + tile // 2, ly + 148), '进店选购', font=F(REG, 20), fill=GRAY, anchor='mm')
bottom_bar(canvas, '高腰提臀 · 侧边口袋 · 裸感面料')
save(grain(canvas, 1.6), '爆款5_多色展示.jpg')

# 备用白底图（猜你喜欢 / 活动准入）
photo = crop_resize(src29, (0, 25, 790, 1015), 623, 800)
a = np.asarray(photo).astype(np.float32)
mn = a.min(axis=2, keepdims=True)
t = np.clip((mn - 196) / (224 - 196), 0, 1)
t = t * t * (3 - 2 * t)
out = a * (1 - t) + 255.0 * t
photo = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
canvas = Image.new('RGB', (800, 800), WHITE)
canvas.paste(photo, ((800 - 623) // 2, 0))
save(canvas, '备用_白底图_猜你喜欢.jpg')

for f in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, f)
    a = np.asarray(Image.open(p))
    print(f, Image.open(p).size, round(os.path.getsize(p) / 1024, 1), 'KB', 'corner', tuple(a[3, 3]))

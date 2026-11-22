# -*- coding: utf-8 -*-
import os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = '1688_1041092037687'
OUT = '淘宝主图_黑色原模板高清'
os.makedirs(OUT, exist_ok=True)

S = 1.5
SIZE = int(800 * S)
BOLD = r'C:\Windows\Fonts\msyhbd.ttc'
REG = r'C:\Windows\Fonts\msyh.ttc'
INK = (26, 26, 26)
ROSE = (232, 70, 124)
WARM = (247, 244, 240)
WHITE = (255, 255, 255)


def P(v):
    return int(round(v * S))


def pt(p):
    return (P(p[0]), P(p[1]))


def box(b):
    return tuple(P(v) for v in b)


def F(path, size):
    return ImageFont.truetype(path, P(size))


def load(path, enhance=True):
    im = Image.open(path).convert('RGB')
    if enhance:
        im = ImageEnhance.Color(im).enhance(1.06)
        im = ImageEnhance.Contrast(im).enhance(1.03)
        im = ImageEnhance.Brightness(im).enhance(1.02)
    return im


def fit(im, crop, w, h):
    return im.crop(crop).resize((w, h), Image.LANCZOS)


def crop_square(im, crop, size):
    return fit(im, crop, size, size)


def text_sh(d, p, txt, font, fill=WHITE, anchor='la', off=2, shadow=(0, 0, 0, 110)):
    x, y = pt(p)
    d.text((x + P(off), y + P(off)), txt, font=font, fill=shadow, anchor=anchor)
    d.text((x, y), txt, font=font, fill=fill, anchor=anchor)


def pill(d, b, fill, radius=None):
    b = box(b)
    d.rounded_rectangle(b, radius=P(radius) if radius is not None else (b[3] - b[1]) // 2, fill=fill)


def dashed_ellipse(d, b, color, width=5, dash=18, gap=12):
    x0, y0, x1, y1 = box(b)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    total = 3.141592653589793 * (3 * (rx + ry) - ((3 * rx + ry) * (rx + 3 * ry)) ** 0.5)
    dw, dd, dg = P(width), P(dash), P(gap)
    n = max(1, int(total / (dd + dg)))
    for i in range(n):
        a0 = i * 2 * 3.141592653589793 / n
        a1 = a0 + (dd / total) * 2 * 3.141592653589793
        points = []
        for k in range(25):
            a = a0 + (a1 - a0) * k / 24
            points.append((cx + rx * __import__('math').cos(a), cy + ry * __import__('math').sin(a)))
        d.line(points, fill=color, width=dw, joint='curve')


def arrow(d, p1, p2, color, width=4, head=16):
    p1, p2 = pt(p1), pt(p2)
    d.line([p1, p2], fill=color, width=P(width))
    ang = __import__('math').atan2(p2[1] - p1[1], p2[0] - p1[0])
    for da in (2.705260340591211, -2.705260340591211):
        hx = p2[0] + P(head) * __import__('math').cos(ang + da)
        hy = p2[1] + P(head) * __import__('math').sin(ang + da)
        d.line([p2, (hx, hy)], fill=color, width=P(width))


def band(w, h, top, bottom):
    g = Image.new('RGBA', (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)))
    return g.resize((w, h))


def save(canvas, name):
    canvas.save(os.path.join(OUT, name), quality=95, subsampling=0)
    print(name)


black_front = load(os.path.join(ROOT, '详情页图', '详情_29.jpg'))
black_back = load(os.path.join(ROOT, '详情页图', '详情_28.jpg'))
black_fabric = load(os.path.join(ROOT, '详情页图', '详情_27.jpg'))
black_sku = load(os.path.join(ROOT, 'sku图', 'SKU_03_黑色.jpg'))


def main1():
    base = fit(black_front, (0, 240, 790, 1293), P(600), SIZE)
    canvas = Image.new('RGB', (SIZE, SIZE), WARM)
    canvas.paste(base, (0, 0))
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.rectangle(box((599, 0, 602, 800)), fill=(232, 70, 124, 60))
    x = P(634)
    d.text((x, P(92)), '高腰', font=F(BOLD, 72), fill=INK)
    d.text((x, P(180)), '提臀', font=F(BOLD, 72), fill=ROSE)
    d.text((x, P(268)), '显瘦', font=F(BOLD, 72), fill=INK)
    d.text((x, P(362)), '三分裤', font=F(BOLD, 50), fill=INK)
    d.rectangle(box((634, 450, 688, 456)), fill=ROSE)
    d.text((x, P(478)), '侧边口袋', font=F(REG, 26), fill=(90, 90, 90))
    d.text((x, P(514)), '裸感面料', font=F(REG, 26), fill=(90, 90, 90))
    d.text((x, P(550)), '高弹不勒', font=F(REG, 26), fill=(90, 90, 90))
    pill(d, (634, 636, 766, 684), ROSE)
    d.text((P(700), P(660)), '7色可选', font=F(BOLD, 25), fill=WHITE, anchor='mm')
    d.text((x, P(726)), 'HIGH WAIST', font=F(BOLD, 15), fill=(176, 168, 162))
    save(canvas, '主图1_黑色_高腰提臀_1200.jpg')


def main2():
    canvas = crop_square(black_back, (0, 1150, 790, 1940), SIZE)
    d = ImageDraw.Draw(canvas, 'RGBA')
    top = band(SIZE, P(210), (0, 0, 0, 130), (0, 0, 0, 0))
    canvas.paste(top, (0, 0), top)
    text_sh(d, (44, 34), 'M型提臀弧线', F(BOLD, 62), WHITE)
    text_sh(d, (46, 116), '蜜桃臀 穿出来', F(REG, 34), (255, 235, 242))
    d.rounded_rectangle(box((46, 164, 290, 202)), radius=P(19), fill=(255, 255, 255, 48))
    d.text(pt((58, 183)), '高弹贴合 不卷边', font=F(REG, 23), fill=WHITE, anchor='lm')
    dashed_ellipse(d, (200, 300, 620, 640), (255, 255, 255, 240), width=5, dash=20, gap=13)
    arrow(d, (688, 268), (600, 340), WHITE, width=5)
    text_sh(d, (696, 238), '提拉', F(BOLD, 32), WHITE, anchor='lm')
    d.rounded_rectangle(box((520, 712, 760, 760)), radius=P(24), fill=(255, 255, 255, 240))
    d.text(pt((640, 736)), '后腰M型走线', font=F(BOLD, 25), fill=(198, 42, 96), anchor='mm')
    save(canvas, '主图2_黑色_M型提臀_1200.jpg')


def main3():
    canvas = crop_square(black_sku, (0, 0, black_sku.width, black_sku.height), SIZE)
    d = ImageDraw.Draw(canvas, 'RGBA')
    top = band(SIZE, P(200), (0, 0, 0, 120), (0, 0, 0, 0))
    canvas.paste(top, (0, 0), top)
    text_sh(d, (44, 32), '侧边隐形口袋', F(BOLD, 60), WHITE)
    text_sh(d, (46, 112), '手机钥匙随身放 运动不累赘', F(REG, 28), (255, 236, 242))
    d.rounded_rectangle(box((36, 420, 196, 462)), radius=P(21), fill=(255, 255, 255, 60))
    d.text(pt((116, 441)), '高腰收腹', font=F(BOLD, 23), fill=WHITE, anchor='mm')
    arrow(d, (200, 441), (330, 350), WHITE, width=4)
    d.rounded_rectangle(box((598, 508, 758, 550)), radius=P(21), fill=(255, 255, 255, 60))
    d.text(pt((678, 529)), '无尴尬线', font=F(BOLD, 23), fill=WHITE, anchor='mm')
    arrow(d, (594, 529), (500, 566), WHITE, width=4)
    arrow(d, (612, 262), (452, 540), WHITE, width=5)
    d.rounded_rectangle(box((590, 218, 766, 260)), radius=P(21), fill=(255, 255, 255, 60))
    d.text(pt((678, 239)), '侧边口袋', font=F(BOLD, 23), fill=WHITE, anchor='mm')
    save(canvas, '主图3_黑色_侧边口袋_1200.jpg')


def main4():
    canvas = crop_square(black_fabric, (150, 1160, 740, 1750), SIZE)
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.rectangle(box((0, 0, 800, 150)), fill=(110, 40, 66, 255))
    top = band(SIZE, P(130), (110, 40, 66, 255), (110, 40, 66, 0))
    canvas.paste(top, (0, P(150)), top)
    text_sh(d, (44, 40), '双面裸感面料', F(BOLD, 56), WHITE, off=1)
    d.text(pt((46, 118)), '触肤即柔 如第二层肌肤', font=F(REG, 29), fill=(255, 232, 240))
    d.text(pt((680, 52)), '75%', font=F(BOLD, 42), fill=WHITE, anchor='ma')
    d.text(pt((680, 100)), '锦纶 Nylon', font=F(REG, 21), fill=(255, 232, 240), anchor='ma')
    d.line([pt((630, 136)), pt((730, 136))], fill=(255, 255, 255, 120), width=P(2))
    d.text(pt((680, 146)), '25% 氨纶 Spandex', font=F(REG, 21), fill=(255, 232, 240), anchor='ma')
    feats = ['软糯亲肤', '高弹回弹', '吸湿排汗', '轻薄透气']
    bw, gap = P(170), P(14)
    x0 = (SIZE - (bw * 4 + gap * 3)) // 2
    bottom = band(SIZE, P(130), (110, 40, 66, 0), (110, 40, 66, 190))
    canvas.paste(bottom, (0, P(670)), bottom)
    for i, t in enumerate(feats):
        x = x0 + i * (bw + gap)
        d.rounded_rectangle([x, P(706), x + bw, P(758)], radius=P(26), fill=(255, 255, 255, 60))
        d.text((x + bw // 2, P(732)), t, font=F(BOLD, 25), fill=WHITE, anchor='mm')
    save(canvas, '主图4_黑色_面料卖点_1200.jpg')


def main5():
    colors = [
        ('奶油黄', 'SKU_01_奶油黄.jpg'),
        ('石英玫瑰', 'SKU_02_石英玫瑰.jpg'),
        ('黑色', 'SKU_03_黑色.jpg'),
        ('白色', 'SKU_04_白色.jpg'),
        ('橄榄绿', 'SKU_05_橄榄绿.jpg'),
        ('浅粉', 'SKU_06_浅粉.jpg'),
        ('海军蓝', 'SKU_07_海军蓝.jpg'),
    ]
    canvas = Image.new('RGB', (SIZE, SIZE), WARM)
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.text(pt((400, 40)), '7色可选', font=F(BOLD, 60), fill=INK, anchor='ma')
    d.text(pt((400, 112)), 'COLOR OPTIONS · 总有一色适合你', font=F(REG, 24), fill=(130, 120, 116), anchor='ma')
    d.rectangle(box((376, 152, 424, 158)), fill=ROSE)
    tile, gap, cols = P(176), P(12), 4
    x0 = (SIZE - (tile * cols + gap * (cols - 1))) // 2
    y0 = P(190)
    mask = Image.new('L', (tile, tile), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile - 1, tile - 1], radius=P(18), fill=255)
    for i, (name, fn) in enumerate(colors):
        im = load(os.path.join(ROOT, 'sku图', fn))
        im = crop_square(im, (0, 0, im.width, im.height), tile)
        x = x0 + (i % cols) * (tile + gap)
        y = y0 + (i // cols) * (tile + gap + P(46))
        canvas.paste(im, (x, y), mask)
        d.text((x + tile // 2, y + tile + P(24)), name, font=F(BOLD, 24), fill=(70, 64, 62), anchor='mm')
    lx = x0 + 3 * (tile + gap)
    ly = y0 + (tile + gap + P(46))
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=P(18), fill=(255, 255, 255))
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=P(18), outline=(226, 218, 210), width=P(2))
    d.text((lx + tile // 2, ly + P(62)), '更多', font=F(BOLD, 34), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + P(106)), '颜色', font=F(BOLD, 34), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + P(148)), '进店选购', font=F(REG, 20), fill=(150, 140, 136), anchor='mm')
    pill(d, (200, 724, 600, 772), INK)
    d.text(pt((400, 748)), '高腰提臀 · 侧边口袋 · 裸感面料', font=F(BOLD, 26), fill=WHITE, anchor='mm')
    save(canvas, '主图5_黑色_多色展示_1200.jpg')


main1()
main2()
main3()
main4()
main5()
print('MAIN IMAGES DONE')

# -*- coding: utf-8 -*-
import os, math
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

ROOT = '1688_1041092037687'
OUT = '淘宝主图'
os.makedirs(OUT, exist_ok=True)

SIZE = 800
BOLD = r'C:\Windows\Fonts\msyhbd.ttc'
REG = r'C:\Windows\Fonts\msyh.ttc'
INK = (26, 26, 26)
ROSE = (232, 70, 124)
WARM = (247, 244, 240)
WHITE = (255, 255, 255)

def F(path, size):
    return ImageFont.truetype(path, size)

def load(path, enhance=True):
    im = Image.open(path).convert('RGB')
    if enhance:
        im = ImageEnhance.Color(im).enhance(1.06)
        im = ImageEnhance.Contrast(im).enhance(1.03)
        im = ImageEnhance.Brightness(im).enhance(1.02)
    return im

def crop_square(im, box, size):
    im = im.crop(box)
    w, h = im.size
    s = min(w, h)
    x = (w - s) // 2
    y = (h - s) // 2
    return im.crop((x, y, x + s, y + s)).resize((size, size), Image.LANCZOS)

def text_sh(draw, xy, txt, font, fill=WHITE, anchor='la', off=2, shadow=(0, 0, 0, 110)):
    x, y = xy
    draw.text((x + off, y + off), txt, font=font, fill=shadow, anchor=anchor)
    draw.text((x, y), txt, font=font, fill=fill, anchor=anchor)

def pill(draw, box, fill, radius=None):
    if radius is None:
        radius = (box[3] - box[1]) // 2
    draw.rounded_rectangle(box, radius=radius, fill=fill)

def dashed_ellipse(draw, bbox, color, width=5, dash=18, gap=12):
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
    total = math.pi * (3 * (rx + ry) - math.sqrt((3 * rx + ry) * (rx + 3 * ry)))
    n = max(1, int(total / (dash + gap)))
    for i in range(n):
        a0 = i * 2 * math.pi / n
        a1 = a0 + (dash / total) * 2 * math.pi
        steps = 24
        pts = []
        for k in range(steps + 1):
            a = a0 + (a1 - a0) * k / steps
            pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        draw.line(pts, fill=color, width=width, joint='curve')

def arrow(draw, p1, p2, color, width=4, head=16):
    draw.line([p1, p2], fill=color, width=width)
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    for da in (math.radians(155), math.radians(-155)):
        hx = p2[0] + head * math.cos(ang + da)
        hy = p2[1] + head * math.sin(ang + da)
        draw.line([p2, (hx, hy)], fill=color, width=width)

def band(w, h, top, bottom):
    g = Image.new('RGBA', (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(4)))
    return g.resize((w, h))


def main1():
    base = load(os.path.join(ROOT, '主图', '主图_04.jpg')).resize((600, 800), Image.LANCZOS)
    canvas = Image.new('RGB', (SIZE, SIZE), WARM)
    canvas.paste(base, (0, 0))
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.rectangle([599, 0, 602, 800], fill=(232, 70, 124, 60))
    x = 634
    d.text((x, 92), '高腰', font=F(BOLD, 72), fill=INK)
    d.text((x, 180), '提臀', font=F(BOLD, 72), fill=ROSE)
    d.text((x, 268), '显瘦', font=F(BOLD, 72), fill=INK)
    d.text((x, 362), '三分裤', font=F(BOLD, 50), fill=INK)
    d.rectangle([x, 450, x + 54, 456], fill=ROSE)
    d.text((x, 478), '侧边口袋', font=F(REG, 26), fill=(90, 90, 90))
    d.text((x, 514), '裸感面料', font=F(REG, 26), fill=(90, 90, 90))
    d.text((x, 550), '高弹不勒', font=F(REG, 26), fill=(90, 90, 90))
    pill(d, [x, 636, x + 132, 684], ROSE)
    d.text((x + 66, 660), '7色可选', font=F(BOLD, 25), fill=WHITE, anchor='mm')
    d.text((x, 726), 'HIGH WAIST', font=F(BOLD, 15), fill=(176, 168, 162))
    canvas.save(os.path.join(OUT, '主图1_首图_高腰提臀.jpg'), quality=92)
    print('1 ok')


def main2():
    im = load(os.path.join(ROOT, '主图', '主图_02.jpg'))
    sq = crop_square(im, (70, 80, 555, 565), SIZE)
    canvas = sq.copy()
    d = ImageDraw.Draw(canvas, 'RGBA')
    top = band(800, 210, (0, 0, 0, 130), (0, 0, 0, 0))
    canvas.paste(top, (0, 0), top)
    text_sh(d, (44, 34), 'M型提臀弧线', F(BOLD, 62), WHITE)
    text_sh(d, (46, 116), '蜜桃臀 穿出来', F(REG, 34), (255, 235, 242))
    d.rounded_rectangle([46, 164, 290, 202], radius=19, fill=(255, 255, 255, 48))
    d.text((58, 183), '高弹贴合 不卷边', font=F(REG, 23), fill=WHITE, anchor='lm')
    dashed_ellipse(d, (200, 300, 620, 640), (255, 255, 255, 240), width=5, dash=20, gap=13)
    arrow(d, (688, 268), (600, 340), WHITE, width=5)
    text_sh(d, (696, 238), '提拉', F(BOLD, 32), WHITE, anchor='lm')
    d.rounded_rectangle([520, 712, 760, 760], radius=24, fill=(255, 255, 255, 240))
    d.text((640, 736), '后腰M型走线', font=F(BOLD, 25), fill=(198, 42, 96), anchor='mm')
    canvas.save(os.path.join(OUT, '主图2_提臀卖点.jpg'), quality=92)
    print('2 ok')


def main3():
    im = load(os.path.join(ROOT, '主图', '主图_01.jpg'))
    sq = crop_square(im, (0, 150, 770, 920), SIZE)
    canvas = sq.copy()
    d = ImageDraw.Draw(canvas, 'RGBA')
    top = band(800, 200, (0, 0, 0, 120), (0, 0, 0, 0))
    canvas.paste(top, (0, 0), top)
    text_sh(d, (44, 32), '侧边隐形口袋', F(BOLD, 60), WHITE)
    text_sh(d, (46, 112), '手机钥匙随身放 运动不累赘', F(REG, 28), (255, 236, 242))
    d.rounded_rectangle([36, 420, 196, 462], radius=21, fill=(255, 255, 255, 60))
    d.text((116, 441), '高腰收腹', font=F(BOLD, 23), fill=WHITE, anchor='mm')
    arrow(d, (200, 441), (330, 350), WHITE, width=4)
    d.rounded_rectangle([598, 508, 758, 550], radius=21, fill=(255, 255, 255, 60))
    d.text((678, 529), '无尴尬线', font=F(BOLD, 23), fill=WHITE, anchor='mm')
    arrow(d, (594, 529), (500, 566), WHITE, width=4)
    arrow(d, (612, 262), (452, 540), WHITE, width=5)
    d.rounded_rectangle([590, 218, 766, 260], radius=21, fill=(255, 255, 255, 60))
    d.text((678, 239), '侧边口袋', font=F(BOLD, 23), fill=WHITE, anchor='mm')
    canvas.save(os.path.join(OUT, '主图3_口袋版型.jpg'), quality=92)
    print('3 ok')


def main4():
    im = load(os.path.join(ROOT, '主图', '主图_03.jpg'))
    sq = crop_square(im, (130, 300, 770, 930), SIZE)
    canvas = sq.copy()
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.rectangle([0, 0, 800, 150], fill=(110, 40, 66, 255))
    top = band(800, 130, (110, 40, 66, 255), (110, 40, 66, 0))
    canvas.paste(top, (0, 150), top)
    text_sh(d, (44, 40), '双面裸感面料', F(BOLD, 56), WHITE, off=1)
    d.text((46, 118), '触肤即柔 如第二层肌肤', font=F(REG, 29), fill=(255, 232, 240))
    d.text((680, 52), '75%', font=F(BOLD, 42), fill=WHITE, anchor='ma')
    d.text((680, 100), '锦纶 Nylon', font=F(REG, 21), fill=(255, 232, 240), anchor='ma')
    d.line([630, 136, 730, 136], fill=(255, 255, 255, 120), width=2)
    d.text((680, 146), '25% 氨纶 Spandex', font=F(REG, 21), fill=(255, 232, 240), anchor='ma')
    feats = ['软糯亲肤', '高弹回弹', '吸湿排汗', '轻薄透气']
    bw, gap = 170, 14
    x0 = (800 - (bw * 4 + gap * 3)) // 2
    bottom = band(800, 130, (110, 40, 66, 0), (110, 40, 66, 190))
    canvas.paste(bottom, (0, 670), bottom)
    for i, t in enumerate(feats):
        x = x0 + i * (bw + gap)
        d.rounded_rectangle([x, 706, x + bw, 758], radius=26, fill=(255, 255, 255, 60))
        d.text((x + bw // 2, 732), t, font=F(BOLD, 25), fill=WHITE, anchor='mm')
    canvas.save(os.path.join(OUT, '主图4_面料卖点.jpg'), quality=92)
    print('4 ok')


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
    d.text((400, 40), '7色可选', font=F(BOLD, 60), fill=INK, anchor='ma')
    d.text((400, 112), 'COLOR OPTIONS · 总有一色适合你', font=F(REG, 24), fill=(130, 120, 116), anchor='ma')
    d.rectangle([376, 152, 424, 158], fill=ROSE)
    tile, gap, cols = 176, 12, 4
    x0 = (800 - (tile * cols + gap * (cols - 1))) // 2
    y0 = 190
    mask = Image.new('L', (tile, tile), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tile, tile], radius=18, fill=255)
    for i, (name, fn) in enumerate(colors):
        im = load(os.path.join(ROOT, 'sku图', fn))
        im = crop_square(im, (0, 0, im.width, im.height), tile)
        x = x0 + (i % cols) * (tile + gap)
        y = y0 + (i // cols) * (tile + gap + 46)
        canvas.paste(im, (x, y), mask)
        d.text((x + tile // 2, y + tile + 24), name, font=F(BOLD, 24), fill=(70, 64, 62), anchor='mm')
    lx = x0 + 3 * (tile + gap)
    ly = y0 + (tile + gap + 46)
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=18, fill=(255, 255, 255))
    d.rounded_rectangle([lx, ly, lx + tile, ly + tile], radius=18, outline=(226, 218, 210), width=2)
    d.text((lx + tile // 2, ly + 62), '更多', font=F(BOLD, 34), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + 106), '颜色', font=F(BOLD, 34), fill=ROSE, anchor='mm')
    d.text((lx + tile // 2, ly + 148), '进店选购', font=F(REG, 20), fill=(150, 140, 136), anchor='mm')
    pill(d, [200, 724, 600, 772], INK)
    d.text((400, 748), '高腰提臀 · 侧边口袋 · 裸感面料', font=F(BOLD, 26), fill=WHITE, anchor='mm')
    canvas.save(os.path.join(OUT, '主图5_多色展示.jpg'), quality=92)
    print('5 ok')


main1(); main2(); main3(); main4(); main5()
print('ALL DONE')

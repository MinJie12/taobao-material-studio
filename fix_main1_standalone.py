# -*- coding: utf-8 -*-
import os
from PIL import Image, ImageOps, ImageEnhance

ROOT = '1688_1041092037687'
OUT = '淘宝主图_黑色原模板高清'
WARM = (247, 244, 240)


def load(path):
    im = Image.open(path).convert('RGB')
    im = ImageEnhance.Color(im).enhance(1.06)
    im = ImageEnhance.Contrast(im).enhance(1.03)
    im = ImageEnhance.Brightness(im).enhance(1.02)
    return im


def contain_canvas(im, box, bg):
    canvas = Image.new('RGB', (1200, 1200), bg)
    fit = ImageOps.contain(im, box, Image.LANCZOS)
    fit = ImageEnhance.Sharpness(fit).enhance(1.15)
    x = (1200 - fit.width) // 2
    y = (1200 - fit.height) // 2
    canvas.paste(fit, (x, y))
    return canvas


other = load(os.path.join(ROOT, '主图', '主图_04.jpg'))
standalone = contain_canvas(other, (900, 1200), WARM)
standalone.save(os.path.join(OUT, '主图1_单独模特_其他色_1200.jpg'), quality=95, subsampling=0)
standalone.save(os.path.join(OUT, '主图1_黑色_高腰提臀_1200.jpg'), quality=95, subsampling=0)
print('other standalone ok')

black_candidate = load(os.path.join(ROOT, '详情页图', '详情_28.jpg')).crop((0, 300, 790, 1900))
candidate = contain_canvas(black_candidate, (700, 1200), WARM)
candidate.save(os.path.join(OUT, '主图1_单独模特_黑色候选_1200.jpg'), quality=95, subsampling=0)
print('black candidate ok')

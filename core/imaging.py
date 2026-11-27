# -*- coding: utf-8 -*-
"""图片处理、文字排版与质量校验。"""
from __future__ import annotations

import io
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from . import config

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9
    RESAMPLE = Image.LANCZOS

_FALLBACK_FONTS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def font_path(bold: bool = False) -> str:
    fonts = config.load_settings().get("fonts", {})
    path = fonts.get("bold" if bold else "regular", "")
    if path and Path(path).is_file():
        return str(path)
    for fallback in _FALLBACK_FONTS:
        if Path(fallback).is_file():
            return fallback
    return ""


@lru_cache(maxsize=128)
def get_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    size = max(6, int(size))
    candidates = [path] if path else []
    candidates.extend(_FALLBACK_FONTS)
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def hex_to_rgb(value, default=(0, 0, 0)) -> tuple[int, int, int]:
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(max(0, min(255, int(v))) for v in value[:3])
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return default
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def rgba(value, alpha: int = 255) -> tuple[int, int, int, int]:
    r, g, b = hex_to_rgb(value)
    return r, g, b, max(0, min(255, int(alpha)))


def mix_color(a, b, ratio: float = 0.5) -> tuple[int, int, int]:
    ca, cb = hex_to_rgb(a), hex_to_rgb(b)
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(ca[i] + (cb[i] - ca[i]) * ratio) for i in range(3))


def load_image(path) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def remove_edge_background(image: Image.Image, tolerance: int = 36) -> tuple[Image.Image, list[int]]:
    rgba = np.array(image.convert("RGBA"))
    rgb = rgba[:, :, :3].astype(np.float32)
    border = np.concatenate([
        rgba[:3].reshape(-1, 4), rgba[-3:].reshape(-1, 4),
        rgba[:, :3].reshape(-1, 4), rgba[:, -3:].reshape(-1, 4),
    ])
    opaque = border[border[:, 3] == 255]
    if len(opaque) < len(border) / 2:
        return Image.fromarray(rgba, "RGBA"), []
    background = np.median(opaque[:, :3], axis=0)
    distance = np.linalg.norm(rgb - background, axis=2)
    alpha = np.clip((distance - tolerance) / (tolerance * 0.8), 0, 1)
    rgba[:, :, 3] = (rgba[:, :, 3] * alpha).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA"), [int(value) for value in background]


def fit_cover(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    width, height = size
    iw, ih = im.size
    if iw <= 0 or ih <= 0:
        return Image.new("RGB", size, (255, 255, 255))
    scale = max(width / iw, height / ih)
    new_size = (max(width, int(math.ceil(iw * scale))), max(height, int(math.ceil(ih * scale))))
    resized = im.resize(new_size, RESAMPLE)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def fit_contain(im: Image.Image, size: tuple[int, int], bg=(255, 255, 255), padding: int = 0) -> Image.Image:
    width, height = size
    inner_w = max(1, width - padding * 2)
    inner_h = max(1, height - padding * 2)
    copy = im.copy()
    copy.thumbnail((inner_w, inner_h), RESAMPLE)
    canvas = Image.new("RGB", size, hex_to_rgb(bg) if not isinstance(bg, tuple) else bg[:3])
    canvas.paste(copy, ((width - copy.width) // 2, (height - copy.height) // 2))
    return canvas


def _clamp(value, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def _bg_rgb(bg) -> tuple[int, int, int]:
    if isinstance(bg, (tuple, list)) and len(bg) >= 3:
        return tuple(max(0, min(255, int(value))) for value in bg[:3])
    return hex_to_rgb(bg)


def fit_cover_focus(
    im: Image.Image,
    size: tuple[int, int],
    zoom: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    bg=(255, 255, 255),
) -> Image.Image:
    """铺满画框，并支持产品缩放与水平 / 垂直移动。

    offset_x / offset_y 取值 -1 到 1：-1 表示贴左 / 贴上，0 居中，1 表示贴右 / 贴下。
    缩放小于 1 时会用背景色补齐空白，方便操作者把产品放小。
    """
    width, height = size
    iw, ih = im.size
    if iw <= 0 or ih <= 0:
        return Image.new("RGB", size, _bg_rgb(bg))
    zoom = _clamp(zoom, 0.5, 3.0)
    offset_x = _clamp(offset_x, -1.0, 1.0)
    offset_y = _clamp(offset_y, -1.0, 1.0)
    scale = max(width / iw, height / ih) * zoom
    new_size = (max(1, int(math.ceil(iw * scale))), max(1, int(math.ceil(ih * scale))))
    resized = im.resize(new_size, RESAMPLE)
    canvas = Image.new("RGB", (width, height), _bg_rgb(bg))
    if resized.width >= width and resized.height >= height:
        free_x = resized.width - width
        free_y = resized.height - height
        left = int(round(free_x * (0.5 + offset_x * 0.5)))
        top = int(round(free_y * (0.5 + offset_y * 0.5)))
        return resized.crop((left, top, left + width, top + height))
    if resized.width <= width:
        x = int(round((width - resized.width) * (0.5 + offset_x * 0.5)))
    else:
        x = -int(round((resized.width - width) * (0.5 + offset_x * 0.5)))
    if resized.height <= height:
        y = int(round((height - resized.height) * (0.5 + offset_y * 0.5)))
    else:
        y = -int(round((resized.height - height) * (0.5 + offset_y * 0.5)))
    canvas.paste(resized, (x, y))
    return canvas


def fit_contain_focus(
    im: Image.Image,
    size: tuple[int, int],
    bg=(255, 255, 255),
    padding: int = 0,
    zoom: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> Image.Image:
    """完整显示产品，同时支持在留白范围内移动和缩放。"""
    width, height = size
    inner_w = max(1, width - padding * 2)
    inner_h = max(1, height - padding * 2)
    copy = im.copy()
    copy.thumbnail((inner_w, inner_h), RESAMPLE)
    zoom = _clamp(zoom, 0.5, 3.0)
    if zoom != 1.0:
        copy = copy.resize(
            (max(1, int(round(copy.width * zoom))), max(1, int(round(copy.height * zoom)))),
            RESAMPLE,
        )
    canvas = Image.new("RGB", size, _bg_rgb(bg))
    free_x = width - copy.width
    free_y = height - copy.height
    if free_x >= 0:
        x = int(round(free_x / 2 + _clamp(offset_x, -1.0, 1.0) * free_x / 2))
    else:
        x = -int(round(-free_x * (0.5 + _clamp(offset_x, -1.0, 1.0) * 0.5)))
    if free_y >= 0:
        y = int(round(free_y / 2 + _clamp(offset_y, -1.0, 1.0) * free_y / 2))
    else:
        y = -int(round(-free_y * (0.5 + _clamp(offset_y, -1.0, 1.0) * 0.5)))
    canvas.paste(copy, (x, y))
    return canvas


def crop_to_ratio(im: Image.Image, ratio: float, focus: tuple[float, float] = (0.5, 0.5)) -> Image.Image:
    iw, ih = im.size
    if iw <= 0 or ih <= 0:
        return im
    current = iw / ih
    if current > ratio:
        new_w = max(1, int(round(ih * ratio)))
        x = int(round((iw - new_w) * max(0.0, min(1.0, focus[0]))))
        box = (x, 0, x + new_w, ih)
    else:
        new_h = max(1, int(round(iw / ratio)))
        y = int(round((ih - new_h) * max(0.0, min(1.0, focus[1]))))
        box = (0, y, iw, y + new_h)
    return im.crop(box)


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=max(0, int(radius)), fill=255
    )
    return mask


def paste_rounded(canvas: Image.Image, im: Image.Image, box: tuple[int, int], radius: int) -> None:
    mask = rounded_mask(im.size, radius)
    canvas.paste(im, box, mask)


def vertical_gradient(width: int, height: int, top, bottom) -> Image.Image:
    top = tuple(int(v) for v in top)
    bottom = tuple(int(v) for v in bottom)
    if len(top) == 3:
        top = top + (255,)
    if len(bottom) == 3:
        bottom = bottom + (255,)
    arr = np.zeros((height, 1, 4), dtype=np.float32)
    for index in range(4):
        arr[:, 0, index] = np.linspace(top[index], bottom[index], max(1, height))
    arr = np.repeat(arr, max(1, width), axis=1)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


def add_gradient(canvas: Image.Image, box: tuple[int, int, int, int], top, bottom) -> None:
    x0, y0, x1, y1 = box
    width, height = max(1, x1 - x0), max(1, y1 - y0)
    gradient = vertical_gradient(width, height, top, bottom)
    if canvas.mode == "RGBA":
        canvas.alpha_composite(gradient, (x0, y0))
    else:
        canvas.paste(gradient, (x0, y0), gradient)


def text_metrics(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if not text:
        return 0, 0
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1])


def _tokenize_for_wrap(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9%+._\-]+|[\u4e00-\u9fff]|[^\s]", text)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    max_width = max(10, int(max_width))
    lines: list[str] = []
    for paragraph in str(text or "").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for token in _tokenize_for_wrap(paragraph):
            if token == " ":
                token = " "
            candidate = current + token
            width, _ = text_metrics(draw, candidate, font)
            if width <= max_width or not current:
                if token == " " and not current:
                    continue
                current = candidate
            else:
                lines.append(current.rstrip())
                current = "" if token == " " else token
        if current:
            lines.append(current.rstrip())
    return lines or [""]


def _ellipsize(draw: ImageDraw.ImageDraw, line: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if text_metrics(draw, line, font)[0] <= max_width:
        return line
    suffix = "…"
    while line and text_metrics(draw, line + suffix, font)[0] > max_width:
        line = line[:-1]
    return (line + suffix) if line else suffix


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    bold: bool,
    max_width: int,
    max_height: int,
    max_size: int,
    min_size: int,
    max_lines: int,
    line_spacing: float = 1.26,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    path = font_path(bold)
    chosen_font = get_font(path, min_size)
    chosen_lines = wrap_text(draw, text, chosen_font, max_width)
    chosen_line_height = int(min_size * line_spacing)
    for size in range(int(max_size), int(min_size) - 1, -2):
        font = get_font(path, size)
        lines = wrap_text(draw, text, font, max_width)
        line_height = int(size * line_spacing)
        if len(lines) <= max_lines and len(lines) * line_height <= max_height:
            return font, lines, line_height
    chosen_font = get_font(path, min_size)
    chosen_lines = wrap_text(draw, text, chosen_font, max_width)
    if len(chosen_lines) > max_lines:
        chosen_lines = chosen_lines[:max_lines]
        chosen_lines[-1] = _ellipsize(draw, chosen_lines[-1], chosen_font, max_width)
    chosen_line_height = int(min_size * line_spacing)
    return chosen_font, chosen_lines, chosen_line_height


def draw_text_lines(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    fill,
    line_height: int,
    align: str = "left",
    shadow: bool = False,
    shadow_alpha: int = 110,
) -> int:
    x, y = xy
    fill = tuple(fill) if isinstance(fill, (tuple, list)) else hex_to_rgb(fill)
    for line in lines:
        width, _ = text_metrics(draw, line, font)
        line_x = x
        if align == "center":
            line_x = x - width // 2
        elif align == "right":
            line_x = x - width
        if shadow:
            draw.text((line_x + 2, y + 2), line, font=font, fill=(0, 0, 0, shadow_alpha))
        draw.text((line_x, y), line, font=font, fill=fill)
        y += line_height
    return y


def draw_pill(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill,
    text: str = "",
    font: ImageFont.FreeTypeFont | None = None,
    text_fill=(255, 255, 255),
    radius: int | None = None,
    outline=None,
    outline_width: int = 2,
) -> None:
    x0, y0, x1, y1 = box
    if radius is None:
        radius = max(1, (y1 - y0) // 2)
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill,
        outline=outline,
        width=outline_width if outline else 1,
    )
    if text and font is not None:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = x0 + (x1 - x0 - tw) // 2 - bbox[0]
        ty = y0 + (y1 - y0 - th) // 2 - bbox[1]
        draw.text((tx, ty), text, font=font, fill=text_fill)


def draw_dashed_ellipse(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[float, float, float, float],
    color,
    width: int = 5,
    dash: int = 18,
    gap: int = 12,
) -> None:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = max(1, (x1 - x0) / 2), max(1, (y1 - y0) / 2)
    total = math.pi * (3 * (rx + ry) - math.sqrt(max(0, (3 * rx + ry) * (rx + 3 * ry))))
    count = max(1, int(total / max(1, dash + gap)))
    for index in range(count):
        a0 = index * 2 * math.pi / count
        a1 = a0 + (dash / max(1, total)) * 2 * math.pi
        points = []
        for step in range(17):
            angle = a0 + (a1 - a0) * step / 16
            points.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle)))
        draw.line(points, fill=color, width=width, joint="curve")


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    p1: tuple[float, float],
    p2: tuple[float, float],
    color,
    width: int = 4,
    head: int = 16,
) -> None:
    draw.line([p1, p2], fill=color, width=width)
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    for delta in (math.radians(155), math.radians(-155)):
        hx = p2[0] + head * math.cos(angle + delta)
        hy = p2[1] + head * math.sin(angle + delta)
        draw.line([p2, (hx, hy)], fill=color, width=width)


def whiten_background(im: Image.Image, lo: int = 196, hi: int = 230) -> Image.Image:
    arr = np.asarray(im.convert("RGB")).astype(np.float32)
    minimum = arr.min(axis=2, keepdims=True)
    t = np.clip((minimum - lo) / max(1, hi - lo), 0, 1)
    t = t * t * (3 - 2 * t)
    out = arr * (1 - t) + 255.0 * t
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def enhance(
    im: Image.Image,
    color: float = 1.04,
    contrast: float = 1.03,
    brightness: float = 1.01,
    sharpness: float = 1.0,
) -> Image.Image:
    if color != 1.0:
        im = ImageEnhance.Color(im).enhance(color)
    if contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(contrast)
    if brightness != 1.0:
        im = ImageEnhance.Brightness(im).enhance(brightness)
    if sharpness != 1.0:
        im = ImageEnhance.Sharpness(im).enhance(sharpness)
    return im


def load_detail_image(path) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        alpha = image.convert("RGBA").getchannel("A") if (
            "A" in image.getbands() or "transparency" in image.info
        ) else None
        profile = image.info.get("icc_profile")
        if profile:
            try:
                image = ImageCms.profileToProfile(
                    image if image.mode in ("RGB", "CMYK", "L", "LAB") else image.convert("RGB"),
                    io.BytesIO(profile), ImageCms.createProfile("sRGB"), outputMode="RGB",
                )
            except (ImageCms.PyCMSError, OSError, ValueError):
                image = image.convert("RGB")
        else:
            image = image.convert("RGB")
        if alpha is not None:
            image = Image.composite(image, Image.new("RGB", image.size, "white"), alpha)
        return image


def beautify_detail(image: Image.Image, *, upscaled: bool = False) -> Image.Image:
    # Work on luminance so sharpening doesn't accentuate colored noise and JPEG fringes.
    light = image.convert("L")
    histogram = light.histogram()
    shadow_share = sum(histogram[:64]) / (image.width * image.height)
    strength = min(0.2, max(0.0, shadow_share - 0.18) * 0.4)
    curve = [round(value + strength * value * (1 - value / 255) ** 2) for value in range(256)]
    adjusted = light.point(curve).filter(ImageFilter.UnsharpMask(
        radius=1.25 if upscaled else 0.95, percent=72 if upscaled else 48, threshold=4,
    ))
    delta = np.asarray(adjusted, dtype=np.int16) - np.asarray(light, dtype=np.int16)
    rgb = np.asarray(image, dtype=np.int16)
    return Image.fromarray(np.clip(rgb + delta[:, :, None], 0, 255).astype(np.uint8))


def detail_segment_ranges(image: Image.Image, max_height: int) -> list[tuple[int, int]]:
    height = image.height
    count = (height + max_height - 1) // max_height
    if count == 1:
        return [(0, height)]
    sample = image.convert("L").resize((min(96, image.width), height), Image.Resampling.BOX)
    pixels = np.asarray(sample, dtype=np.float32)
    activity = np.abs(np.diff(pixels, axis=0)).mean(axis=1)
    activity = np.convolve(activity, np.ones(5) / 5, mode="same")
    window = min(70, max_height // 12)
    cuts = [0]
    for remaining in range(count - 1, 0, -1):
        start = cuts[-1]
        ideal = start + (height - start) // (remaining + 1)
        low = max(start + 1, height - remaining * max_height, ideal - window)
        high = min(start + max_height, height - remaining, ideal + window)
        cut = min(range(low, high + 1), key=lambda row: activity[row - 1] + 0.08 * abs(row - ideal))
        cuts.append(cut)
    return list(zip(cuts, cuts[1:] + [height]))


def save_jpeg(
    im: Image.Image,
    path,
    target_bytes: int | None = None,
    max_bytes: int | None = None,
    *,
    subsampling: int = 2,
    preferred_quality: int | None = None,
) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    im = im.convert("RGB")
    best_data = b""
    best_quality = 90
    qualities = list(range(94, 49, -3))
    if max_bytes and not target_bytes:
        target_bytes = max_bytes
    for quality in qualities:
        buffer = io.BytesIO()
        im.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True, subsampling=subsampling)
        data = buffer.getvalue()
        best_data, best_quality = data, quality
        if target_bytes:
            if len(data) <= target_bytes:
                break
            if preferred_quality is not None and quality <= preferred_quality and (not max_bytes or len(data) <= max_bytes):
                break
        elif max_bytes and len(data) <= max_bytes:
            break
    if max_bytes and len(best_data) > max_bytes:
        for quality in range(48, 29, -4):
            buffer = io.BytesIO()
            im.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True, subsampling=subsampling)
            if len(buffer.getvalue()) < len(best_data):
                best_data, best_quality = buffer.getvalue(), quality
            if len(best_data) <= max_bytes:
                break
    with open(path, "wb") as f:
        f.write(best_data)
    return {
        "bytes": len(best_data),
        "quality": best_quality,
        "width": im.width,
        "height": im.height,
        "within_max": (len(best_data) <= max_bytes) if max_bytes else True,
        "within_target": (len(best_data) <= target_bytes) if target_bytes else True,
    }


def validate_output(path, spec: dict, kind: str = "") -> list[str]:
    path = Path(path)
    issues: list[str] = []
    if not path.is_file():
        return ["文件不存在"]
    if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        issues.append("格式不是 JPG/PNG/WEBP")
    try:
        with Image.open(path) as im:
            width, height = im.size
            rgb = im.convert("RGB")
    except Exception as exc:
        return [f"图片无法读取: {exc}"]
    size_bytes = path.stat().st_size
    expected_w = int(spec.get("width", 0) or 0)
    expected_h = int(spec.get("height", 0) or 0)
    max_height = int(spec.get("max_height", 0) or 0)
    if expected_w and width != expected_w:
        issues.append(f"宽度应为 {expected_w}px，实际 {width}px")
    if expected_h and height != expected_h:
        issues.append(f"高度应为 {expected_h}px，实际 {height}px")
    if kind == "detail":
        if expected_w and width != expected_w:
            pass
        if max_height and height > max_height:
            issues.append(f"高度超过分段上限 {max_height}px")
    max_bytes = int(spec.get("max_bytes", 0) or 0)
    if max_bytes and size_bytes > max_bytes:
        issues.append(f"文件超过 {max_bytes // 1024}KB")
    if kind in ("white", "white_mobile"):
        pixels = rgb.load()
        corners = [
            pixels[2, 2],
            pixels[width - 3, 2],
            pixels[2, height - 3],
            pixels[width - 3, height - 3],
        ]
        if any(min(c) < 250 for c in corners):
            issues.append("白底图四角不是纯白")
    return issues


def dominant_colors(im: Image.Image, n: int = 5, center_crop: float = 0.64) -> list[tuple[tuple[int, int, int], float]]:
    im = im.convert("RGB")
    width, height = im.size
    cw = max(1, int(width * center_crop))
    ch = max(1, int(height * center_crop))
    left = (width - cw) // 2
    top = (height - ch) // 2
    sample = im.crop((left, top, left + cw, top + ch)).resize((100, 100), RESAMPLE)
    quantized = sample.quantize(colors=max(2, int(n)), method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    colors = quantized.getcolors() or []
    total = sum(count for count, _ in colors) or 1
    result = []
    for count, index in sorted(colors, reverse=True):
        rgb = tuple(palette[index * 3 : index * 3 + 3])
        if len(rgb) != 3:
            continue
        result.append((rgb, count / total))
    return result


def nearest_color_name(rgb: tuple[int, int, int], palette: dict[str, list[int]]) -> str:
    best_name = ""
    best_distance = float("inf")
    for name, values in palette.items():
        if not isinstance(values, (list, tuple)) or len(values) < 3:
            continue
        distance = sum((int(rgb[i]) - int(values[i])) ** 2 for i in range(3))
        if distance < best_distance:
            best_distance = distance
            best_name = name
    return best_name


def analyze_image_colors(path, palette: dict[str, list[int]]) -> list[dict]:
    try:
        im = load_image(path)
    except Exception:
        return []
    result = []
    seen = set()
    for rgb, share in dominant_colors(im, n=6):
        name = nearest_color_name(rgb, palette)
        if not name or name in seen:
            continue
        if name == "白色" and share > 0.35:
            continue
        if name in ("灰色", "浅灰") and share > 0.28:
            continue
        if share < 0.06:
            continue
        seen.add(name)
        result.append({"name": name, "share": round(float(share), 3), "rgb": list(rgb)})
        if len(result) >= 4:
            break
    return result


def border_lightness(im: Image.Image) -> tuple[bool, float]:
    im = im.convert("RGB")
    width, height = im.size
    step_x = max(1, width // 24)
    step_y = max(1, height // 24)
    values = []
    for x in range(0, width, step_x):
        for y in (0, 1, height - 2, height - 1):
            values.append(min(im.getpixel((x, y))))
    for y in range(0, height, step_y):
        for x in (0, 1, width - 2, width - 1):
            values.append(min(im.getpixel((x, y))))
    average = sum(values) / max(1, len(values))
    return average >= 215, average


def thumbnail(src, dest, width: int = 360) -> Path:
    src, dest = Path(src), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im = load_image(src)
    ratio = width / max(1, im.width)
    target = (max(1, width), max(1, int(im.height * ratio)))
    im = im.resize(target, RESAMPLE)
    im.save(dest, "JPEG", quality=82, optimize=True)
    return dest

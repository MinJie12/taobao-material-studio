# -*- coding: utf-8 -*-
"""主图 / 详情 / SKU / 白底图模板渲染。"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from . import config, imaging, keywords, main_design, storage

SLOT_ROLES = {
    "1": "首图 · 吸引点击",
    "2": "核心卖点",
    "3": "穿着场景",
    "4": "细节 / 面料",
    "5": "颜色规格 / 白底",
}

DEFAULT_TEMPLATES = {
    "1": "split",
    "2": "overlay",
    "3": "annotate",
    "4": "band",
    "5": "grid",
}


def _templates_config() -> dict:
    return config.load_templates()


def template_list() -> list[dict]:
    data = _templates_config()
    return list(data.get("main", []) or [])


def template_by_id(template_id: str) -> dict:
    for item in template_list():
        if item.get("id") == template_id:
            return item
    return {}


def _raw_path(task_id: str, rel: str) -> Path:
    path = (config.TASKS_DIR / task_id / str(rel)).resolve()
    task_root = (config.TASKS_DIR / task_id).resolve()
    if task_root not in path.parents:
        raise ValueError("非法素材路径")
    if not path.is_file():
        raise FileNotFoundError(f"素材不存在: {rel}")
    return path


def _load_photo(task_id: str, rel: str) -> Image.Image:
    return imaging.enhance(imaging.load_image(_raw_path(task_id, rel)))


def _photo_for(ctx: dict, size: tuple[int, int], mode: str = "cover", bg=(255, 255, 255)) -> Image.Image:
    photo = ctx["photo"]
    zoom = ctx.get("photo_zoom", 1)
    offset_x = ctx.get("photo_x", 0)
    offset_y = ctx.get("photo_y", 0)
    if mode == "whiten":
        photo = imaging.whiten_background(photo)
        mode = "contain"
    if mode == "contain":
        return imaging.fit_contain_focus(
            photo, size, bg=bg, zoom=zoom, offset_x=offset_x, offset_y=offset_y,
        )
    return imaging.fit_cover_focus(
        photo, size, zoom=zoom, offset_x=offset_x, offset_y=offset_y, bg=bg,
    )


def _draw(canvas: Image.Image) -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(canvas, "RGBA")


def _template_surface(ctx: dict, bg) -> Image.Image:
    if "layers" in ctx:
        return Image.new("RGBA", ctx["size"])
    return Image.new("RGB", ctx["size"], bg)


def _place_product(ctx: dict, canvas: Image.Image, photo: Image.Image, x=0, y=0, *, name="商品图", mask=None) -> None:
    if "layers" in ctx:
        if mask is not None:
            photo = photo.convert("RGBA")
            photo.putalpha(mask)
        ctx["layers"].append((name, photo, x, y, False))
    else:
        canvas.paste(photo, (x, y), mask)


def _element_surface(ctx: dict, draw, name: str):
    if "layers" not in ctx:
        return draw
    layer = Image.new("RGBA", ctx["size"])
    ctx["elements"].append((name, layer))
    return _draw(layer)


def _headline(ctx: dict, draw, xy, lines, font, fill, line_height, **options):
    label = ctx["headline"] or "主标题"
    return imaging.draw_text_lines(
        _element_surface(ctx, draw, label), xy, lines, font, fill, line_height, **options,
    )


def main_composition(template: str, ctx: dict) -> tuple[Image.Image, list]:
    ctx = {**ctx, "layers": [], "elements": []}
    decorations = RENDERERS[template](ctx)
    canvas = Image.new("RGBA", ctx["size"], (255, 255, 255) if template == "white" else ctx["bg"])
    overlays = [("模板装饰", decorations, False), *((name, image, False) for name, image in ctx["elements"])]
    layers = ctx["layers"]
    for name, image, locked in overlays:
        bounds = image.getbbox()
        if bounds:
            layers.append((name, image.crop(bounds), bounds[0], bounds[1], locked))
    for _, image, x, y, _ in layers:
        canvas.alpha_composite(image.convert("RGBA"), (x, y))
    return canvas.convert("RGB"), layers


def _is_mobile(size: tuple[int, int]) -> bool:
    return size[1] > size[0] * 1.05


def _body_color(ctx: dict):
    return imaging.mix_color(ctx["text_color"], ctx["bg"], 0.48)


def _draw_bullets(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    bullets: list[str],
    size: int,
    color,
    accent,
    max_items: int = 3,
    max_lines: int = 1,
    gap: int = 8,
) -> int:
    font = imaging.get_font(imaging.font_path(False), size)
    dot = max(3, size // 6)
    for item in (bullets or [])[:max_items]:
        lines = imaging.wrap_text(draw, str(item), font, max(20, width - size))
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = imaging._ellipsize(draw, lines[-1], font, max(20, width - size))
        draw.ellipse([x, y + int(size * 0.30), x + dot * 2, y + int(size * 0.30) + dot * 2], fill=accent)
        for line in lines:
            draw.text((x + size, y), line, font=font, fill=color)
            y += int(size * 1.28)
        y += gap
    return y


def _draw_footer(draw: ImageDraw.ImageDraw, size: tuple[int, int], text: str, accent, color) -> None:
    if not text:
        return
    width, height = size
    font = imaging.get_font(imaging.font_path(False), max(12, int(width * 0.0175)))
    x = int(width * 0.05)
    y = height - int(height * 0.045) - max(12, int(width * 0.0175))
    draw.rectangle([x, y + 2, x + 8, y + 10], fill=accent)
    draw.text((x + 18, y), str(text), font=font, fill=color)


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    size: tuple[int, int],
    text: str,
    accent,
    x: int | None = None,
    y: int | None = None,
    fill=None,
    text_fill=(255, 255, 255),
) -> tuple[int, int, int, int] | None:
    if not text:
        return None
    width, height = size
    font = imaging.get_font(imaging.font_path(True), max(14, int(width * 0.023)))
    tw, th = imaging.text_metrics(draw, str(text), font)
    pad_x = max(12, int(width * 0.018))
    box_w = tw + pad_x * 2
    box_h = max(34, int(height * 0.045))
    if x is None:
        x = int(width * 0.05)
    if y is None:
        y = int(height * 0.05)
    box = (x, y, x + box_w, y + box_h)
    imaging.draw_pill(draw, box, fill or accent, str(text), font, text_fill)
    return box


def render_split(ctx: dict) -> Image.Image:
    width, height = ctx["size"]
    accent, bg, text_color = ctx["accent"], ctx["bg"], ctx["text_color"]
    canvas = _template_surface(ctx, bg)
    draw = _draw(canvas)
    if not ctx["show_text"]:
        _place_product(ctx, canvas, _photo_for(ctx, (width, height), ctx["photo_mode"], bg))
        return canvas
    mobile = _is_mobile((width, height))
    if mobile:
        photo_h = int(height * 0.60)
        photo = _photo_for(ctx, (width, photo_h), ctx["photo_mode"], bg)
        _place_product(ctx, canvas, photo)
        imaging.add_gradient(canvas, (0, photo_h - int(height * 0.08), width, photo_h), bg + (0,), bg + (255,))
        x = int(width * 0.055)
        text_w = width - x * 2
        y = photo_h + int(height * 0.028)
        font, lines, line_h = imaging.fit_text(
            draw, ctx["headline"], True, text_w, int(height * 0.16), int(width * 0.085), 30, 2
        )
        y = _headline(ctx, draw, (x, y), lines, font, text_color, line_h, shadow=False)
        if ctx["subhead"]:
            font2, lines2, lh2 = imaging.fit_text(
                draw, ctx["subhead"], False, text_w, int(height * 0.06), int(width * 0.034), 16, 1
            )
            y = imaging.draw_text_lines(draw, (x, y + int(height * 0.014)), lines2, font2, _body_color(ctx), lh2)
        draw.rectangle([x, y + int(height * 0.012), x + int(width * 0.07), y + int(height * 0.012) + 5], fill=accent)
        _draw_bullets(
            draw, x, y + int(height * 0.032), text_w, ctx["bullets"], int(width * 0.027), _body_color(ctx), accent,
            max_items=2, max_lines=1,
        )
        if ctx["badge"]:
            _draw_badge(_element_surface(ctx, draw, ctx["badge"]), (width, height), ctx["badge"], accent, y=int(height * 0.035))
        _draw_footer(draw, (width, height), ctx["footer"], accent, _body_color(ctx))
        return canvas

    photo_w = int(width * 0.60)
    photo = _photo_for(ctx, (photo_w, height), ctx["photo_mode"], bg)
    _place_product(ctx, canvas, photo)
    draw.rectangle([photo_w - 2, int(height * 0.07), photo_w + 2, int(height * 0.93)], fill=accent + (80,))
    x = photo_w + int(width * 0.055)
    text_w = width - x - int(width * 0.05)
    y = int(height * 0.09)
    font, lines, line_h = imaging.fit_text(
        draw, ctx["headline"], True, text_w, int(height * 0.34), int(width * 0.092), 34, 3
    )
    y = _headline(ctx, draw, (x, y), lines, font, text_color, line_h)
    if ctx["subhead"]:
        font2, lines2, lh2 = imaging.fit_text(
            draw, ctx["subhead"], False, text_w, int(height * 0.12), int(width * 0.036), 18, 2
        )
        y = imaging.draw_text_lines(draw, (x, y + int(height * 0.018)), lines2, font2, _body_color(ctx), lh2)
    draw.rectangle([x, y + int(height * 0.024), x + int(width * 0.07), y + int(height * 0.024) + 5], fill=accent)
    _draw_bullets(
        draw, x, y + int(height * 0.05), text_w, ctx["bullets"], int(width * 0.027), _body_color(ctx), accent,
        max_items=3, max_lines=1,
    )
    if ctx["badge"]:
        _draw_badge(_element_surface(ctx, draw, ctx["badge"]), (width, height), ctx["badge"], accent, x=x, y=int(height * 0.78))
    _draw_footer(draw, (width, height), ctx["footer"], accent, _body_color(ctx))
    return canvas


def render_overlay(ctx: dict) -> Image.Image:
    width, height = ctx["size"]
    accent, bg, text_color = ctx["accent"], ctx["bg"], ctx["text_color"]
    canvas = _template_surface(ctx, bg)
    photo = _photo_for(ctx, (width, height), ctx["photo_mode"], bg)
    _place_product(ctx, canvas, photo)
    if not ctx["show_text"]:
        return canvas
    draw = _draw(canvas)
    top_h = int(height * (0.40 if _is_mobile((width, height)) else 0.34))
    imaging.add_gradient(canvas, (0, 0, width, top_h), (0, 0, 0, 205), (0, 0, 0, 0))
    x = int(width * 0.055)
    y = int(height * 0.045)
    text_w = width - x * 2
    font, lines, line_h = imaging.fit_text(
        draw, ctx["headline"], True, text_w, int(height * 0.18), int(width * 0.088), 30, 2
    )
    y = _headline(ctx, draw, (x, y), lines, font, (255, 255, 255), line_h, shadow=True)
    if ctx["subhead"]:
        font2, lines2, lh2 = imaging.fit_text(
            draw, ctx["subhead"], False, text_w, int(height * 0.10), int(width * 0.032), 16, 2
        )
        y = imaging.draw_text_lines(
            draw, (x, y + int(height * 0.012)), lines2, font2, (255, 255, 255, 235), lh2, shadow=True
        )
    if ctx["badge"]:
        font_b = imaging.get_font(imaging.font_path(True), max(14, int(width * 0.023)))
        tw, _ = imaging.text_metrics(draw, ctx["badge"], font_b)
        pad = max(12, int(width * 0.018))
        _draw_badge(
            _element_surface(ctx, draw, ctx["badge"]), (width, height), ctx["badge"], accent,
            x=width - int(width * 0.05) - tw - pad * 2, y=int(height * 0.05),
        )
    bullets = (ctx["bullets"] or [])[:3]
    if bullets or ctx["footer"]:
        imaging.add_gradient(canvas, (0, int(height * 0.74), width, height), (0, 0, 0, 0), (0, 0, 0, 185))
        chip_font = imaging.get_font(imaging.font_path(True), max(13, int(width * 0.021)))
        chip_y = int(height * 0.80)
        chip_x = int(width * 0.05)
        for item in bullets:
            tw, _ = imaging.text_metrics(draw, item, chip_font)
            box_w = min(width - chip_x - int(width * 0.05), tw + int(width * 0.035))
            imaging.draw_pill(
                draw, (chip_x, chip_y, chip_x + box_w, chip_y + int(height * 0.045)),
                (255, 255, 255, 48), item, chip_font, (255, 255, 255),
            )
            chip_x += box_w + int(width * 0.015)
            if chip_x > width - int(width * 0.2):
                break
        _draw_footer(draw, (width, height), ctx["footer"], accent, (255, 255, 255, 220))
    return canvas


def render_annotate(ctx: dict) -> Image.Image:
    width, height = ctx["size"]
    accent, bg, text_color = ctx["accent"], ctx["bg"], ctx["text_color"]
    canvas = _template_surface(ctx, bg)
    photo = _photo_for(ctx, (width, height), ctx["photo_mode"], bg)
    _place_product(ctx, canvas, photo)
    if not ctx["show_text"]:
        return canvas
    draw = _draw(canvas)
    imaging.add_gradient(canvas, (0, 0, width, int(height * 0.30)), (0, 0, 0, 190), (0, 0, 0, 0))
    x = int(width * 0.05)
    y = int(height * 0.04)
    font, lines, line_h = imaging.fit_text(
        draw, ctx["headline"], True, int(width * 0.88), int(height * 0.14), int(width * 0.075), 28, 2
    )
    y = _headline(ctx, draw, (x, y), lines, font, (255, 255, 255), line_h, shadow=True)
    if ctx["subhead"]:
        font2, lines2, lh2 = imaging.fit_text(
            draw, ctx["subhead"], False, int(width * 0.88), int(height * 0.07), int(width * 0.028), 14, 1
        )
        imaging.draw_text_lines(draw, (x, y + int(height * 0.01)), lines2, font2, (255, 255, 255, 230), lh2, shadow=True)
    mobile = _is_mobile((width, height))
    if mobile:
        ellipse = (int(width * 0.20), int(height * 0.44), int(width * 0.84), int(height * 0.74))
        positions = [
            ((int(width * 0.05), int(height * 0.49)), (int(width * 0.38), int(height * 0.58))),
            ((int(width * 0.60), int(height * 0.36)), (int(width * 0.58), int(height * 0.51))),
        ]
    else:
        ellipse = (int(width * 0.24), int(height * 0.34), int(width * 0.80), int(height * 0.76))
        positions = [
            ((int(width * 0.06), int(height * 0.47)), (int(width * 0.40), int(height * 0.55))),
            ((int(width * 0.68), int(height * 0.31)), (int(width * 0.62), int(height * 0.47))),
            ((int(width * 0.66), int(height * 0.75)), (int(width * 0.56), int(height * 0.64))),
        ]
    imaging.draw_dashed_ellipse(draw, ellipse, (255, 255, 255, 235), width=max(3, int(width * 0.005)), dash=18, gap=12)
    labels = [str(item) for item in (ctx["bullets"] or []) if item][: len(positions)]
    if not labels:
        labels = ["细节展示", "版型设计"]
    label_font = imaging.get_font(imaging.font_path(True), max(13, int(width * 0.022)))
    for label, (label_pos, target) in zip(labels, positions):
        label = label[:10]
        tw, _ = imaging.text_metrics(draw, label, label_font)
        pad = max(10, int(width * 0.014))
        box_w = tw + pad * 2
        box_h = max(30, int(height * 0.04))
        lx, ly = label_pos
        if lx + box_w > width - int(width * 0.03):
            lx = width - int(width * 0.03) - box_w
        box = (lx, ly, lx + box_w, ly + box_h)
        imaging.draw_arrow(draw, (lx + box_w / 2, ly + box_h / 2), target, (255, 255, 255, 235), width=4, head=12)
        imaging.draw_pill(draw, box, (255, 255, 255, 235), label, label_font, (40, 32, 36))
    _draw_footer(draw, (width, height), ctx["footer"], accent, (255, 255, 255, 220))
    return canvas


def render_band(ctx: dict) -> Image.Image:
    width, height = ctx["size"]
    accent, bg, text_color = ctx["accent"], ctx["bg"], ctx["text_color"]
    dark = imaging.mix_color(accent, (20, 16, 18), 0.42)
    canvas = _template_surface(ctx, bg)
    if not ctx["show_text"]:
        _place_product(ctx, canvas, _photo_for(ctx, (width, height), ctx["photo_mode"], bg))
        return canvas
    mobile = _is_mobile((width, height))
    band_h = int(height * (0.155 if mobile else 0.19))
    bottom_h = int(height * (0.18 if mobile else 0.17))
    draw = _draw(canvas)
    draw.rectangle([0, 0, width, band_h], fill=dark)
    x = int(width * 0.05)
    font, lines, line_h = imaging.fit_text(
        draw, ctx["headline"], True, int(width * 0.72), band_h - int(height * 0.055), int(width * 0.062), 24, 2
    )
    _headline(ctx, draw, (x, int(height * 0.028)), lines, font, (255, 255, 255), line_h, shadow=False)
    if ctx["subhead"]:
        font2, lines2, lh2 = imaging.fit_text(
            draw, ctx["subhead"], False, int(width * 0.72), int(height * 0.045), int(width * 0.026), 13, 1
        )
        imaging.draw_text_lines(
            draw, (x, band_h - int(height * 0.028) - lh2), lines2, font2, (255, 255, 255, 225), lh2
        )
    badge_text = ctx["badge"] or "面料细节"
    font_b = imaging.get_font(imaging.font_path(True), max(12, int(width * 0.02)))
    tw, _ = imaging.text_metrics(draw, badge_text, font_b)
    pad = max(10, int(width * 0.014))
    box = (width - int(width * 0.05) - tw - pad * 2, int(height * 0.035), width - int(width * 0.05), int(height * 0.035) + int(height * 0.042))
    imaging.draw_pill(_element_surface(ctx, draw, badge_text), box, (255, 255, 255, 38), badge_text, font_b, (255, 255, 255), outline=(255, 255, 255, 120), outline_width=2)
    photo_box = (0, band_h, width, height - bottom_h)
    photo = _photo_for(ctx, (width, photo_box[3] - photo_box[1]), ctx["photo_mode"], bg)
    _place_product(ctx, canvas, photo, y=band_h)
    imaging.add_gradient(canvas, (0, height - bottom_h, width, height), dark + (0,), dark + (225,))
    bullets = [str(item) for item in (ctx["bullets"] or []) if item][:4]
    if bullets:
        cols = 2 if mobile else max(1, min(4, len(bullets)))
        rows = (len(bullets) + cols - 1) // cols
        margin = int(width * 0.05)
        gap = int(width * 0.014)
        chip_w = (width - margin * 2 - gap * (cols - 1)) // cols
        chip_h = int(height * (0.045 if mobile else 0.05))
        start_y = height - bottom_h + int(height * 0.035)
        chip_font = imaging.get_font(imaging.font_path(True), max(13, int(width * 0.022)))
        for index, item in enumerate(bullets):
            row, col = divmod(index, cols)
            cx = margin + col * (chip_w + gap)
            cy = start_y + row * (chip_h + int(height * 0.012))
            imaging.draw_pill(draw, (cx, cy, cx + chip_w, cy + chip_h), (255, 255, 255, 48), item[:10], chip_font, (255, 255, 255))
        _ = rows
    elif ctx["footer"]:
        font3 = imaging.get_font(imaging.font_path(True), max(14, int(width * 0.023)))
        tw, _ = imaging.text_metrics(draw, ctx["footer"], font3)
        draw.text(((width - tw) // 2, height - bottom_h + int(height * 0.055)), ctx["footer"], font=font3, fill=(255, 255, 255, 230))
    return canvas


def render_grid(ctx: dict) -> Image.Image:
    width, height = ctx["size"]
    accent, bg, text_color = ctx["accent"], ctx["bg"], ctx["text_color"]
    canvas = _template_surface(ctx, bg)
    draw = _draw(canvas)
    mobile = _is_mobile((width, height))
    title = ctx["headline"] or "多色可选"
    font, lines, line_h = imaging.fit_text(
        draw, title, True, int(width * 0.86), int(height * 0.09), int(width * 0.075), 30, 1
    )
    _headline(ctx, draw, (width // 2, int(height * 0.035)), lines, font, text_color, line_h, align="center")
    subhead_y = int(height * (0.125 if mobile else 0.115))
    line_y = int(height * (0.175 if mobile else 0.16))
    if ctx["subhead"]:
        font2 = imaging.get_font(imaging.font_path(False), max(13, int(width * 0.025)))
        tw, _ = imaging.text_metrics(draw, ctx["subhead"], font2)
        draw.text(((width - tw) // 2, subhead_y), ctx["subhead"], font=font2, fill=_body_color(ctx))
    draw.rectangle([width // 2 - int(width * 0.03), line_y, width // 2 + int(width * 0.03), line_y + 5], fill=accent)
    items = list(ctx.get("color_items") or [])
    if not items:
        items = [{"name": "主图", "image": ctx["photo"]}]
    max_slots = 9 if mobile else 8
    more = {"name": "更多颜色", "image": None, "more": True}
    if len(items) > max_slots:
        items = items[: max_slots - 1] + [more]
    elif len(items) >= 5 and len(items) < max_slots:
        items = items + [more]
    cols = 3 if mobile else 4
    rows = 3 if mobile else 2
    margin_x = int(width * (0.05 if mobile else 0.06))
    gap = int(width * (0.018 if mobile else 0.015))
    label_h = int(height * (0.038 if mobile else 0.045))
    title_area = int(height * (0.20 if mobile else 0.23))
    footer_area = int(height * (0.08 if mobile else 0.10))
    available_w = width - margin_x * 2
    available_h = height - title_area - footer_area - rows * label_h - (rows - 1) * gap
    tile = min((available_w - gap * (cols - 1)) // cols, available_h // rows)
    grid_w = cols * tile + gap * (cols - 1)
    start_x = (width - grid_w) // 2
    start_y = title_area + max(0, (available_h - (rows * tile + (rows - 1) * gap)) // 2)
    label_font = imaging.get_font(imaging.font_path(True), max(13, int(width * 0.023)))
    for index, item in enumerate(items):
        row, col = divmod(index, cols)
        if row >= rows:
            break
        x = start_x + col * (tile + gap)
        y = start_y + row * (tile + label_h + gap)
        radius = max(10, int(tile * 0.10))
        image = item.get("image")
        draw.rounded_rectangle(
            [x, y, x + tile, y + tile], radius=radius,
            fill=None if "layers" in ctx and isinstance(image, Image.Image) else (255, 255, 255),
            outline=(228, 220, 214), width=2,
        )
        if item.get("more"):
            draw.text((x + tile // 2, y + tile // 2 - int(tile * 0.10)), "更多", font=label_font, fill=accent, anchor="mm")
            draw.text((x + tile // 2, y + tile // 2 + int(tile * 0.04)), "颜色", font=label_font, fill=accent, anchor="mm")
        else:
            if isinstance(image, Image.Image):
                fitted = imaging.fit_contain(image, (tile, tile), bg=(255, 255, 255), padding=max(4, int(tile * 0.05)))
                _place_product(ctx, canvas, fitted, x, y, name=f"商品图 · {item['name']}",
                               mask=imaging.rounded_mask(fitted.size, radius))
        name = str(item.get("name", ""))[:8]
        tw, _ = imaging.text_metrics(draw, name, label_font)
        draw.text((x + (tile - tw) // 2, y + tile + int(label_h * 0.22)), name, font=label_font, fill=text_color)
    footer = ctx["footer"] or "多色可选 · 进店选购"
    font3 = imaging.get_font(imaging.font_path(True), max(14, int(width * 0.024)))
    tw, _ = imaging.text_metrics(draw, footer, font3)
    pad = int(width * 0.035)
    box_w = min(width - margin_x * 2, tw + pad * 2)
    bx = (width - box_w) // 2
    by = height - int(height * 0.065) - int(height * 0.05)
    imaging.draw_pill(_element_surface(ctx, draw, footer), (bx, by, bx + box_w, by + int(height * 0.05)), accent, footer, font3, (255, 255, 255))
    return canvas


def render_white_canvas(ctx: dict) -> Image.Image:
    width, height = ctx["size"]
    canvas = _template_surface(ctx, (255, 255, 255))
    photo = ctx["photo"]
    if ctx.get("whiten", True):
        photo = imaging.whiten_background(photo)
    padding = int(min(width, height) * (0.085 if _is_mobile((width, height)) else 0.075))
    fitted = imaging.fit_contain_focus(
        photo, (width, height), bg=(255, 255, 255), padding=padding,
        zoom=ctx.get("photo_zoom", 1),
        offset_x=ctx.get("photo_x", 0),
        offset_y=ctx.get("photo_y", 0),
    )
    _place_product(ctx, canvas, fitted)
    return canvas


RENDERERS = {
    "split": render_split,
    "overlay": render_overlay,
    "annotate": render_annotate,
    "band": render_band,
    "grid": render_grid,
    "white": render_white_canvas,
}


def _spec(kind: str) -> dict:
    return config.get_spec(kind)


def _finalize_record(
    task_id: str,
    kind: str,
    path: Path,
    template: str,
    source: str,
    options: dict,
    extra: dict | None = None,
) -> dict:
    spec = _spec(kind)
    with Image.open(path) as src:
        image = src.convert("RGB")
    info = imaging.save_jpeg(
        image,
        path,
        target_bytes=int(spec.get("target_bytes", 0) or 0),
        max_bytes=int(spec.get("max_bytes", 0) or 0),
    )
    issues = imaging.validate_output(path, spec, kind)
    task_dir = config.TASKS_DIR / task_id
    record = {
        "file": path.relative_to(task_dir).as_posix(),
        "template": template,
        "source": source,
        "width": info["width"],
        "height": info["height"],
        "bytes": info["bytes"],
        "quality": info["quality"],
        "issues": issues,
        "headline": options.get("headline", ""),
        "subhead": options.get("subhead", ""),
        "updatedAt": storage.now(),
    }
    if extra:
        record.update(extra)
    return record


def _color_items(task_id: str, meta: dict) -> list[dict]:
    items = []
    groups = storage.scan_raw(task_id)
    sku_records = {item.get("image", ""): item.get("name", "") for item in meta.get("sku", [])}
    for rel in groups.get("sku", []):
        name = sku_records.get(rel, "")
        if not name:
            name = re.sub(r"^sku_\d+_", "", Path(rel).stem)
        if any(keyword in name for keyword in ("定制", "OEM", "ODM", "支持", "联系", "客服", "更多")):
            continue
        try:
            image = imaging.load_image(_raw_path(task_id, rel))
        except Exception:
            continue
        items.append({"name": name, "image": image, "file": rel})
        if len(items) >= 9:
            break
    return items


def _main_context(size, photo, options: dict, design: dict, color_items: list) -> dict:
    return {
        "size": size,
        "photo": photo,
        "headline": str(options.get("headline") or ""),
        "subhead": str(options.get("subhead") or ""),
        "bullets": [str(item) for item in (options.get("bullets") or []) if str(item).strip()],
        "badge": str(options.get("badge") or ""),
        "footer": str(options.get("footer") or ""),
        "accent": imaging.hex_to_rgb(options.get("accent") or "#E8467C"),
        "bg": imaging.hex_to_rgb(options.get("bg") or design.get("background") or "#F7F4F0"),
        "text_color": imaging.hex_to_rgb(options.get("text_color") or "#1A1A1A"),
        "photo_mode": str(options.get("photo_mode") or "cover"),
        "photo_zoom": float(options.get("photo_zoom", 1) or 1) * float(design.get("productScale", 1) or 1),
        "photo_x": options.get("photo_x", 0),
        "photo_y": options.get("photo_y", 0),
        "show_text": bool(options.get("show_text", True)),
        "color_items": color_items,
        "whiten": bool(options.get("whiten", True)),
    }


def prepare_main_design(task_id: str, kind: str, slot: int, expected: str, *, template_only=False) -> dict:
    meta = storage.load_meta(task_id)
    record = main_design.get_record(meta, kind, slot)
    main_design.check_revision(record, expected)
    if template_only and record.get("templateEditor"):
        return main_design.editable_record({"editor": record["templateEditor"]})["editor"]
    if record.get("editor") and not template_only:
        return record
    options = default_slot_options(task_id, meta)["slots"][slot - 1]
    for key in ("template", "source", "headline", "subhead"):
        if key in record and (record[key] or key in ("headline", "subhead")):
            options[key] = record[key]
    template = options["template"]
    photo = _load_photo(task_id, options["source"])
    size = (record["width"], record["height"])
    colors = _color_items(task_id, meta) if template == "grid" else []
    ctx = _main_context(size, photo, options, {}, colors)
    canvas, layers = main_composition(template, ctx)
    project = main_design.layer_project(task_id, kind, slot, canvas, _main_background(template, ctx), layers)
    project["reconstructed"] = True

    def update(current: dict) -> None:
        result = main_design.get_record(current, kind, slot)
        main_design.check_revision(result, expected)
        result.setdefault("templateEditor", project)
        result.setdefault("templateSource", options["source"])
        if not template_only:
            result.setdefault("editor", project)

    result = main_design.get_record(storage.update_meta(task_id, update), kind, slot)
    if template_only:
        return main_design.editable_record({"editor": result["templateEditor"]})["editor"]
    return result


def _main_background(template: str, ctx: dict) -> tuple:
    return (255, 255, 255) if template == "white" else ctx["bg"]


def render_main_slot(task_id: str, slot: int, options: dict, meta: dict | None = None) -> dict:
    slot = int(slot)
    if slot < 1 or slot > 5:
        raise ValueError("主图卡位必须是 1-5")
    meta = meta or storage.load_meta(task_id)
    options = dict(options or {})
    design = meta.get("design") if isinstance(meta.get("design"), dict) else {}
    template = str(options.get("template") or DEFAULT_TEMPLATES.get(str(slot), "split"))
    if template not in RENDERERS:
        raise ValueError(f"未知模板: {template}")
    source = str(options.get("source") or "").strip()
    if not source:
        groups = storage.scan_raw(task_id)
        candidates = groups.get("main", []) + groups.get("detail", []) + groups.get("sku", [])
        if not candidates:
            raise ValueError("任务还没有可用素材，请先采集或上传图片")
        source = candidates[min(slot - 1, len(candidates) - 1)]
    photo = _load_photo(task_id, source)
    variants = options.get("variants") or ["pc", "mobile"]
    if isinstance(variants, str):
        variants = [variants]
    color_items = _color_items(task_id, meta) if template == "grid" else []
    records = {}
    task_root = storage.task_path(task_id)
    with tempfile.TemporaryDirectory(dir=task_root) as temporary:
        pending = {}
        for variant in variants:
            if variant not in ("pc", "mobile") or variant in records:
                continue
            kind = "main_pc" if variant == "pc" else "main_mobile"
            spec = _spec(kind)
            size = (int(spec.get("width", 800)), int(spec.get("height", 800)))
            ctx = _main_context(size, photo, options, design, color_items)
            canvas, layers = main_composition(template, ctx)
            project = main_design.layer_project(task_id, kind, slot, canvas, _main_background(template, ctx), layers)
            path = Path(temporary) / f"{kind}.jpg"
            target = storage.output_dir(task_id, kind) / f"{slot:02d}.jpg"
            canvas.save(path, "JPEG", quality=95)
            record = _finalize_record(task_id, kind, path, template, source, options)
            record.update(file=target.relative_to(task_root).as_posix(),
                          previewVersion=str(path.stat().st_mtime_ns), editor=project,
                          templateEditor=project, templateSource=source)
            records[variant] = record
            pending[variant] = (kind, path, target)

        def _update(meta_obj: dict) -> None:
            for variant, record in records.items():
                kind, path, target = pending[variant]
                os.replace(path, target)
                meta_obj.setdefault("outputs", {}).setdefault(kind, {})[str(slot)] = record
            meta_obj["status"] = "generated"
            meta_obj["statusText"] = "已出图"
            storage.add_log(meta_obj, f"生成主图卡位 {slot}：{template}（{', '.join(records.keys())}）")

        storage.update_meta(task_id, _update)
    return records


def default_slot_options(task_id: str, meta: dict | None = None) -> dict:
    meta = meta or storage.load_meta(task_id)
    groups = storage.scan_raw(task_id)
    analysis = keywords.analyze([], meta.get("title", ""))
    copy = analysis.get("copy", {})
    color_items = _color_items(task_id, meta)
    color_names = [item["name"] for item in color_items]
    main_files = groups.get("main", [])
    detail_files = groups.get("detail", [])
    sku_files = groups.get("sku", [])
    fallback = (main_files + detail_files + sku_files)[:1]
    sources = []
    for index in range(5):
        if index < len(main_files):
            sources.append(main_files[index])
        elif detail_files:
            sources.append(detail_files[min(index, len(detail_files) - 1)])
        elif fallback:
            sources.append(fallback[0])
        else:
            sources.append("")
    slots = []
    for slot in range(1, 6):
        slot_copy = copy.get("slots", {}).get(str(slot), {})
        headline = slot_copy.get("headline", "")
        subhead = slot_copy.get("subhead", "")
        bullets = slot_copy.get("bullets", [])
        badge = slot_copy.get("badge", "")
        footer = slot_copy.get("footer", "")
        if slot == 5:
            headline = f"{len(color_names)}色可选" if len(color_names) >= 2 else "多色可选"
            subhead = "COLOR OPTIONS"
            bullets = color_names[:4] or bullets
            badge = ""
        slots.append({
            "slot": slot,
            "role": SLOT_ROLES[str(slot)],
            "template": DEFAULT_TEMPLATES[str(slot)],
            "source": sources[slot - 1],
            "headline": headline,
            "subhead": subhead,
            "bullets": bullets,
            "badge": badge,
            "footer": footer,
            "variants": ["pc", "mobile"],
            "accent": "#E8467C",
            "bg": "#F7F4F0",
            "text_color": "#1A1A1A",
            "photo_mode": "cover",
            "photo_zoom": 1,
            "photo_x": 0,
            "photo_y": 0,
            "show_text": True,
        })
    return {
        "slots": slots,
        "colorItems": [{"name": item["name"], "file": item["file"]} for item in color_items],
        "analysisSummary": {
            "categories": {key: value.get("words", [])[:8] for key, value in analysis.get("categories", {}).items()},
            "bannedFound": analysis.get("bannedFound", []),
        },
        "rawGroups": groups,
    }


def render_all_main(task_id: str, slots: list[dict] | None = None, meta: dict | None = None) -> dict:
    meta = meta or storage.load_meta(task_id)
    if not slots:
        slots = default_slot_options(task_id, meta)["slots"]
    results = {}
    errors = []
    for slot_options in slots:
        slot = int(slot_options.get("slot", 0))
        try:
            results[str(slot)] = render_main_slot(task_id, slot, slot_options, meta)
        except Exception as exc:
            errors.append({"slot": slot, "error": str(exc)})
    return {"records": results, "errors": errors}


DETAIL_SEQUENCE = (
    ("商品全貌", r"首屏|首图|封面|全貌|主图|\b(?:hero|cover|overview)\b"),
    ("核心卖点", r"卖点|亮点|优势|功能|\b(?:features?|benefits?)\b"),
    ("使用场景", r"场景|实拍|穿搭|上身|\b(?:scene|lifestyle|usage)\b"),
    ("细节展示", r"细节|工艺|材质|面料|\b(?:closeup|texture|material)\b"),
    ("规格参数", r"规格|参数|尺码|尺寸|色卡|\b(?:specs?|size|dimensions)\b"),
    ("选购说明", r"售后|保养|洗涤|包装|安装|说明|\b(?:care|guide|shipping)\b"),
)
DETAIL_ROLE_PATTERNS = tuple((label, re.compile(pattern, re.I)) for label, pattern in DETAIL_SEQUENCE)


def detail_source_role(name: str) -> tuple[int, str]:
    stem = re.sub(r"[_-]+", " ", name)
    # Keep unrecognized materials together in their existing order.
    for index in (4, 5, 0, 1, 2, 3):
        label, pattern = DETAIL_ROLE_PATTERNS[index]
        if pattern.search(stem):
            return index * 2, label
    return 7, ""


def beautify_detail_page(task_id: str, sources: list[str], *, auto_order: bool = False) -> list[dict]:
    groups = storage.scan_raw(task_id)
    if not isinstance(sources, list) or not sources:
        raise ValueError("请至少选择一张详情素材")
    allowed = set(groups["detail"] + groups["main"])
    if any(not isinstance(source, str) or source not in allowed for source in sources):
        raise ValueError("所选详情素材已移动或删除，请重新选择")
    sources = list(dict.fromkeys(sources))
    raw = storage.load_meta(task_id).get("raw", {})
    names = {
        item.get("file"): item.get("name")
        for kind in ("detail", "main") for item in raw.get(kind, [])
    }
    roles = {source: detail_source_role(str(names.get(source) or Path(source).stem)) for source in sources}
    if auto_order:
        sources.sort(key=lambda source: roles[source][0])
    spec = _spec("detail")
    width = int(spec["width"])
    max_height = int(spec.get("max_height") or spec["segment_height"])
    height = min(int(spec["segment_height"]), max_height)
    max_bytes = int(spec.get("max_bytes") or 0)
    target_bytes = int(spec.get("target_bytes") or max_bytes or 0)
    if max_bytes:
        target_bytes = min(target_bytes, max_bytes)
    if width < 1 or height < 1:
        raise ValueError("请检查设置中的详情页宽度和分段高度")

    root = storage.task_path(task_id)
    out_dir = storage.output_dir(task_id, "detail")
    generation = uuid4().hex[:10]
    records = []
    previous_names = []
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        staged = Path(temporary)
        for index, source in enumerate(sources, 1):
            try:
                image = imaging.load_detail_image(_raw_path(task_id, source))
                original_width = image.width
                total_height = max(1, round(image.height * width / image.width))
                if image.width != width:
                    image = image.resize((width, total_height), imaging.RESAMPLE)
                image = imaging.beautify_detail(image, upscaled=original_width < width)
            except (OSError, ValueError) as exc:
                raise ValueError(f"无法处理素材 {Path(source).name}：{exc}") from exc
            pending = list(reversed(imaging.detail_segment_ranges(image, height)))
            segment = 0
            while pending:
                top, bottom = pending.pop()
                name = f"detail_{index:02d}_{segment + 1:02d}_{generation}.jpg"
                path = staged / name
                info = imaging.save_jpeg(image.crop((0, top, width, bottom)), path, target_bytes, max_bytes,
                                         subsampling=0, preferred_quality=82)
                if not info["within_max"]:
                    if bottom - top <= 1:
                        raise ValueError(f"素材 {Path(source).name} 无法压缩到当前文件上限，请检查详情规格")
                    middle = (top + bottom) // 2
                    pending.extend([(middle, bottom), (top, middle)])
                    continue
                issues = imaging.validate_output(path, spec, "detail")
                if original_width < width:
                    issues.append(f"原图宽 {original_width}px，已等比放大至 {width}px；放大无法恢复原本缺失的细节")
                if info["quality"] < 75:
                    issues.append("图片内容较复杂，已加大压缩")
                segment += 1
                records.append({
                    **info, "file": (out_dir / name).relative_to(root).as_posix(),
                    "source": source, "sourceIndex": index, "segment": segment, "template": "detail_beauty",
                    "sourceRole": roles[source][1], "autoOrdered": auto_order,
                    "issues": issues, "updatedAt": storage.now(),
                })

        def publish(meta_obj: dict) -> None:
            for record in records:
                filename = Path(record["file"]).name
                os.replace(staged / filename, out_dir / filename)
            outputs = meta_obj.setdefault("outputs", {})
            previous = outputs.get("detail") or []
            if isinstance(previous, dict):
                previous = previous.values()
            previous_names.extend(
                Path(item["file"]).name for item in previous
                if isinstance(item, dict) and re.fullmatch(r"output/detail/detail_[\w]+\.jpg", item.get("file") or "")
            )
            outputs["detail"] = records
            meta_obj["status"] = "generated"
            meta_obj["statusText"] = "已出图"
            storage.add_log(meta_obj, f"一键美化详情页：{len(sources)} 张素材，{len(records)} 个分段")

        storage.update_meta(task_id, publish)
        for name in previous_names:
            try:
                (out_dir / name).unlink(missing_ok=True)
            except OSError:
                pass
    return records


def render_detail(task_id: str, options: dict | None = None, meta: dict | None = None) -> list[dict]:
    options = dict(options or {})
    if options.get("beautify") is True:
        return beautify_detail_page(task_id, options.get("sources"), auto_order=options.get("auto_order") is True)
    meta = meta or storage.load_meta(task_id)
    design = meta.get("design") if isinstance(meta.get("design"), dict) else {}
    spec = _spec("detail")
    width = int(options.get("width") or spec.get("width", 750))
    segment_height = int(options.get("segment_height") or spec.get("segment_height", 1500))
    groups = storage.scan_raw(task_id)
    sources = [str(item) for item in (options.get("sources") or []) if str(item).strip()]
    if not sources:
        sources = groups.get("detail", []) or groups.get("main", [])
    if not sources:
        raise ValueError("没有可用的详情图素材")
    out_dir = storage.output_dir(task_id, "detail")
    for old in out_dir.glob("detail_*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass
    records = []
    enhance_enabled = bool(options.get("enhance", True))
    for source_index, rel in enumerate(sources, 1):
        path = _raw_path(task_id, rel)
        im = imaging.load_image(path)
        if enhance_enabled:
            im = imaging.enhance(im, color=1.02, contrast=1.02)
        low_res = im.width < width
        if im.width != width:
            new_h = max(1, int(im.height * width / im.width))
            im = im.resize((width, new_h), imaging.RESAMPLE)
        segments = max(1, (im.height + segment_height - 1) // segment_height)
        for segment_index in range(segments):
            top = segment_index * segment_height
            bottom = min(im.height, top + segment_height)
            segment = im.crop((0, top, width, bottom))
            filename = f"detail_{source_index:02d}_{segment_index + 1:02d}.jpg"
            out_path = out_dir / filename
            segment.save(out_path, "JPEG", quality=92)
            record = _finalize_record(
                task_id, "detail", out_path, "segment", rel, options,
                extra={"sourceIndex": source_index, "segment": segment_index + 1, "segments": segments},
            )
            if low_res:
                record["issues"].append("原图宽度不足 750px，已放大")
            records.append(record)
    cover_made = None
    if options.get("make_cover"):
        cover_source = str(options.get("cover_source") or (groups.get("main", []) or [""])[0])
        if cover_source:
            try:
                photo = _load_photo(task_id, cover_source)
                size = (width, int(width * 4 / 3))
                ctx = {
                    "size": size,
                    "photo": photo,
                    "headline": str(options.get("cover_title") or meta.get("title", "")),
                    "subhead": str(options.get("cover_subhead") or ""),
                    "bullets": [],
                    "badge": "",
                    "footer": str(options.get("cover_footer") or "详情页"),
                    "accent": imaging.hex_to_rgb(options.get("accent") or "#E8467C"),
                    "bg": imaging.hex_to_rgb(options.get("bg") or design.get("background") or "#F7F4F0"),
                    "text_color": imaging.hex_to_rgb(options.get("text_color") or "#FFFFFF"),
                    "photo_mode": "cover",
                    "photo_zoom": float(options.get("cover_photo_zoom", 1) or 1) * float(design.get("productScale", 1) or 1),
                    "photo_x": options.get("cover_photo_x", 0),
                    "photo_y": options.get("cover_photo_y", 0),
                    "show_text": True,
                    "color_items": [],
                    "whiten": False,
                }
                canvas = render_overlay(ctx)
                out_path = out_dir / "detail_00_cover.jpg"
                canvas.save(out_path, "JPEG", quality=94)
                cover_made = _finalize_record(task_id, "detail", out_path, "cover", cover_source, options)
                cover_made["issues"] = [
                    issue for issue in cover_made.get("issues", []) if "高度" not in issue
                ]
                records.insert(0, cover_made)
            except Exception as exc:
                records.append({"file": "", "template": "cover", "source": cover_source, "issues": [str(exc)]})

    def _update(meta_obj: dict):
        meta_obj.setdefault("outputs", {})["detail"] = records
        meta_obj["status"] = "generated"
        meta_obj["statusText"] = "已出图"
        storage.add_log(meta_obj, f"生成详情图：{len(records)} 张")
        return meta_obj

    storage.update_meta(task_id, _update)
    return records


def render_sku(task_id: str, options: dict | None = None, meta: dict | None = None) -> list[dict]:
    options = dict(options or {})
    meta = meta or storage.load_meta(task_id)
    groups = storage.scan_raw(task_id)
    sources = [str(item) for item in (options.get("sources") or []) if str(item).strip()]
    if not sources:
        sources = groups.get("sku", [])
    if not sources:
        raise ValueError("没有可用的 SKU 图素材")
    spec = _spec("sku")
    width = int(spec.get("width", 800))
    height = int(spec.get("height", 800))
    bg = imaging.hex_to_rgb(options.get("bg") or "#FFFFFF")
    out_dir = storage.output_dir(task_id, "sku")
    for old in out_dir.glob("sku_*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass
    sku_names = {item.get("image", ""): item.get("name", "") for item in meta.get("sku", [])}
    records = []
    for index, rel in enumerate(sources, 1):
        photo = _load_photo(task_id, rel)
        name = sku_names.get(rel) or re.sub(r"^sku_\d+_", "", Path(rel).stem)
        if options.get("whiten", True):
            photo = imaging.whiten_background(photo)
        canvas = Image.new("RGB", (width, height), bg)
        padding = int(min(width, height) * 0.085)
        fitted = imaging.fit_contain_focus(
            photo, (width, height), bg=bg, padding=padding,
            zoom=options.get("photo_zoom", 1),
            offset_x=options.get("photo_x", 0),
            offset_y=options.get("photo_y", 0),
        )
        canvas.paste(fitted, (0, 0))
        draw = _draw(canvas)
        if options.get("show_name", True) and name:
            label = str(name)[:10]
            font = imaging.get_font(imaging.font_path(True), max(16, int(width * 0.028)))
            tw, _ = imaging.text_metrics(draw, label, font)
            pad = int(width * 0.03)
            box_w = min(width - int(width * 0.1), tw + pad * 2)
            box_h = int(height * 0.06)
            bx = (width - box_w) // 2
            by = height - box_h - int(height * 0.035)
            imaging.draw_pill(
                draw, (bx, by, bx + box_w, by + box_h),
                imaging.hex_to_rgb(options.get("accent") or "#1A1A1A"), label, font, (255, 255, 255),
            )
        out_path = out_dir / f"sku_{index:02d}_{storage.safe_filename(name, 'sku')}.jpg"
        canvas.save(out_path, "JPEG", quality=94)
        record = _finalize_record(task_id, "sku", out_path, "card", rel, options, extra={"name": name})
        records.append(record)

    def _update(meta_obj: dict):
        meta_obj.setdefault("outputs", {})["sku"] = records
        meta_obj["status"] = "generated"
        meta_obj["statusText"] = "已出图"
        storage.add_log(meta_obj, f"生成 SKU 图：{len(records)} 张")
        return meta_obj

    storage.update_meta(task_id, _update)
    return records


def render_white(task_id: str, options: dict | None = None, meta: dict | None = None) -> dict:
    options = dict(options or {})
    meta = meta or storage.load_meta(task_id)
    groups = storage.scan_raw(task_id)
    source = str(options.get("source") or "").strip()
    if not source:
        candidates = groups.get("sku", []) or groups.get("main", []) or groups.get("detail", [])
        if not candidates:
            raise ValueError("没有可用素材")
        source = candidates[0]
    photo = _load_photo(task_id, source)
    variants = options.get("variants") or ["pc", "mobile"]
    if isinstance(variants, str):
        variants = [variants]
    records = {}
    for variant in variants:
        if variant not in ("pc", "mobile"):
            continue
        kind = "white"
        spec = _spec("white") if variant == "pc" else _spec("white_mobile")
        size = (int(spec.get("width", 800)), int(spec.get("height", 800)))
        ctx = {
            "size": size,
            "photo": photo,
            "headline": "",
            "subhead": "",
            "bullets": [],
            "badge": "",
            "footer": "",
            "accent": imaging.hex_to_rgb("#E8467C"),
            "bg": (255, 255, 255),
            "text_color": (0, 0, 0),
            "photo_mode": "contain",
            "photo_zoom": options.get("photo_zoom", 1),
            "photo_x": options.get("photo_x", 0),
            "photo_y": options.get("photo_y", 0),
            "show_text": False,
            "color_items": [],
            "whiten": bool(options.get("whiten", True)),
        }
        canvas = render_white_canvas(ctx)
        out_dir = storage.output_dir(task_id, "white")
        out_path = out_dir / f"white_{variant}.jpg"
        canvas.save(out_path, "JPEG", quality=94)
        record = _finalize_record(task_id, "white_mobile" if variant == "mobile" else "white", out_path, "white", source, options)
        if variant == "mobile":
            record["note"] = "手机端白底图按 750×1000 输出"
        records[variant] = record

    def _update(meta_obj: dict):
        meta_obj.setdefault("outputs", {}).setdefault("white", {})
        meta_obj["outputs"]["white"].update(records)
        meta_obj["status"] = "generated"
        meta_obj["statusText"] = "已出图"
        storage.add_log(meta_obj, f"生成白底图：{len(records)} 张")
        return meta_obj

    storage.update_meta(task_id, _update)
    return records


def render_color_preview(task_id: str, options: dict | None = None, meta: dict | None = None) -> dict:
    """用当前配色渲染全部模板的小图，供界面即时预览。"""
    options = dict(options or {})
    meta = meta or storage.load_meta(task_id)
    groups = storage.scan_raw(task_id)
    source = str(options.get("source") or "").strip()
    if not source:
        candidates = groups.get("main", []) or groups.get("detail", []) or groups.get("sku", [])
        if not candidates:
            raise ValueError("没有可用素材，无法预览配色")
        source = candidates[0]
    photo = _load_photo(task_id, source)
    color_items = _color_items(task_id, meta)
    task_dir = config.TASKS_DIR / task_id
    out_dir = task_dir / "output" / "preview"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.jpg"):
        try:
            old.unlink()
        except OSError:
            pass
    size = (400, 400)
    items = []
    for template_id, renderer in RENDERERS.items():
        ctx = {
            "size": size,
            "photo": photo,
            "headline": str(options.get("headline") or "高腰显瘦"),
            "subhead": str(options.get("subhead") or "舒适百搭 · 细节用心"),
            "bullets": [str(item) for item in (options.get("bullets") or ["高弹不勒", "亲肤面料"])][:4],
            "badge": str(options.get("badge") or ""),
            "footer": str(options.get("footer") or "高腰提臀 · 细节展示"),
            "accent": imaging.hex_to_rgb(options.get("accent") or "#E8467C"),
            "bg": imaging.hex_to_rgb(options.get("bg") or "#F7F4F0"),
            "text_color": imaging.hex_to_rgb(options.get("text_color") or "#1A1A1A"),
            "photo_mode": str(options.get("photo_mode") or "cover"),
            "photo_zoom": options.get("photo_zoom", 1),
            "photo_x": options.get("photo_x", 0),
            "photo_y": options.get("photo_y", 0),
            "show_text": template_id != "white",
            "color_items": color_items,
            "whiten": True,
        }
        canvas = renderer(ctx)
        path = out_dir / f"{template_id}.jpg"
        canvas.save(path, "JPEG", quality=88)
        items.append({
            "template": template_id,
            "name": template_by_id(template_id).get("name", template_id),
            "file": path.relative_to(task_dir).as_posix(),
        })
    return {"source": source, "items": items}


def outputs_summary(task_id: str) -> dict:
    meta = storage.load_meta(task_id)
    files = storage.scan_outputs(task_id)
    return {
        "meta": meta.get("outputs", {}),
        "files": files,
    }

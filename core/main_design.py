"""Persist and render the editable layers belonging to a generated main image."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageOps

from . import config, imaging, storage

KINDS = {"main_pc", "main_mobile"}
ASSET_KINDS = ("main", "detail", "sku", "review")


class DesignConflict(ValueError):
    pass


def layer_project(task_id: str, kind: str, slot: int, canvas: Image.Image, background: tuple, layers: list) -> dict:
    root = storage.task_path(task_id)
    directory = root / "design" / "main" / kind / str(slot) / uuid4().hex
    directory.mkdir(parents=True)
    records = []
    for index, (name, image, x, y, locked) in enumerate(layers):
        layer_id = str(index + 1)
        path = directory / f"{layer_id}.png"
        image.save(path, "PNG")
        records.append({
            "id": layer_id, "name": name, "file": path.relative_to(root).as_posix(),
            "locked": locked, "replaceable": name == "商品图" or name.startswith("商品图 · "),
            "left": x, "top": y, "width": image.width, "height": image.height,
        })
    return {"width": canvas.width, "height": canvas.height, "background": list(background), "layers": records}


def get_record(meta: dict, kind: str, slot: int) -> dict:
    if kind not in KINDS or not 1 <= slot <= 5:
        raise ValueError("请选择有效的主图卡位和端")
    record = meta.get("outputs", {}).get(kind, {}).get(str(slot))
    if not record or not record.get("file"):
        raise FileNotFoundError("请先生成这张主图")
    return record


def revision(record: dict) -> str:
    return "|".join(str(record.get(key, "")) for key in ("file", "previewVersion", "updatedAt", "editedAt"))


def check_revision(record: dict, expected: str) -> None:
    if revision(record) != expected:
        raise DesignConflict("这张成品已在其他页面更新，请重新打开工作台")


def library(task_id: str) -> dict:
    groups = storage.scan_raw(task_id)
    return {kind: groups.get(kind, []) for kind in ASSET_KINDS}


def editable_record(record: dict) -> dict:
    project = record.get("editor")
    if not project:
        return record
    layers = []
    for layer in project["layers"]:
        name = layer["name"]
        layers.append({
            **layer,
            "locked": layer["locked"] and name != "模板装饰",
            "replaceable": name == "商品图" or name.startswith("商品图 · "),
        })
    return {**record, "editor": {**project, "layers": layers}}


def apply_transforms(project: dict, changes: dict) -> list[dict]:
    if not isinstance(changes, dict):
        raise ValueError("图层参数格式错误")
    editable = {layer["id"] for layer in project["layers"] if not layer["locked"]}
    if not changes.keys() <= editable:
        raise ValueError("图层不存在或已锁定")
    layers = []
    limit = max(project["width"], project["height"])
    for layer in project["layers"]:
        update = changes.get(layer["id"], {})
        if not isinstance(update, dict):
            raise ValueError("图层参数格式错误")
        result = dict(layer)
        for key in ("left", "top", "width", "height"):
            value = update.get(key, layer[key])
            if type(value) is not int or not (-2 * limit <= value <= 3 * limit):
                raise ValueError("图层坐标或尺寸超出范围")
            if key in ("width", "height") and value < 1:
                raise ValueError("图层尺寸必须大于零")
            result[key] = value
        opacity = update.get("opacity", layer.get("opacity", 100))
        if type(opacity) is not int or not 0 <= opacity <= 100:
            raise ValueError("不透明度必须在 0 到 100 之间")
        result["opacity"] = opacity
        layers.append(result)
    return layers


def layer_pixels(root: Path, project: dict, layer: dict, change: dict, allowed: set) -> Image.Image:
    asset = change.get("asset") or ""
    if asset and (not layer["replaceable"] or not isinstance(asset, str) or asset not in allowed):
        raise ValueError("只能为商品图选择当前任务的图片素材")
    path = (root / (asset or layer["file"])).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("图层素材已移动或删除，请重新选择")
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    if asset:
        image.thumbnail((max(project["width"], 1200), max(project["height"], 1200)), imaging.RESAMPLE)
    edits = change.get("edits", [])
    if not isinstance(edits, list) or len(edits) > 100 or (edits and not layer["replaceable"]):
        raise ValueError("商品图编辑参数无效")
    for edit in edits:
        if edit == {"type": "background"}:
            image, _ = imaging.remove_edge_background(image)
            continue
        if not isinstance(edit, dict) or edit.get("type") not in ("clear", "keep"):
            raise ValueError("图层编辑操作无效")
        box = edit.get("box")
        if (not isinstance(box, list) or len(box) != 4
                or any(type(value) not in (int, float) or not 0 <= value <= 1 for value in box)
                or not (box[0] < box[2] and box[1] < box[3])):
            raise ValueError("矩形选区无效")
        left, top, right, bottom = (
            round(value * size) for value, size in zip(box, (image.width, image.height) * 2)
        )
        mask = Image.new("L", image.size)
        mask.paste(255, (left, top, right, bottom))
        if edit["type"] == "clear":
            mask = ImageOps.invert(mask)
        image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    return image


def preview(task_id: str, kind: str, slot: int, expected: str, layer_id: str, change: dict, *, from_template=False) -> Image.Image:
    record = get_record(storage.load_meta(task_id), kind, slot)
    check_revision(record, expected)
    editor = record.get("templateEditor" if from_template else "editor")
    project = editable_record({"editor": editor}).get("editor") or {}
    layer = next((item for item in project.get("layers", []) if item["id"] == layer_id), None)
    if not layer or not layer["replaceable"] or layer["locked"] or not isinstance(change, dict):
        raise ValueError("请选择商品图图层")
    allowed = {asset for group in library(task_id).values() for asset in group}
    return layer_pixels(storage.task_path(task_id), project, layer, change, allowed)


def save(task_id: str, kind: str, slot: int, expected: str, changes: dict, order=None, removed=None, *, from_template=False) -> dict:
    root = storage.task_path(task_id)
    original = get_record(storage.load_meta(task_id), kind, slot)
    check_revision(original, expected)
    editor = original.get("templateEditor" if from_template else "editor")
    project = editable_record({"editor": editor}).get("editor")
    if not project:
        raise ValueError("请先载入可编辑布局")
    layers = apply_transforms(project, changes)
    if removed is not None:
        editable_ids = {layer["id"] for layer in layers if not layer["locked"]}
        if not isinstance(removed, list) or any(not isinstance(key, str) or key not in editable_ids for key in removed):
            raise ValueError("删除的图层不存在或已锁定")
        removed_ids = set(removed)
        layers = [layer for layer in layers if layer["id"] not in removed_ids]
    if order is not None:
        by_id = {layer["id"]: layer for layer in layers}
        if (not isinstance(order, list) or any(not isinstance(key, str) for key in order)
                or len(order) != len(layers) or set(order) != set(by_id)):
            raise ValueError("图层顺序必须包含所有图层且不能重复")
        layers = [by_id[key] for key in order]
    allowed = {asset for group in library(task_id).values() for asset in group}
    canvas = Image.new("RGBA", (project["width"], project["height"]), tuple(project["background"]))
    for layer in layers:
        change = changes.get(layer["id"], {})
        visible = layer_pixels(root, project, layer, change, allowed)
        if change.get("asset") or change.get("edits"):
            directory = root / "design" / "main" / kind / str(slot) / uuid4().hex
            directory.mkdir(parents=True)
            path = directory / (layer["id"] + ".png")
            visible.save(path, "PNG")
            layer["file"] = path.relative_to(root).as_posix()
            if change.get("asset"):
                layer["asset"] = change["asset"]
        size = (layer["width"], layer["height"])
        if visible.size != size:
            visible = visible.resize(size, imaging.RESAMPLE)
        if layer["opacity"] < 100:
            opacity = layer["opacity"] / 100
            visible = visible.copy()
            visible.putalpha(visible.getchannel("A").point(lambda value: round(value * opacity)))
        canvas.alpha_composite(visible, (layer["left"], layer["top"]))

    spec = config.get_spec(kind)
    target = storage.output_dir(task_id, kind) / f"{slot:02d}.jpg"
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        pending = Path(temporary) / target.name
        info = imaging.save_jpeg(
            canvas.convert("RGB"), pending,
            target_bytes=int(spec.get("target_bytes") or 0), max_bytes=int(spec.get("max_bytes") or 0),
        )
        issues = imaging.validate_output(pending, spec, kind)
        editor = {**project, "layers": layers}
        editor.pop("reconstructed", None)

        def update(meta: dict) -> None:
            record = get_record(meta, kind, slot)
            check_revision(record, expected)
            os.replace(pending, target)
            record.pop("editedAt", None)
            record.update(info, file=target.relative_to(root).as_posix(), issues=issues,
                          previewVersion=uuid4().hex, updatedAt=storage.now(),
                          editor=editor)
            products = [layer for layer in layers if layer["replaceable"]]
            if from_template and record.get("templateSource"):
                record["source"] = record["templateSource"]
            if len(products) == 1 and products[0].get("asset"):
                record["source"] = products[0]["asset"]
            storage.add_log(meta, f"保存主图图层编辑 · {kind} · 第 {slot} 张")

        meta = storage.update_meta(task_id, update)
    return get_record(meta, kind, slot)

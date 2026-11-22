# -*- coding: utf-8 -*-
"""任务目录、元数据与文件归档。"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from . import config

_META_LOCK = threading.RLock()

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jfif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".flv", ".mkv"}
ALLOWED_RAW_EXTS = IMAGE_EXTS | VIDEO_EXTS
RAW_KINDS = ("main", "detail", "sku", "video")
OUTPUT_KINDS = ("main_pc", "main_mobile", "white", "detail", "sku", "video", "export")

_WINDOWS_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_filename(name: str, fallback: str = "file", max_len: int = 60) -> str:
    name = _WINDOWS_BAD.sub("_", str(name or "")).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = fallback
    return name[:max_len].strip() or fallback


def natural_key(value: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(value))]


def task_path(task_id: str) -> Path:
    config.ensure_dirs()
    root = config.TASKS_DIR.resolve()
    path = (root / str(task_id)).resolve()
    if path.parent != root:
        raise ValueError("非法任务 ID")
    if not path.is_dir():
        raise FileNotFoundError("任务不存在")
    return path


def task_meta_path(task_id: str) -> Path:
    return task_path(task_id) / "task_meta.json"


def make_task_id(offer_id: str, title: str) -> str:
    config.ensure_dirs()
    slug = safe_filename(title, fallback="未命名", max_len=24)
    slug = re.sub(r"\s+", "", slug)
    prefix = safe_filename(offer_id, fallback="", max_len=24) if offer_id else ""
    base = f"{prefix}_{slug}" if prefix else f"manual_{slug}"
    candidate = base
    index = 2
    while (config.TASKS_DIR / candidate).exists():
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _default_meta(task_id: str, offer_id: str, title: str, source_url: str) -> dict:
    return {
        "id": task_id,
        "offerId": offer_id or "",
        "title": title or "未命名商品",
        "sourceUrl": source_url or "",
        "category": "",
        "price": "",
        "status": "created",
        "statusText": "已创建",
        "progress": {"done": 0, "total": 0},
        "createdAt": now(),
        "updatedAt": now(),
        "lastError": "",
        "raw": {kind: [] for kind in RAW_KINDS},
        "sku": [],
        "skuProps": [],
        "outputs": {kind: {} for kind in OUTPUT_KINDS if kind != "export"},
        "exports": [],
        "keywords": {
            "competitorTitles": [],
            "analyzedAt": "",
            "categories": {},
            "imageTags": {},
            "titles": [],
            "selectedTitle": "",
            "bannedFound": [],
            "brandFound": [],
            "stats": {},
        },
        "logs": [],
    }


def _normalize_meta(meta: dict) -> dict:
    base = _default_meta(
        str(meta.get("id", "")),
        str(meta.get("offerId", "")),
        str(meta.get("title", "")),
        str(meta.get("sourceUrl", "")),
    )
    for key, value in base.items():
        if key not in meta:
            meta[key] = value
        elif isinstance(value, dict) and isinstance(meta.get(key), dict):
            for sub_key, sub_value in value.items():
                meta[key].setdefault(sub_key, sub_value)
    raw = meta.setdefault("raw", {})
    for kind in RAW_KINDS:
        raw.setdefault(kind, [])
    outputs = meta.setdefault("outputs", {})
    for kind in OUTPUT_KINDS:
        if kind != "export":
            outputs.setdefault(kind, {})
    meta.setdefault("sku", [])
    meta.setdefault("exports", [])
    meta.setdefault("logs", [])
    meta.setdefault("keywords", base["keywords"])
    return meta


def ensure_task_dirs(path: Path) -> None:
    for kind in RAW_KINDS:
        (path / "raw" / kind).mkdir(parents=True, exist_ok=True)
    for kind in OUTPUT_KINDS:
        (path / "output" / kind).mkdir(parents=True, exist_ok=True)


def create_task(offer_id: str = "", title: str = "", source_url: str = "", category: str = "", price: str = "") -> dict:
    task_id = make_task_id(offer_id, title)
    path = config.TASKS_DIR / task_id
    ensure_task_dirs(path)
    meta = _default_meta(task_id, offer_id, title, source_url)
    meta["category"] = category or ""
    meta["price"] = price or ""
    add_log(meta, "任务已创建")
    save_meta(task_id, meta)
    return meta


def load_meta(task_id: str) -> dict:
    path = task_meta_path(task_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError) as exc:
        raise FileNotFoundError(f"任务元数据不可读: {exc}") from exc
    if not isinstance(meta, dict):
        raise ValueError("任务元数据格式错误")
    meta.setdefault("id", task_id)
    return _normalize_meta(meta)


def save_meta(task_id: str, meta: dict) -> dict:
    path = task_meta_path(task_id)
    meta = _normalize_meta(meta)
    meta["updatedAt"] = now()
    if len(meta.get("logs", [])) > 300:
        meta["logs"] = meta["logs"][-300:]
    with _META_LOCK:
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    return meta


def update_meta(task_id: str, updater) -> dict:
    with _META_LOCK:
        meta = load_meta(task_id)
        result = updater(meta)
        if isinstance(result, dict):
            meta = result
        return save_meta(task_id, meta)


def add_log(meta: dict, message: str, level: str = "info") -> None:
    meta.setdefault("logs", []).append(
        {"time": now(), "level": level, "message": str(message)}
    )


def set_status(task_id: str, status: str, status_text: str = "", error: str | None = None) -> dict:
    def _update(meta: dict):
        meta["status"] = status
        if status_text:
            meta["statusText"] = status_text
        if error is not None:
            meta["lastError"] = error
        add_log(meta, f"状态更新：{status} {status_text}".strip(), "info" if not error else "error")
        return meta

    return update_meta(task_id, _update)


def sha1_file(path: Path, chunk_size: int = 1024 * 256) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


def file_record(path: Path, task_dir: Path, url: str = "", name: str = "") -> dict:
    try:
        rel = path.relative_to(task_dir).as_posix()
    except ValueError:
        rel = path.name
    width, height = image_size(path) if path.suffix.lower() in IMAGE_EXTS else (0, 0)
    return {
        "file": rel,
        "name": name or path.stem,
        "url": url or "",
        "bytes": path.stat().st_size if path.exists() else 0,
        "width": width,
        "height": height,
        "sha1": sha1_file(path) if path.exists() and path.is_file() else "",
        "addedAt": now(),
    }


def _next_index(directory: Path, prefix: str) -> int:
    max_index = 0
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)")
    if directory.exists():
        for item in directory.iterdir():
            if not item.is_file():
                continue
            match = pattern.match(item.name)
            if match:
                max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def copy_into_raw(
    task_id: str,
    src: Path,
    kind: str,
    index: int | None = None,
    name: str = "",
    url: str = "",
) -> dict:
    if kind not in RAW_KINDS:
        raise ValueError(f"未知素材类型: {kind}")
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"源文件不存在: {src}")
    task_dir = task_path(task_id)
    dest_dir = task_dir / "raw" / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    if ext not in ALLOWED_RAW_EXTS:
        ext = ".jpg" if kind != "video" else ".mp4"
    if index is None:
        index = _next_index(dest_dir, kind)
    while True:
        if kind == "sku" and name:
            filename = f"sku_{index:02d}_{safe_filename(name)}{ext}"
        else:
            filename = f"{kind}_{index:02d}{ext}"
        dest = dest_dir / filename
        if not dest.exists():
            break
        index += 1
    shutil.copy2(src, dest)
    return file_record(dest, task_dir, url=url, name=name)


def save_upload(task_id: str, kind: str, filename: str, stream, name: str = "", url: str = "") -> dict:
    if kind not in RAW_KINDS:
        raise ValueError(f"未知素材类型: {kind}")
    task_dir = task_path(task_id)
    dest_dir = task_dir / "raw" / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_RAW_EXTS:
        ext = ".jpg" if kind != "video" else ".mp4"
    index = _next_index(dest_dir, kind)
    if kind == "sku" and name:
        dest = dest_dir / f"sku_{index:02d}_{safe_filename(name)}{ext}"
    else:
        dest = dest_dir / f"{kind}_{index:02d}{ext}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    stream.save(tmp)
    if kind != "video":
        try:
            with Image.open(tmp) as im:
                im.verify()
        except Exception:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"不是有效图片: {filename}")
    os.replace(tmp, dest)
    return file_record(dest, task_dir, url=url, name=name or Path(filename).stem)


def scan_raw(task_id: str) -> dict[str, list[str]]:
    task_dir = task_path(task_id)
    result: dict[str, list[str]] = {}
    for kind in RAW_KINDS:
        directory = task_dir / "raw" / kind
        files: list[Path] = []
        if directory.is_dir():
            files = [
                item
                for item in directory.iterdir()
                if item.is_file() and item.suffix.lower() in ALLOWED_RAW_EXTS
            ]
        files.sort(key=lambda p: natural_key(p.name))
        result[kind] = [p.relative_to(task_dir).as_posix() for p in files]
    return result


def scan_outputs(task_id: str) -> dict[str, list[str]]:
    task_dir = task_path(task_id)
    result: dict[str, list[str]] = {}
    for kind in OUTPUT_KINDS:
        directory = task_dir / "output" / kind
        files: list[Path] = []
        if directory.is_dir():
            files = [item for item in directory.iterdir() if item.is_file()]
        files.sort(key=lambda p: natural_key(p.name))
        result[kind] = [p.relative_to(task_dir).as_posix() for p in files]
    return result


def get_cover(task_id: str, meta: dict | None = None) -> str:
    meta = meta or load_meta(task_id)
    raw = meta.get("raw", {})
    for kind in ("main", "detail", "sku"):
        for record in raw.get(kind, []):
            rel = record.get("file", "")
            if rel and (task_path(task_id) / rel).is_file():
                return rel
    groups = scan_raw(task_id)
    for kind in ("main", "detail", "sku"):
        if groups.get(kind):
            return groups[kind][0]
    return ""


def get_stats(task_id: str, meta: dict | None = None) -> dict:
    meta = meta or load_meta(task_id)
    groups = scan_raw(task_id)
    outputs = scan_outputs(task_id)
    total_bytes = 0
    for group in groups.values():
        for rel in group:
            try:
                total_bytes += (task_path(task_id) / rel).stat().st_size
            except OSError:
                pass
    for group in outputs.values():
        for rel in group:
            try:
                total_bytes += (task_path(task_id) / rel).stat().st_size
            except OSError:
                pass
    return {
        "rawCounts": {kind: len(files) for kind, files in groups.items()},
        "outputCounts": {kind: len(files) for kind, files in outputs.items()},
        "totalBytes": total_bytes,
        "skuCount": len(meta.get("sku", [])),
        "logCount": len(meta.get("logs", [])),
    }


def task_summary(meta: dict) -> dict:
    task_id = meta.get("id", "")
    stats = {"rawCounts": {}, "outputCounts": {}, "totalBytes": 0, "skuCount": len(meta.get("sku", []))}
    try:
        stats = get_stats(task_id, meta)
    except Exception:
        pass
    return {
        "id": task_id,
        "title": meta.get("title", "未命名商品"),
        "offerId": meta.get("offerId", ""),
        "sourceUrl": meta.get("sourceUrl", ""),
        "status": meta.get("status", "created"),
        "statusText": meta.get("statusText", ""),
        "createdAt": meta.get("createdAt", ""),
        "updatedAt": meta.get("updatedAt", ""),
        "lastError": meta.get("lastError", ""),
        "progress": meta.get("progress", {}),
        "cover": get_cover(task_id, meta),
        "stats": stats,
    }


def list_tasks() -> list[dict]:
    config.ensure_dirs()
    tasks: list[dict] = []
    for item in config.TASKS_DIR.iterdir():
        if not item.is_dir():
            continue
        meta_path = item / "task_meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = load_meta(item.name)
            tasks.append(task_summary(meta))
        except Exception:
            continue
    tasks.sort(key=lambda t: t.get("updatedAt", ""), reverse=True)
    return tasks


def delete_task(task_id: str) -> None:
    path = task_path(task_id)
    shutil.rmtree(path)


def write_task_aux(task_id: str, meta: dict) -> None:
    task_dir = task_path(task_id)
    sku = meta.get("sku", [])
    with open(task_dir / "sku.json", "w", encoding="utf-8") as f:
        json.dump(sku, f, ensure_ascii=False, indent=2)
    with open(task_dir / "sku.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["规格名", "价格", "库存", "SKU图", "来源URL"])
        for item in sku:
            writer.writerow([
                item.get("name", ""),
                item.get("price", ""),
                item.get("stock", ""),
                item.get("image", ""),
                item.get("url", ""),
            ])
    with open(task_dir / "keywords.json", "w", encoding="utf-8") as f:
        json.dump(meta.get("keywords", {}), f, ensure_ascii=False, indent=2)


def update_output_record(task_id: str, old_file: str, updates: dict) -> dict:
    def _update(meta: dict):
        changed = False
        outputs = meta.setdefault("outputs", {})
        for value in outputs.values():
            if isinstance(value, dict):
                for record in value.values():
                    if isinstance(record, dict) and record.get("file") == old_file:
                        record.update(updates)
                        changed = True
            elif isinstance(value, list):
                for record in value:
                    if isinstance(record, dict) and record.get("file") == old_file:
                        record.update(updates)
                        changed = True
        if changed:
            add_log(meta, f"图片已编辑：{old_file}")
        return meta

    return update_meta(task_id, _update)


def output_dir(task_id: str, kind: str) -> Path:
    path = task_path(task_id) / "output" / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def rebuild_sku_from_files(task_id: str, names: list[str] | None = None, urls: list[str] | None = None) -> list[dict]:
    groups = scan_raw(task_id)
    names = names or []
    urls = urls or []
    sku = []
    for index, rel in enumerate(groups.get("sku", [])):
        filename = Path(rel).stem
        name = names[index] if index < len(names) and names[index] else filename
        name = re.sub(r"^sku_\d+_", "", name)
        sku.append({
            "name": name,
            "price": "",
            "stock": "",
            "image": rel,
            "url": urls[index] if index < len(urls) else "",
        })
    return sku

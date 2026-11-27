# -*- coding: utf-8 -*-
"""上架素材包导出。"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from . import config, storage

DEFAULT_SECTIONS = {
    "main_pc": True,
    "main_mobile": True,
    "white": True,
    "detail": True,
    "sku": True,
    "edited": True,
    "video": True,
    "keywords": True,
    "meta": True,
}

FOLDER_NAMES = {
    "main_pc": "01_main_pc",
    "main_mobile": "02_main_mobile",
    "white": "03_white",
    "detail": "04_detail",
    "sku": "05_sku",
    "video": "06_video",
    "keywords": "07_keywords",
    "meta": "08_meta",
    "edited": "09_edited",
}

LABELS = {
    "main_pc": "电脑端主图",
    "main_mobile": "手机端主图",
    "white": "白底图",
    "detail": "详情页图",
    "sku": "SKU 图",
    "edited": "编辑成品",
    "video": "视频",
    "keywords": "关键词",
    "meta": "商品与素材信息",
}


def _csv_bytes(headers: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def _iter_output_records(meta: dict, kind: str):
    value = meta.get("outputs", {}).get(kind, {})
    if isinstance(value, dict):
        for record in value.values():
            if isinstance(record, dict) and record.get("file"):
                yield record
    elif isinstance(value, list):
        for record in value:
            if isinstance(record, dict) and record.get("file"):
                yield record


def build_export(task_id: str, options: dict | None = None) -> dict:
    options = dict(options or {})
    meta = storage.load_meta(task_id)
    task_dir = config.TASKS_DIR / task_id
    settings = config.load_settings()
    sections = dict(DEFAULT_SECTIONS)
    sections.update(options.get("sections") or {})
    export_dir = storage.output_dir(task_id, "export")
    timestamp = storage.timestamp_slug()
    offer = storage.safe_filename(str(meta.get("offerId") or task_id), fallback="task", max_len=24)
    zip_filename = f"taobao_materials_{offer}_{timestamp}.zip"
    zip_path = export_dir / zip_filename
    download_name = f"淘宝素材包_{storage.safe_filename(meta.get('title', '商品'), '商品', 24)}_{timestamp}.zip"

    grouped: dict[str, list[str]] = {kind: [] for kind in FOLDER_NAMES}
    material_rows: list[list] = []

    for kind in ("main_pc", "main_mobile", "white", "detail", "sku", "edited"):
        if not sections.get(kind):
            continue
        for record in _iter_output_records(meta, kind):
            path = task_dir / record["file"]
            if not path.is_file():
                continue
            grouped[kind].append(record["file"])
            material_rows.append([
                LABELS[kind],
                record["file"],
                record.get("source", ""),
                record.get("template", ""),
                record.get("width", ""),
                record.get("height", ""),
                record.get("bytes", ""),
                "; ".join(record.get("issues", []) or []),
            ])
    if sections.get("video"):
        for record in meta.get("raw", {}).get("video", []):
            path = task_dir / record.get("file", "")
            if not path.is_file():
                continue
            grouped["video"].append(record["file"])
            material_rows.append([
                LABELS["video"], record["file"], record.get("url", ""), "",
                record.get("width", ""), record.get("height", ""), record.get("bytes", ""), "",
            ])

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        file_count = 0
        for kind, folder in FOLDER_NAMES.items():
            if not sections.get(kind):
                continue
            for rel in grouped.get(kind, []):
                path = task_dir / rel
                if path.is_file():
                    archive.write(path, arcname=f"{folder}/{path.name}")
                    file_count += 1
        if sections.get("keywords"):
            keywords = meta.get("keywords", {})
            rows = []
            for key, category in keywords.get("categories", {}).items():
                for entry in category.get("words", []):
                    rows.append([
                        category.get("name", key),
                        entry.get("word", ""),
                        entry.get("count", ""),
                        entry.get("score", ""),
                        "/".join(entry.get("source", []) or []),
                    ])
            archive.writestr(
                f"{FOLDER_NAMES['keywords']}/keywords.csv",
                _csv_bytes(["词类", "关键词", "出现次数", "得分", "来源"], rows),
            )
            titles = keywords.get("titles", []) or []
            title_text = ["标题候选", "=" * 40, ""]
            for index, item in enumerate(titles, 1):
                title_text.append(f"{index}. {item.get('title', '')}")
                title_text.append(f"   评分：{item.get('score', '')}  字数：{item.get('length', '')}  来源：{item.get('source', '')}")
            if keywords.get("selectedTitle"):
                title_text.extend(["", f"已选标题：{keywords['selectedTitle']}"])
            if keywords.get("bannedFound"):
                title_text.extend(["", "提示：检测到以下敏感词，请人工确认：" + "、".join(keywords["bannedFound"])])
            title_text.append("")
            archive.writestr(
                f"{FOLDER_NAMES['keywords']}/titles.txt",
                "\ufeff" + "\n".join(title_text),
            )
            file_count += 2
        if sections.get("meta"):
            sku_rows = []
            for item in meta.get("sku", []):
                sku_rows.append([
                    item.get("name", ""), item.get("price", ""), item.get("stock", ""),
                    item.get("image", ""), item.get("url", ""),
                ])
            archive.writestr(
                f"{FOLDER_NAMES['meta']}/sku.csv",
                _csv_bytes(["规格名", "价格", "库存", "SKU图", "来源URL"], sku_rows),
            )
            product_rows = [[
                meta.get("title", ""), meta.get("offerId", ""), meta.get("price", ""),
                meta.get("category", ""), meta.get("sourceUrl", ""), meta.get("createdAt", ""),
            ]]
            archive.writestr(
                f"{FOLDER_NAMES['meta']}/product.csv",
                _csv_bytes(["商品标题", "商品ID", "价格", "类目", "来源链接", "采集时间"], product_rows),
            )
            archive.writestr(
                f"{FOLDER_NAMES['meta']}/material_list.csv",
                _csv_bytes(
                    ["类型", "文件", "来源", "模板", "宽度", "高度", "字节数", "校验问题"],
                    material_rows,
                ),
            )
            product = {
                "title": meta.get("title", ""),
                "offerId": meta.get("offerId", ""),
                "sourceUrl": meta.get("sourceUrl", ""),
                "price": meta.get("price", ""),
                "category": meta.get("category", ""),
                "collectedAt": meta.get("createdAt", ""),
                "sku": meta.get("sku", []),
                "skuProps": meta.get("skuProps", []),
            }
            archive.writestr(
                f"{FOLDER_NAMES['meta']}/product.json",
                json.dumps(product, ensure_ascii=False, indent=2),
            )
            note = [
                "淘宝素材包说明",
                "=" * 40,
                f"商品：{meta.get('title', '')}",
                f"来源：{meta.get('sourceUrl', '')}",
                f"导出时间：{storage.now()}",
                "",
                "目录说明：",
            ]
            for kind, folder in FOLDER_NAMES.items():
                note.append(f"  {folder}/  {LABELS[kind]}")
            note.extend([
                "",
                "温馨提示：",
                "1. 上架前请确认货源图片授权，避免侵权；",
                "2. 主图请遵守平台规范，不要放价格与促销文案；",
                "3. 白底图四角需为纯白 RGB(255,255,255)；",
                "4. CSV 文件使用 UTF-8 BOM 编码，可直接用 Excel 打开。",
                "",
            ])
            archive.writestr(f"{FOLDER_NAMES['meta']}/素材说明.txt", "\ufeff" + "\n".join(note))
            file_count += 5

    info = {
        "file": zip_path.relative_to(task_dir).as_posix(),
        "downloadName": download_name,
        "bytes": zip_path.stat().st_size,
        "fileCount": file_count,
        "sections": {key: bool(value) for key, value in sections.items()},
        "createdAt": storage.now(),
    }

    def _update(meta_obj: dict):
        meta_obj.setdefault("exports", []).append(info)
        meta_obj["exports"] = meta_obj["exports"][-20:]
        meta_obj["status"] = "exported"
        meta_obj["statusText"] = "已导出"
        storage.add_log(meta_obj, f"导出素材包：{download_name}（{file_count} 个文件）")
        return meta_obj

    storage.update_meta(task_id, _update)
    return {"ok": True, "data": info}


def latest_export(task_id: str) -> dict | None:
    meta = storage.load_meta(task_id)
    exports = meta.get("exports", [])
    return exports[-1] if exports else None

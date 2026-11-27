# -*- coding: utf-8 -*-
"""淘宝商品素材采集与创作工具 · 本地 Web 服务入口。"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import io
import mimetypes
import os
import socket
import sys
import tempfile
import threading
import traceback
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from PIL import Image
from werkzeug.exceptions import HTTPException

from core import ai, collector, config, exporter, imaging, keywords, main_design, storage, templates

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

app = Flask(__name__, static_folder=str(config.WEB_DIR), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

JOBS: dict[str, threading.Thread] = {}
JOB_LOCK = threading.RLock()


def ok(data=None, status: int = 200):
    return jsonify({"ok": True, "data": data if data is not None else {}}), status


def fail(message, status: int = 400):
    return jsonify({"ok": False, "error": str(message)}), status


def json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _task_or_error(task_id: str):
    try:
        return storage.load_meta(task_id), None
    except (FileNotFoundError, ValueError) as exc:
        return None, fail(str(exc), 404)


@app.errorhandler(Exception)
def handle_exception(exc):
    if isinstance(exc, HTTPException):
        return fail(exc.description, exc.code or 400)
    traceback.print_exc()
    return fail(f"服务器错误：{exc}", 500)


@app.route("/")
def index():
    return send_from_directory(str(config.WEB_DIR), "index.html")


@app.route("/studio/<task_id>/<kind>/<int:slot>")
def main_image_studio(task_id: str, kind: str, slot: int):
    return send_from_directory(str(config.WEB_DIR), "studio.html")


@app.route("/api/tasks/<task_id>/main-design/<kind>/<int:slot>", methods=["GET", "POST"])
def main_image_design(task_id: str, kind: str, slot: int):
    try:
        meta = storage.load_meta(task_id)
        record = main_design.get_record(meta, kind, slot)
        if request.method == "POST":
            data = json_body()
            expected = data.get("revision", "")
            if data.get("action") == "prepare":
                record = templates.prepare_main_design(task_id, kind, slot, expected)
            elif data.get("action") == "template-preview":
                project = templates.prepare_main_design(task_id, kind, slot, expected, template_only=True)
                return ok(project)
            elif data.get("action") == "preview-layer":
                image = main_design.preview(task_id, kind, slot, expected, data.get("layer"), data.get("change"),
                                            from_template=data.get("fromTemplate") is True)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                buffer.seek(0)
                return send_file(buffer, mimetype="image/png", max_age=0)
            else:
                record = main_design.save(task_id, kind, slot, expected, data.get("layers"), data.get("order"), data.get("removed"),
                                          from_template=data.get("fromTemplate") is True)
    except FileNotFoundError as exc:
        return fail(str(exc), 404)
    except main_design.DesignConflict as exc:
        return fail(str(exc), 409)
    except (ValueError, KeyError) as exc:
        return fail(str(exc))
    return ok({
        "title": meta.get("title", ""), "record": main_design.editable_record(record),
        "revision": main_design.revision(record), "library": main_design.library(task_id),
    })


@app.route("/api/health")
def health():
    return ok({"name": "淘宝商品素材采集与创作工具", "version": "1.0.0", "tasks": len(storage.list_tasks())})


@app.route("/api/settings")
def get_settings():
    settings = copy.deepcopy(config.load_settings())
    if settings.get("download", {}).get("cookie"):
        settings["download"]["cookie"] = "__SET__"
    if settings.get("ai", {}).get("api_key"):
        settings["ai"]["api_key"] = "__SET__"
    return ok(settings)


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = json_body()
    download = dict(data.get("download") or {})
    if "cookie" in download:
        value = str(download["cookie"]).strip()
        if value in ("__SET__", "__KEEP__"):
            download.pop("cookie")
        elif value == "__CLEAR__":
            download["cookie"] = ""
    ai = dict(data.get("ai") or {})
    if "api_key" in ai:
        value = str(ai["api_key"]).strip()
        if value in ("__SET__", "__KEEP__"):
            ai.pop("api_key")
        elif value == "__CLEAR__":
            ai["api_key"] = ""
    update = dict(data)
    if download:
        update["download"] = download
    if ai:
        update["ai"] = ai
    for kind, spec in (update.get("specs") or {}).items():
        if not isinstance(spec, dict):
            continue
        for key in ("width", "height", "max_height", "segment_height", "max_bytes", "target_bytes"):
            if key in spec:
                try:
                    spec[key] = int(spec[key])
                except (TypeError, ValueError):
                    return fail(f"{kind}.{key} 必须是数字")
    settings = config.save_settings(update)
    safe = copy.deepcopy(settings)
    if safe.get("download", {}).get("cookie"):
        safe["download"]["cookie"] = "__SET__"
    if safe.get("ai", {}).get("api_key"):
        safe["ai"]["api_key"] = "__SET__"
    return ok(safe)


@app.route("/api/templates")
def get_templates():
    return ok(config.load_templates())


@app.route("/api/ai/status")
def ai_status():
    return ok(ai.status(config.load_settings().get("ai", {})))


@app.route("/api/tasks")
def list_tasks():
    return ok(storage.list_tasks())


def _start_collect(task_id: str, url: str, cookie: str, settings: dict):
    def progress(done: int, total: int):
        def _update(meta):
            meta["progress"] = {"done": done, "total": total}
            return meta

        storage.update_meta(task_id, _update)

    def worker():
        try:
            collector.collect_from_url(task_id, url, settings, cookie)
        except Exception as exc:
            storage.set_status(task_id, "failed", "采集失败", error=str(exc))

            def _log_failure(meta, error=exc):
                storage.add_log(meta, f"采集失败：{error}", "error")
                return meta

            storage.update_meta(task_id, _log_failure)
        finally:
            with JOB_LOCK:
                JOBS.pop(task_id, None)

    with JOB_LOCK:
        if task_id in JOBS and JOBS[task_id].is_alive():
            return False
        thread = threading.Thread(target=worker, daemon=True, name=f"collect-{task_id}")
        JOBS[task_id] = thread
        thread.start()
    return True


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = json_body()
    settings = config.load_settings()
    mode = str(data.get("mode") or "manual")
    if mode == "url":
        url = str(data.get("url") or "").strip()
        if not url:
            return fail("请填写 1688 商品链接")
        offer_id = collector.extract_offer_id(url)
        meta = storage.create_task(
            offer_id=offer_id,
            title=str(data.get("title") or f"1688商品_{offer_id or '链接'}"),
            source_url=url,
            category=str(data.get("category") or ""),
        )
        cookie = str(data.get("cookie") or "").strip() or str(settings.get("download", {}).get("cookie", ""))
        _start_collect(meta["id"], url, cookie, settings)
        return ok({"id": meta["id"], "status": "collecting"}, 201)
    if mode == "folder":
        folder = str(data.get("folder") or "").strip()
        if not folder:
            return fail("请填写本机素材文件夹路径")
        try:
            plan = collector.scan_folder(folder)
        except Exception as exc:
            return fail(str(exc))
        meta = storage.create_task(
            offer_id=plan.get("offerId", ""),
            title=plan.get("title") or Path(folder).name,
            source_url=plan.get("sourceUrl", ""),
            price=plan.get("price", ""),
        )
        try:
            result = collector.collect_from_folder(meta["id"], folder, settings)
        except Exception as exc:
            storage.delete_task(meta["id"])
            return fail(str(exc))
        return ok({"id": result["id"], "status": result.get("status")}, 201)
    if mode == "manual":
        meta = storage.create_task(
            offer_id=str(data.get("offerId") or ""),
            title=str(data.get("title") or "手动新建商品"),
            source_url=str(data.get("sourceUrl") or ""),
            category=str(data.get("category") or ""),
        )
        return ok({"id": meta["id"], "status": meta["status"]}, 201)
    return fail(f"未知任务模式: {mode}")


@app.route("/api/tasks/import-pages", methods=["POST"])
def import_pages():
    uploads = request.files.getlist("files")
    if not uploads:
        return fail("请选择要导入的网页或 JSON 文件")
    parsed_files = []
    for upload in uploads:
        data = upload.read()
        if not data:
            continue
        parsed_files.append((upload.filename or "upload.html", data))
    if not parsed_files:
        return fail("文件内容为空")
    merged = collector.merge_results([collector.parse_bytes(name, data) for name, data in parsed_files])
    meta = storage.create_task(
        offer_id=merged.get("offerId", ""),
        title=merged.get("title") or "网页导入商品",
        source_url=merged.get("sourceUrl", ""),
        price=merged.get("price", ""),
    )
    try:
        result = collector.collect_from_page_files(meta["id"], parsed_files, config.load_settings())
    except Exception as exc:
        storage.delete_task(meta["id"])
        return fail(str(exc))
    return ok({"id": result["id"], "status": result.get("status")}, 201)


@app.route("/api/tasks/import-zip", methods=["POST"])
def import_zip():
    upload = request.files.get("file")
    if not upload:
        return fail("请选择 zip 压缩包")
    fd, temp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        upload.save(temp_path)
        meta = storage.create_task(title=Path(upload.filename or "素材包").stem)
        try:
            result = collector.collect_from_zip(meta["id"], temp_path, config.load_settings())
        except Exception as exc:
            storage.delete_task(meta["id"])
            return fail(str(exc))
        return ok({"id": result["id"], "status": result.get("status")}, 201)
    finally:
        Path(temp_path).unlink(missing_ok=True)


@app.route("/api/tasks/demo", methods=["POST"])
def import_demo():
    demo_dir = config.ROOT / "1688_1041092037687"
    if not demo_dir.is_dir():
        return fail("示例文件夹不存在，请使用其他采集方式")
    plan = collector.scan_folder(str(demo_dir))
    meta = storage.create_task(
        offer_id=plan.get("offerId", ""),
        title=plan.get("title") or "示例商品",
        source_url=plan.get("sourceUrl", ""),
        price=plan.get("price", ""),
    )
    try:
        result = collector.collect_from_folder(meta["id"], str(demo_dir), config.load_settings())
    except Exception as exc:
        storage.delete_task(meta["id"])
        return fail(str(exc))
    return ok({"id": result["id"], "status": result.get("status")}, 201)


@app.route("/api/tasks/<task_id>")
def get_task(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    return ok({
        "meta": meta,
        "stats": storage.get_stats(task_id, meta),
        "raw": storage.scan_raw(task_id),
        "outputs": storage.scan_outputs(task_id),
    })


@app.route("/api/tasks/<task_id>/design", methods=["GET"])
def get_design(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    return ok({"design": meta.get("design", {}), "versions": meta.get("designVersions", [])})


@app.route("/api/tasks/<task_id>/design", methods=["POST"])
def save_design(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    design = data.get("design")
    if not isinstance(design, dict):
        return fail("design 必须是对象")
    current = meta.get("design") if isinstance(meta.get("design"), dict) else {}
    versions = list(meta.get("designVersions") or [])
    versions.append({"design": current, "at": storage.now(), "note": str(data.get("note") or "")[:120]})
    versions = versions[-30:]
    meta["design"] = design
    meta["designVersions"] = versions
    storage.add_log(meta, "保存可编辑设计工程")
    storage.save_meta(task_id, meta)
    return ok({"design": design, "versions": versions})


@app.route("/api/tasks/<task_id>/ai/analyze", methods=["POST"])
def ai_analyze(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    result = ai.analyze_product(meta, storage.scan_raw(task_id))
    settings = config.load_settings().get("ai", {})
    if settings.get("enabled"):
        prompt = (
            "请只返回简短的商品卖点和视觉风格建议，不要虚构材质、尺寸或功能。"
            f"商品标题：{meta.get('title', '')}\n商品类目：{meta.get('category', '')}"
        )
        model_text = ai.complete(prompt, settings)
        if model_text:
            result["modelInsight"] = model_text[:4000]
            result["source"] = "model+local-rule"

    def _update(meta_obj):
        meta_obj["aiAnalysis"] = result
        storage.add_log(meta_obj, "完成商品本地分析")
        return meta_obj

    storage.update_meta(task_id, _update)
    return ok(result)


@app.route("/api/tasks/<task_id>/ai/assistant/preview", methods=["POST"])
def ai_assistant_preview(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    instruction = str(json_body().get("instruction") or "").strip()
    if not instruction:
        return fail("请输入要修改的设计要求")
    return ok(ai.parse_instruction(instruction))


@app.route("/api/tasks/<task_id>/ai/assistant/apply", methods=["POST"])
def ai_assistant_apply(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else ai.parse_instruction(str(data.get("instruction") or ""))
    if not plan.get("operations"):
        return fail("没有可应用的设计修改")
    updated = ai.apply_instruction(meta, plan)
    versions = list(meta.get("designVersions") or [])
    versions.append({"design": dict(meta.get("design") or {}), "at": storage.now(), "note": "AI 设计修改前"})
    updated["designVersions"] = versions[-30:]
    history = list(meta.get("aiHistory") or [])
    history.append({"before": {"design": dict(meta.get("design") or {})}, "plan": plan, "at": storage.now()})
    updated["aiHistory"] = history
    updated["aiRedoHistory"] = []
    storage.save_meta(task_id, updated)
    return ok({"design": updated.get("design", {}), "history": updated["aiHistory"]})


@app.route("/api/tasks/<task_id>/ai/assistant/undo", methods=["POST"])
def ai_assistant_undo(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    history = list(meta.get("aiHistory") or [])
    if not history:
        return fail("没有可撤销的设计修改")
    entry = history.pop()
    redo = list(meta.get("aiRedoHistory") or [])
    redo.append({"design": dict(meta.get("design") or {}), "entry": entry})
    meta["design"] = dict((entry.get("before") or {}).get("design") or {})
    meta["aiHistory"] = history
    meta["aiRedoHistory"] = redo
    storage.save_meta(task_id, meta)
    return ok({"design": meta["design"], "history": history, "canRedo": True})


@app.route("/api/tasks/<task_id>/ai/assistant/redo", methods=["POST"])
def ai_assistant_redo(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    redo = list(meta.get("aiRedoHistory") or [])
    if not redo:
        return fail("没有可重做的设计修改")
    item = redo.pop()
    entry = item.get("entry") or {}
    history = list(meta.get("aiHistory") or [])
    history.append(entry)
    meta["design"] = dict(item.get("design") or {})
    meta["aiHistory"] = history
    meta["aiRedoHistory"] = redo
    storage.save_meta(task_id, meta)
    return ok({"design": meta["design"], "history": history, "canRedo": bool(redo)})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    storage.delete_task(task_id)
    return ok({"deleted": task_id})


@app.route("/api/tasks/<task_id>/collect", methods=["POST"])
def retry_collect(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    url = str(data.get("url") or meta.get("sourceUrl") or "").strip()
    if not url:
        return fail("没有可重试的来源链接，请新建任务或使用导入方式")
    cookie = str(data.get("cookie") or "").strip() or str(config.load_settings().get("download", {}).get("cookie", ""))
    storage.set_status(task_id, "collecting", "重新采集")
    _start_collect(task_id, url, cookie, config.load_settings())
    return ok({"status": "collecting"})


@app.route("/api/tasks/<task_id>/upload", methods=["POST"])
def upload_images(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    kind = str(request.form.get("kind") or "main")
    uploads = request.files.getlist("files")
    if not uploads:
        return fail("请选择图片文件")
    saved = []
    for upload in uploads:
        try:
            saved.append(storage.save_upload(task_id, kind, upload.filename or "image.jpg", upload))
        except Exception as exc:
            return fail(f"{upload.filename}: {exc}")
    meta = storage.load_meta(task_id)
    meta.setdefault("raw", {}).setdefault(kind, []).extend(saved)
    meta = collector.refresh_meta_from_files(task_id, meta)
    storage.add_log(meta, f"上传 {kind} 图片 {len(saved)} 张")
    storage.save_meta(task_id, meta)
    return ok({"saved": len(saved), "files": [item["file"] for item in saved]})


@app.route("/api/tasks/<task_id>/raw/classify", methods=["POST"])
def classify_review_image(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    try:
        record = storage.classify_review_file(
            task_id,
            str(data.get("file") or ""),
            str(data.get("kind") or ""),
            str(data.get("name") or "").strip(),
        )
    except (FileNotFoundError, ValueError) as exc:
        return fail(str(exc))
    return ok({"file": record["file"], "kind": data.get("kind")})


@app.route("/api/tasks/<task_id>/raw", methods=["DELETE"])
def delete_raw_image(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    try:
        record = storage.delete_raw_file(task_id, str(data.get("file") or ""))
    except FileNotFoundError as exc:
        return fail(str(exc), 404)
    except ValueError as exc:
        return fail(str(exc))
    meta = collector.refresh_meta_from_files(task_id)
    return ok({"file": record["file"], "kind": record["kind"], "raw": meta["raw"]})


@app.route("/api/tasks/<task_id>/open-folder", methods=["POST"])
def open_folder(task_id: str):
    try:
        path = storage.task_path(task_id)
    except (FileNotFoundError, ValueError) as exc:
        return fail(str(exc), 404)
    subpath = str(json_body().get("subpath") or "").strip()
    if subpath:
        candidate = (path / subpath).resolve()
        if path.resolve() not in candidate.parents:
            return fail("非法文件夹路径")
        if candidate.is_dir():
            path = candidate
    if hasattr(os, "startfile"):
        try:
            os.startfile(str(path))
        except OSError as exc:
            return fail(f"无法打开文件夹: {exc}")
        return ok({"opened": str(path)})
    return fail("当前系统不支持自动打开文件夹", 501)


@app.route("/api/tasks/<task_id>/suggestions")
def suggestions(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    return ok(templates.default_slot_options(task_id))


@app.route("/api/tasks/<task_id>/preview/colors", methods=["POST"])
def preview_colors(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    try:
        result = templates.render_color_preview(task_id, json_body(), meta)
    except Exception as exc:
        return fail(str(exc))
    return ok(result)


@app.route("/api/tasks/<task_id>/generate/main", methods=["POST"])
def generate_main(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    try:
        records = templates.render_main_slot(task_id, int(data.get("slot", 1)), data)
    except Exception as exc:
        return fail(str(exc))
    return ok(records)


@app.route("/api/tasks/<task_id>/generate/main/all", methods=["POST"])
def generate_main_all(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    slots = data.get("slots") or None
    variants = data.get("variants")
    if variants and slots:
        for slot in slots:
            slot["variants"] = variants
    try:
        result = templates.render_all_main(task_id, slots)
    except Exception as exc:
        return fail(str(exc))
    return ok(result)


@app.route("/api/tasks/<task_id>/generate/detail", methods=["POST"])
def generate_detail(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    try:
        records = templates.render_detail(task_id, json_body())
    except Exception as exc:
        return fail(str(exc))
    return ok(records)


@app.route("/api/tasks/<task_id>/generate/sku", methods=["POST"])
def generate_sku(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    try:
        records = templates.render_sku(task_id, json_body())
    except Exception as exc:
        return fail(str(exc))
    return ok(records)


@app.route("/api/tasks/<task_id>/generate/white", methods=["POST"])
def generate_white(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    try:
        records = templates.render_white(task_id, json_body())
    except Exception as exc:
        return fail(str(exc))
    return ok(records)


@app.route("/api/tasks/<task_id>/keywords/analyze", methods=["POST"])
def analyze_keywords(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    titles = data.get("titles")
    if not titles:
        text = str(data.get("text") or "")
        titles = [line.strip() for line in text.splitlines() if line.strip()]
    if not isinstance(titles, list):
        return fail("竞品标题应为列表或每行一条的文本")
    titles = [str(title).strip()[:300] for title in titles[:300] if str(title).strip()]
    product_title = str(data.get("productTitle") or meta.get("title", ""))
    new_product = data.get("newProduct") is True
    if new_product:
        product_title = str(data.get("productTitle") or "").strip()[:300]
        if not product_title:
            return fail("请填写自定义商品标题")
    image_tags = data.get("imageTags") or meta.get("keywords", {}).get("imageTags") or {}
    color_tags = keywords.analyze_task_colors(task_id, storage.scan_raw(task_id))
    analysis = keywords.analyze(list(titles or []), product_title, image_tags, color_tags)
    analysis["colorTags"] = color_tags
    if new_product:
        facts = str(data.get("titleFacts") or "")[:800]
        preferred = data.get("words")
        analysis["titles"] = keywords.recommend_new_titles(
            product_title, list(titles or []), facts,
            [word for word in preferred if isinstance(word, str)] if isinstance(preferred, list) else None,
        )

    def _update(meta_obj):
        store = meta_obj.setdefault("keywords", {})
        store.update({
            "competitorTitles": list(titles or []),
            "productTitle": product_title,
            "analyzedAt": storage.now(),
            "categories": analysis.get("categories", {}),
            "imageTags": analysis.get("imageTags", {}),
            "colorTags": color_tags,
            "titles": analysis.get("titles", []),
            "bannedFound": analysis.get("bannedFound", []),
            "brandFound": analysis.get("brandFound", []),
            "stats": analysis.get("stats", {}),
        })
        if new_product:
            store["titleFacts"] = facts
            if store.get("selectedTitle") not in {item["title"] for item in analysis["titles"]}:
                store["selectedTitle"] = ""
        storage.add_log(meta_obj, f"关键词分析完成：{len(titles or [])} 条竞品标题")
        return meta_obj

    storage.update_meta(task_id, _update)
    storage.write_task_aux(task_id, storage.load_meta(task_id))
    return ok(analysis)


@app.route("/api/tasks/<task_id>/keywords/titles", methods=["POST"])
def generate_titles(task_id: str):
    meta, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    words = [str(word) for word in (data.get("words") or []) if str(word).strip()]
    product_title = str(data.get("productTitle") or meta.get("title", ""))
    titles = keywords.generate_titles_from_words(words, product_title)

    def _update(meta_obj):
        meta_obj.setdefault("keywords", {})["titles"] = titles
        return meta_obj

    storage.update_meta(task_id, _update)
    storage.write_task_aux(task_id, storage.load_meta(task_id))
    return ok(titles)


@app.route("/api/tasks/<task_id>/keywords/save", methods=["POST"])
def save_keywords(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    if "titles" in data:
        if not isinstance(data["titles"], list) or any(
                not isinstance(item, dict) or not isinstance(item.get("title"), str) for item in data["titles"]):
            return fail("标题候选格式无效")
        if any(len(item["title"]) > keywords.NEW_TITLE_LIMIT for item in data["titles"]):
            return fail("请将超长标题调整为 30 字以内")
        for item in data["titles"]:
            item["length"] = len(item["title"])

    def _update(meta_obj):
        store = meta_obj.setdefault("keywords", {})
        for key in ("imageTags", "titles", "selectedTitle", "competitorTitles", "productTitle", "titleFacts"):
            if key in data:
                store[key] = data[key]
        storage.add_log(meta_obj, "关键词与标题已保存")
        return meta_obj

    meta = storage.update_meta(task_id, _update)
    storage.write_task_aux(task_id, meta)
    return ok({"saved": True})


@app.route("/api/tasks/<task_id>/image/edit", methods=["POST"])
def edit_image(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    rel = str(data.get("file") or "").strip()
    data_url = str(data.get("dataUrl") or "").strip()
    save_as_new = bool(data.get("saveAsNew"))
    note = storage.safe_filename(str(data.get("note") or "").strip(), "", 24)
    is_raw = rel.startswith("raw/")
    is_output = rel.startswith("output/")
    if not (is_raw or is_output):
        return fail("只能编辑原始素材或成品图")
    if not data_url.startswith("data:image/"):
        return fail("图片数据格式错误")
    try:
        task_dir = storage.task_path(task_id)
    except (FileNotFoundError, ValueError) as exc:
        return fail(str(exc), 404)
    path = (task_dir / rel).resolve()
    if task_dir.resolve() not in path.parents or not path.is_file():
        return fail("图片文件不存在", 404)
    try:
        header, encoded = data_url.split(",", 1)
        use_png = "image/png" in header.lower()
        image_bytes = base64.b64decode(encoded)
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGBA" if use_png else "RGB")
    except Exception as exc:
        return fail(f"图片数据无法读取: {exc}")
    extension = ".png" if use_png else ".jpg"
    labels = {
        "main_pc": "主图PC",
        "main_mobile": "主图手机",
        "white": "白底图",
        "detail": "详情图",
        "sku": "SKU图",
        "edited": "编辑图",
        "main": "主图原图",
        "review": "待确认原图",
    }
    parts = Path(rel).parts
    kind = parts[1] if len(parts) > 1 else ""
    label = labels.get(kind, "图片")
    stem = Path(rel).stem
    if kind and stem.startswith(kind + "_"):
        stem = stem[len(kind) + 1:]
    stem = storage.safe_filename(stem, "image", 36)
    name_parts = [label, stem]
    if note:
        name_parts.append(note)
    edited_dir = task_dir / "output" / "edited"
    edited_dir.mkdir(parents=True, exist_ok=True)
    overwrite_edited = is_output and not save_as_new and path.parent.name == "edited"
    target = path if overwrite_edited else edited_dir / f"{'_'.join(name_parts)}_edited{extension}"
    if not overwrite_edited and (save_as_new or is_raw):
        index = 1
        base = target
        while target.exists():
            index += 1
            target = base.with_name(f"{base.stem}_{index}{base.suffix}")
    if use_png:
        image.save(target, "PNG", optimize=True)
    else:
        image.save(target, "JPEG", quality=92, optimize=True)
    info = {
        "file": target.relative_to(task_dir).as_posix(),
        "width": image.width,
        "height": image.height,
        "bytes": target.stat().st_size,
        "issues": [],
        "editedAt": storage.now(),
        "originFile": rel,
        "note": note,
    }
    if is_output and not save_as_new:
        storage.update_output_record(task_id, rel, info)
    else:
        def _append(meta_obj: dict):
            edited = meta_obj.setdefault("outputs", {}).setdefault("edited", [])
            if not isinstance(edited, list):
                edited = list(edited.values()) if isinstance(edited, dict) else []
                meta_obj["outputs"]["edited"] = edited
            edited.append(info)
            storage.add_log(meta_obj, f"保存编辑图片：{info['file']}")
            return meta_obj

        storage.update_meta(task_id, _append)
    return ok(info)


@app.route("/api/tasks/<task_id>/image/remove-bg", methods=["POST"])
def remove_background(task_id: str):
    """基础抠图：按边角背景色去除纯色/浅色背景，复杂背景需人工处理。"""
    _, error = _task_or_error(task_id)
    if error:
        return error
    data = json_body()
    rel = str(data.get("file") or "").strip()
    tolerance = max(5, min(120, int(data.get("tolerance", 36))))
    try:
        task_dir = storage.task_path(task_id)
    except (FileNotFoundError, ValueError) as exc:
        return fail(str(exc), 404)
    path = (task_dir / rel).resolve()
    if task_dir.resolve() not in path.parents or not path.is_file():
        return fail("图片文件不存在", 404)
    try:
        with Image.open(path) as opened:
            source = opened.convert("RGBA")
    except Exception as exc:
        return fail(f"图片无法读取: {exc}")
    cutout, background = imaging.remove_edge_background(source, tolerance)
    out_dir = task_dir / "output" / "cutout"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{storage.timestamp_slug()}_{Path(rel).stem}_cutout.png"
    cutout.save(target, "PNG", optimize=True)
    return ok({
        "file": target.relative_to(task_dir).as_posix(),
        "method": "color-distance",
        "background": background,
    })


@app.route("/api/tasks/<task_id>/export", methods=["POST"])
def export_task(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    return exporter.build_export(task_id, json_body())


@app.route("/api/tasks/<task_id>/export/download")
def download_export(task_id: str):
    _, error = _task_or_error(task_id)
    if error:
        return error
    info = exporter.latest_export(task_id)
    if not info:
        return fail("还没有导出过素材包")
    path = storage.task_path(task_id) / info["file"]
    if not path.is_file():
        return fail("素材包文件不存在", 404)
    return send_file(path, as_attachment=True, download_name=info["downloadName"])


@app.route("/media/<task_id>/<path:relpath>")
def media(task_id: str, relpath: str):
    try:
        task_dir = storage.task_path(task_id)
    except (FileNotFoundError, ValueError):
        abort(404)
    path = (task_dir / relpath).resolve()
    if task_dir.resolve() not in path.parents or not path.is_file():
        abort(404)
    thumb_width = request.args.get("w")
    if thumb_width and path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        try:
            width = max(80, min(1200, int(thumb_width)))
        except ValueError:
            width = 360
        key = hashlib.sha1(f"{relpath}|{path.stat().st_mtime_ns}|{width}".encode("utf-8")).hexdigest()[:20]
        thumb_dir = task_dir / ".thumbs"
        thumb_path = thumb_dir / f"{key}.jpg"
        if not thumb_path.is_file():
            imaging.thumbnail(path, thumb_path, width)
        path = thumb_path
    mimetype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return send_file(path, mimetype=mimetype, conditional=True)


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 30):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.close()
            return port
        except OSError:
            sock.close()
    return preferred


def recover_interrupted() -> None:
    for summary in storage.list_tasks():
        if summary.get("status") in ("collecting", "generating"):
            try:
                storage.set_status(
                    summary["id"], "failed", "采集中断",
                    error="服务重启导致任务中断，请点击“重新采集”重试",
                )
            except Exception:
                pass


def main() -> None:
    config.ensure_dirs()
    parser = argparse.ArgumentParser(description="淘宝商品素材采集与创作工具")
    parser.add_argument("--host", default="", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="监听端口，默认读取配置")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()
    settings = config.load_settings()
    host = args.host or str(settings.get("server", {}).get("host", "127.0.0.1"))
    preferred = args.port or int(settings.get("server", {}).get("port", 8765))
    port = pick_port(host, preferred)
    recover_interrupted()
    url = f"http://{host}:{port}"
    print("=" * 60)
    print("  淘宝商品素材采集与创作工具 已启动")
    print(f"  打开浏览器访问: {url}")
    print("  停止服务: 在此窗口按 Ctrl+C")
    print("=" * 60)
    if not args.no_browser and settings.get("server", {}).get("open_browser", True):
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()

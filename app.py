# -*- coding: utf-8 -*-
"""淘宝商品素材采集与创作工具 · 本地 Web 服务入口。"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import io
import mimetypes
import numpy as np
import os
import shutil
import socket
import sys
import tempfile
import threading
import traceback
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image
from werkzeug.exceptions import HTTPException

from core import collector, config, exporter, imaging, keywords, storage, templates

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
    meta = collector.refresh_meta_from_files(task_id, meta)
    storage.add_log(meta, f"上传 {kind} 图片 {len(saved)} 张")
    storage.save_meta(task_id, meta)
    return ok({"saved": len(saved), "files": [item["file"] for item in saved]})


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
    product_title = str(data.get("productTitle") or meta.get("title", ""))
    image_tags = data.get("imageTags") or meta.get("keywords", {}).get("imageTags") or {}
    color_tags = keywords.analyze_task_colors(task_id, storage.scan_raw(task_id))
    analysis = keywords.analyze(list(titles or []), product_title, image_tags, color_tags)
    analysis["colorTags"] = color_tags

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

    def _update(meta_obj):
        store = meta_obj.setdefault("keywords", {})
        for key in ("imageTags", "titles", "selectedTitle", "competitorTitles", "productTitle"):
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
    if not rel.startswith("output/"):
        return fail("只能编辑成品图，不能修改原图")
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
    target = path
    if save_as_new:
        target = path.with_name(f"{path.stem}_edited{extension}")
        index = 2
        while target.exists():
            target = path.with_name(f"{path.stem}_edited_{index}{extension}")
            index += 1
    else:
        backup_dir = task_dir / "output" / ".backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{storage.timestamp_slug()}_{path.name}"
        shutil.copy2(path, backup)
        if use_png and target.suffix.lower() in (".jpg", ".jpeg"):
            target = target.with_suffix(".png")
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
    }
    storage.update_output_record(task_id, rel, info)
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
            source = opened.convert("RGB")
    except Exception as exc:
        return fail(f"图片无法读取: {exc}")
    width, height = source.size
    arr = np.asarray(source).astype(np.int16)
    border = np.concatenate([
        arr[:3, :, :].reshape(-1, 3),
        arr[-3:, :, :].reshape(-1, 3),
        arr[:, :3, :].reshape(-1, 3),
        arr[:, -3:, :].reshape(-1, 3),
    ], axis=0)
    background = np.median(border, axis=0)
    distance = np.sqrt(np.sum((arr - background) ** 2, axis=2))
    low = float(tolerance)
    high = float(tolerance) * 1.8
    alpha = np.clip((distance - low) / max(1.0, high - low), 0, 1)
    alpha = (alpha * 255).astype(np.uint8)
    rgba = np.dstack([arr.astype(np.uint8), alpha])
    cutout = Image.fromarray(rgba, "RGBA")
    out_dir = task_dir / "output" / "cutout"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{storage.timestamp_slug()}_{Path(rel).stem}_cutout.png"
    cutout.save(target, "PNG", optimize=True)
    return ok({
        "file": target.relative_to(task_dir).as_posix(),
        "method": "color-distance",
        "background": [int(value) for value in background],
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

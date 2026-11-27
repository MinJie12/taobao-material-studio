# -*- coding: utf-8 -*-
"""图片编辑和详情页工作台升级的回归测试。"""
from __future__ import annotations

import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app import app as flask_app
from core import imaging, storage, templates


def write_image(path: Path, color=(255, 0, 0), size=(200, 100)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", quality=92)
    return path


def png_data_url(width=200, height=100, color=(0, 0, 255)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class ImagingFocusTests(unittest.TestCase):
    def test_fit_cover_focus_can_move_crop_window(self):
        image = Image.new("RGB", (200, 100), (255, 0, 0))
        image.paste(Image.new("RGB", (100, 100), (0, 0, 255)), (100, 0))

        left = imaging.fit_cover_focus(image, (100, 100), zoom=1.0, offset_x=-1)
        right = imaging.fit_cover_focus(image, (100, 100), zoom=1.0, offset_x=1)

        self.assertEqual((255, 0, 0), left.getpixel((50, 50)))
        self.assertEqual((0, 0, 255), right.getpixel((50, 50)))

    def test_fit_contain_focus_supports_zoom_and_offset(self):
        image = Image.new("RGB", (200, 100), (255, 0, 0))
        zoomed = imaging.fit_contain_focus(image, (200, 100), padding=0, zoom=1.5, offset_y=1)
        self.assertEqual((200, 100), zoomed.size)


class MainSlotPhotoControlsTests(unittest.TestCase):
    def test_default_slot_options_include_photo_transform_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(offer_id="123", title="test")
                options = templates.default_slot_options(task["id"])["slots"][0]
        self.assertEqual(1, options["photo_zoom"])
        self.assertEqual(0, options["photo_x"])
        self.assertEqual(0, options["photo_y"])

    def test_saved_design_parameters_are_used_by_main_renderer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(title="test")
                source = write_image(storage.task_path(task["id"]) / "raw" / "main" / "main_01.jpg")
                storage.update_meta(task["id"], lambda meta: meta.update({"design": {"background": "#EAF2FF", "productScale": 1.2}}) or meta)
                rel = source.relative_to(storage.task_path(task["id"])).as_posix()
                result = templates.render_main_slot(task["id"], 1, {"source": rel, "variants": ["pc"], "show_text": False}, storage.load_meta(task["id"]))
                self.assertIn("pc", result)
                self.assertTrue((storage.task_path(task["id"]) / result["pc"]["file"]).is_file())


class ImageEditUpgradeTests(unittest.TestCase):
    def test_raw_image_edit_saves_to_unified_edited_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(offer_id="123", title="test")
                raw = write_image(storage.task_path(task["id"]) / "raw" / "main" / "main_01.jpg")
                original_bytes = raw.read_bytes()
                client = flask_app.test_client()
                response = client.post(
                    f"/api/tasks/{task['id']}/image/edit",
                    json={"file": "raw/main/main_01.jpg", "dataUrl": png_data_url(), "saveAsNew": False, "note": "新增", "isRaw": True},
                )
                self.assertEqual(200, response.status_code)
                data = response.json["data"]
                self.assertTrue(data["file"].startswith("output/edited/主图原图_"))
                self.assertTrue(raw.is_file())
                self.assertEqual(original_bytes, raw.read_bytes())
                meta = storage.load_meta(task["id"])
                edited = meta["outputs"]["edited"]
                self.assertEqual(1, len(edited))
                self.assertEqual(data["file"], edited[0]["file"])

    def test_output_image_overwrite_updates_record_and_uses_edited_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(offer_id="123", title="test")
                task_dir = storage.task_path(task["id"])
                output = write_image(task_dir / "output" / "main_pc" / "01.jpg")
                storage.update_meta(task["id"], lambda meta: meta["outputs"]["main_pc"].__setitem__(
                    "1", {"file": "output/main_pc/01.jpg", "issues": []}
                ))
                client = flask_app.test_client()
                response = client.post(
                    f"/api/tasks/{task['id']}/image/edit",
                    json={"file": "output/main_pc/01.jpg", "dataUrl": png_data_url(), "saveAsNew": False},
                )
                self.assertEqual(200, response.status_code)
                data = response.json["data"]
                self.assertTrue(data["file"].startswith("output/edited/主图PC_"))
                self.assertEqual(data["file"], storage.load_meta(task["id"])["outputs"]["main_pc"]["1"]["file"])
                self.assertTrue(output.is_file())


class NewProductTitleTests(unittest.TestCase):
    def test_recommendations_use_verified_phrases_and_save_five_distinct_titles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(title="商品")["id"]
                client = flask_app.test_client()
                title = "女式高腰直筒瑜伽裤"
                response = client.post(f"/api/tasks/{task}/keywords/analyze", json={
                    "newProduct": True, "productTitle": title,
                    "text": "高腰瑜伽裤防水速干\n高腰瑜伽裤侧边口袋适合健身\n高腰瑜伽裤高弹面料",
                    "titleFacts": "柔软亲肤，侧边口袋，高弹面料，普拉提训练，日常通勤，松紧腰设计，适合健身",
                    "words": ["防水", "侧边口袋"],
                })
                self.assertEqual(200, response.status_code, response.get_json())
                titles = response.get_json()["data"]["titles"]
                self.assertEqual(5, len({item["title"] for item in titles}))
                for item in titles:
                    self.assertEqual(30, len(item["title"]))
                    self.assertIn(title, item["title"])
                    self.assertNotIn("防水", item["title"])
                    self.assertNotIn("速干", item["title"])
                self.assertEqual(titles, storage.load_meta(task)["keywords"]["titles"])
                self.assertEqual(400, client.post(f"/api/tasks/{task}/keywords/save", json={
                    "titles": [{"title": "长" * 31}],
                }).status_code)

    def test_sparse_title_is_not_padded_with_competitor_claims(self):
        from core import keywords

        result = keywords.recommend_new_titles("女式高腰直筒瑜伽裤", ["高腰直筒瑜伽裤保暖防水"])
        self.assertEqual(["女式高腰直筒瑜伽裤"], [item["title"] for item in result])


class DetailWorkbenchTests(unittest.TestCase):
    def test_automatic_order_uses_filename_roles_and_manual_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(title="test")
                root = storage.task_path(task["id"])
                sources = [
                    "raw/detail/detail_03.jpg", "raw/detail/detail_02.jpg", "raw/detail/卖点.jpg",
                    "raw/detail/detail_01.jpg", "raw/detail/商品全貌.jpg",
                ]
                for source in sources:
                    write_image(root / source)
                storage.update_meta(task["id"], lambda meta: meta["raw"]["detail"].append(
                    {"file": sources[0], "name": "尺码表"}
                ))
                spec = {"width": 200, "segment_height": 200, "max_height": 200}
                with patch.object(templates, "_spec", return_value=spec):
                    automatic = templates.beautify_detail_page(task["id"], sources, auto_order=True)
                    manual = templates.beautify_detail_page(task["id"], sources)
                expected = [sources[index] for index in (4, 2, 1, 3, 0)]
                self.assertEqual(expected, [record["source"] for record in automatic])
                self.assertEqual(sources, [record["source"] for record in manual])
                self.assertTrue(all(record["autoOrdered"] for record in automatic))
                self.assertFalse(any(record["autoOrdered"] for record in manual))

    def test_smart_segmentation_avoids_detail_when_a_quiet_cut_is_nearby(self):
        image = Image.new("RGB", (80, 280), "white")
        draw = ImageDraw.Draw(image)
        for row in range(135, 146, 2):
            draw.line((0, row, 79, row), fill="black")
        ranges = imaging.detail_segment_ranges(image, 160)
        self.assertEqual(2, len(ranges))
        self.assertNotIn(ranges[0][1], range(135, 146))
        self.assertEqual(ranges[0][1], ranges[1][0])
        self.assertEqual((0, 280), (ranges[0][0], ranges[-1][1]))
        self.assertTrue(all(0 < bottom - top <= 160 for top, bottom in ranges))

    def test_one_click_detail_uses_specs_and_preserves_previous_output_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(title="test")
                root = storage.task_path(task["id"])
                source = "raw/detail/long.png"
                Image.new("RGB", (150, 420), (40, 48, 55)).save(root / source)
                raw = (root / source).read_bytes()
                spec = {"width": 300, "segment_height": 330, "max_height": 300,
                        "max_bytes": 50_000, "target_bytes": 30_000}
                client = flask_app.test_client()
                endpoint = f"/api/tasks/{task['id']}/generate/detail"
                with patch.object(templates, "_spec", return_value=spec):
                    response = client.post(endpoint, json={
                        "sources": [source], "beautify": True, "make_cover": True, "width": 100,
                    })
                    self.assertEqual(200, response.status_code, response.get_json())
                    results = response.get_json()["data"]
                    self.assertEqual(840, sum(record["height"] for record in results))
                    for record in results:
                        self.assertEqual("detail_beauty", record["template"])
                        self.assertEqual(source, record["source"])
                        self.assertEqual(300, record["width"])
                        self.assertLessEqual(record["height"], 300)
                        self.assertLessEqual(record["bytes"], 50_000)
                        self.assertIn("150px", record["issues"][0])
                    self.assertEqual(raw, (root / source).read_bytes())
                    (root / "raw/detail/broken.jpg").write_bytes(b"invalid image")
                    failed = client.post(endpoint, json={
                        "beautify": True, "sources": [source, "raw/detail/broken.jpg"],
                    })
                    self.assertEqual(400, failed.status_code)
                    self.assertEqual(results, storage.load_meta(task["id"])["outputs"]["detail"])
                    self.assertTrue(all((root / record["file"]).is_file() for record in results))

    def test_detail_generation_preserves_selected_source_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(offer_id="123", title="test")
                rel_first = write_image(storage.task_path(task["id"]) / "raw" / "detail" / "detail_01.jpg", (255, 0, 0)).relative_to(storage.task_path(task["id"])).as_posix()
                rel_second = write_image(storage.task_path(task["id"]) / "raw" / "detail" / "detail_02.jpg", (0, 255, 0)).relative_to(storage.task_path(task["id"])).as_posix()
                records = templates.render_detail(
                    task["id"], {"sources": [rel_second, rel_first], "width": 100, "segment_height": 100, "enhance": False, "make_cover": False}
                )
                self.assertEqual([rel_second, rel_first], [record["source"] for record in records])


if __name__ == "__main__":
    unittest.main()

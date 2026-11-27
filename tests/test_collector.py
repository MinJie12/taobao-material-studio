import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from werkzeug.datastructures import FileStorage

from app import app as flask_app
from core import collector, storage


class CollectorTests(unittest.TestCase):
    def test_unclassified_page_images_are_not_guessed_as_main_or_detail(self):
        images = "".join(
            f'<img src="https://cbu01.alicdn.com/img/{index}.jpg">'
            for index in range(8)
        )

        parsed = collector.parse_html(f"<html><body>{images}</body></html>")

        self.assertEqual([], parsed["main"])
        self.assertEqual([], parsed["detail"])
        self.assertEqual(8, len(parsed["unknown"]))

    def test_sku_images_already_found_in_data_are_not_added_to_review(self):
        html = """
        <script>
        window.__INIT_DATA__ = {
          "offerImgList": ["https://cbu01.alicdn.com/img/main.jpg"],
          "skuImages": [{"name": "蓝色", "url": "https://cbu01.alicdn.com/img/sku.jpg"}]
        };
        </script>
        <img src="https://cbu01.alicdn.com/img/sku.jpg">
        """

        parsed = collector.parse_html(html)

        self.assertEqual(1, len(parsed["main"]))
        self.assertEqual([{"name": "蓝色", "url": "https://cbu01.alicdn.com/img/sku.jpg"}], parsed["sku"])
        self.assertEqual([], parsed["unknown"])

    def test_1688_context_and_product_regions_are_classified_automatically(self):
        context_html = """
        <script>
        window.context = {"result":{"data":{
          "gallery":{"fields":{"offerImgList":["https://cbu01.alicdn.com/img/context-main.jpg"]}},
          "skuModel":{"skuProps":[{"name":"颜色","values":[{"name":"蓝色","imageUrl":"https://cbu01.alicdn.com/img/context-sku.jpg"}]}]},
          "description":{"fields":{"detailUrl":"https://desc.alicdn.com/item/description.html"}}
        }}};
        </script>
        """
        parsed_context = collector.parse_html(context_html, "https://detail.1688.com/offer/12345678.html")

        self.assertIn("https://cbu01.alicdn.com/img/context-main.jpg", parsed_context["main"])
        self.assertIn(
            {"name": "蓝色", "url": "https://cbu01.alicdn.com/img/context-sku.jpg"},
            parsed_context["sku"],
        )
        self.assertEqual(["https://desc.alicdn.com/item/description.html"], parsed_context["detailUrls"])

        markup = """
        <div id="dt-tab"><img src="https://cbu01.alicdn.com/img/dom-main.jpg"></div>
        <div class="pc-sku-wrapper"><div class="prop-item-inner-wrapper">
          <img src="https://cbu01.alicdn.com/img/dom-sku.jpg">
        </div></div>
        <div class="html-description"><img src="https://cbu01.alicdn.com/img/dom-detail.jpg"></div>
        <div class="recommend"><img src="https://cbu01.alicdn.com/img/dom-ad.jpg"></div>
        """
        parsed_markup = collector.parse_html(markup)

        self.assertIn("https://cbu01.alicdn.com/img/dom-main.jpg", parsed_markup["main"])
        self.assertIn("https://cbu01.alicdn.com/img/dom-sku.jpg", [item["url"] for item in parsed_markup["sku"]])
        self.assertIn("https://cbu01.alicdn.com/img/dom-detail.jpg", parsed_markup["detail"])
        self.assertEqual(["https://cbu01.alicdn.com/img/dom-ad.jpg"], parsed_markup["unknown"])

    def test_page_without_product_data_falls_back_to_mobile_page(self):
        shell_html = "<html><body>" + "".join(
            f'<img src="https://cbu01.alicdn.com/img/ad-{index}.jpg">'
            for index in range(200)
        ) + "</body></html>"
        mobile_html = "x" * 5000 + """
        <script>
        window.__INIT_DATA = {"data": {"100": {"data": {
          "offerImgList": ["https://cbu01.alicdn.com/img/main.jpg"]
        }}}};
        </script>
        """
        url = "https://detail.1688.com/offer/12345678.html"

        with patch.object(collector, "fetch_page", side_effect=[shell_html, mobile_html]) as fetch:
            html, final_url = collector.fetch_product_html(url, {})

        self.assertIn("offerImgList", html)
        self.assertEqual("https://m.1688.com/offer/12345678.html", final_url)
        self.assertEqual(2, fetch.call_count)

    def test_page_without_product_data_raises_clear_error(self):
        shell_html = "<html><body>" + "".join(
            f'<img src="https://cbu01.alicdn.com/img/ad-{index}.jpg">'
            for index in range(200)
        ) + "</body></html>"
        url = "https://detail.1688.com/offer/12345678.html"

        with patch.object(collector, "fetch_page", return_value=shell_html):
            with self.assertRaises(collector.CollectError) as context:
                collector.fetch_product_html(url, {})

        self.assertIn("没有商品数据", str(context.exception))

    def test_mobile_init_data_without_trailing_underscores_is_parsed(self):
        html = """
        <script>
        window.__GLOBAL_DADA = {"isLogin": false};
        window.__INIT_DATA = {"data": {"100": {"data": {
          "offerImgList": ["https://cbu01.alicdn.com/img/main-a.jpg"],
          "offerImages": [{"imgUrl": "https://cbu01.alicdn.com/img/main-a.jpg", "typeDes": "主图"}],
          "skuImages": [{"name": "奶油黄", "imgUrl": "https://cbu01.alicdn.com/img/sku-a.jpg"}],
          "detailUrl": "https://air.1688.com/pages/od/app-desc/index.html?url=https://itemcdn.tmall.com/1688offer/icoss-demo"
        }}}};
        </script>
        """

        parsed = collector.parse_html(html, "https://m.1688.com/offer/100.html")

        self.assertIn("https://cbu01.alicdn.com/img/main-a.jpg", parsed["main"])
        self.assertIn(
            {"name": "奶油黄", "url": "https://cbu01.alicdn.com/img/sku-a.jpg"},
            parsed["sku"],
        )
        self.assertEqual(
            ["https://itemcdn.tmall.com/1688offer/icoss-demo"],
            parsed["detailUrls"],
        )

    def test_scripts_ui_icons_and_thumbnail_variants_are_not_collected(self):
        html = """
        <script>
        window.__INIT_DATA = {"data": {"100": {"data": {
          "offerImgList": ["https://cbu01.alicdn.com/img/main.jpg"],
          "seedModules": ["https://g.alicdn.com/code/npm/@ali/cmod-odw-basic-description/0.0.77/index.js"]
        }}}};
        </script>
        <img src="https://gw.alicdn.com/imgextra/i4/demo-2-tps-132-140.png">
        <img src="https://cbu01.alicdn.com/img/main.310x310.jpg">
        <img src="https://img.alicdn.com/tfs/TB1demo-26-44.png">
        """

        parsed = collector.parse_html(html, "https://m.1688.com/offer/100.html")

        self.assertEqual(["https://cbu01.alicdn.com/img/main.jpg"], parsed["main"])
        self.assertEqual([], parsed["sku"])
        self.assertEqual([], parsed["detail"])
        self.assertEqual([], parsed["video"])
        self.assertEqual([], parsed["unknown"])

    def test_global_data_images_are_treated_as_main_images(self):
        html = """
        <script>
        window.__INIT_DATA = {"globalData": {"images": [
          {"fullPathImageURI": "https://cbu01.alicdn.com/img/gallery-a.jpg"},
          {"fullPathImageURI": "https://cbu01.alicdn.com/img/gallery-b.jpg"}
        ]}};
        </script>
        """

        parsed = collector.parse_html(html)

        self.assertEqual(
            [
                "https://cbu01.alicdn.com/img/gallery-a.jpg",
                "https://cbu01.alicdn.com/img/gallery-b.jpg",
            ],
            parsed["main"],
        )

    def test_streamed_detail_resource_is_decoded_without_consuming_content(self):
        settings = {"download": {"retries": 1}}
        detail_text = 'var offer_details={"content":"<img src=\\"https://cbu01.alicdn.com/img/detail.jpg\\">"};'
        response = Mock(status_code=200, is_redirect=False, encoding="utf-8")
        response.iter_content.return_value = [detail_text.encode("utf-8")]

        with patch.object(collector.requests, "get", return_value=response):
            html, error = collector.fetch_detail_resource(
                "https://itemcdn.tmall.com/1688offer/icoss-demo", settings,
            )

        self.assertEqual("", error)
        self.assertIn("offer_details", html)
        detail = collector.parse_desc_html(html, "https://itemcdn.tmall.com/1688offer/icoss-demo")
        self.assertEqual(["https://cbu01.alicdn.com/img/detail.jpg"], detail["detail"])

    def test_url_collection_fetches_detail_resource_with_task_cookie(self):
        product_html = """
        <script>
        window.context = {"result":{"data":{"description":{"fields":{
          "detailUrl":"https://desc.alicdn.com/item/description.html"
        }}}}};
        </script>
        """
        detail_html = 'var offer_details = {"content":"<img src=\\"https://cbu01.alicdn.com/img/detail.jpg\\">"};'
        product_url = "https://detail.1688.com/offer/12345678.html"
        with patch.object(collector, "fetch_product_html", return_value=(product_html, product_url)):
            with patch.object(collector, "fetch_detail_resource", return_value=(detail_html, "")) as fetch_detail:
                with patch.object(collector, "apply_parsed", return_value={"id": "test"}) as apply:
                    collector.collect_from_url("test", product_url, {}, cookie="task-cookie")

        fetch_detail.assert_called_once_with(
            "https://desc.alicdn.com/item/description.html",
            {}, cookie="task-cookie", referer=product_url,
        )
        self.assertIn("https://cbu01.alicdn.com/img/detail.jpg", apply.call_args.args[1]["detail"])

    def test_task_cookie_is_used_for_image_download_requests(self):
        settings = {"download": {"retries": 1}}
        response = Mock(status_code=200, headers={"Content-Length": "10"})
        response.iter_content.return_value = [b"x" * 10]

        with patch.object(collector, "_headers", return_value={"Cookie": "task-cookie"}) as headers:
            with patch.object(collector.requests, "get", return_value=response):
                result, error = collector.download_one(
                    "unused-task", "main", 1, "https://example.test/image.jpg",
                    "", settings, set(), cookie="task-cookie",
                )

        self.assertIsNone(result)
        self.assertEqual("文件为空或过小", error)
        headers.assert_called_once_with(settings, cookie="task-cookie")

    def test_download_pipeline_forwards_cookie_to_each_image_request(self):
        parsed = {"main": ["https://cbu01.alicdn.com/img/main.jpg"]}
        with patch.object(collector, "download_one", return_value=(None, None)) as download:
            collector.download_all(
                "unused-task", parsed, {"download": {"concurrency": 1}},
                cookie="task-cookie",
            )

        self.assertEqual("task-cookie", download.call_args.args[-1])

    def test_unknown_candidates_are_downloaded_into_review_category(self):
        parsed = {"unknown": ["https://cbu01.alicdn.com/img/unknown.jpg"]}
        with patch.object(collector, "download_one", return_value=(None, None)) as download:
            result = collector.download_all(
                "unused-task", parsed, {"download": {"concurrency": 1}},
            )

        self.assertEqual("review", download.call_args.args[1])
        self.assertIn("review", result["records"])

    def test_url_collection_passes_task_cookie_into_download_pipeline(self):
        html = """
        <script>
        window.__INIT_DATA__ = {"offerImgList": ["https://cbu01.alicdn.com/img/main.jpg"]};
        </script>
        """
        with patch.object(collector, "fetch_product_html", return_value=(html, "https://detail.1688.com/offer/12345678.html")) as fetch:
            with patch.object(collector, "apply_parsed", return_value={"id": "test"}) as apply:
                collector.collect_from_url(
                    "test", "https://detail.1688.com/offer/12345678.html",
                    {}, cookie="task-cookie",
                )

        fetch.assert_called_once()
        self.assertEqual("task-cookie", fetch.call_args.args[2])
        self.assertEqual("task-cookie", apply.call_args.kwargs["cookie"])


class ReviewClassificationTests(unittest.TestCase):
    def test_classifying_review_image_moves_file_and_updates_sku_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tasks_dir = Path(temp_dir) / "tasks"
            with patch.object(storage.config, "TASKS_DIR", tasks_dir):
                task = storage.create_task(offer_id="12345678", title="test")
                image_data = io.BytesIO()
                Image.new("RGB", (320, 240), color=(30, 80, 120)).save(image_data, format="JPEG")
                image_data.seek(0)
                upload = FileStorage(stream=image_data, filename="review.jpg")
                record = storage.save_upload(task["id"], "review", "review.jpg", upload)
                meta = storage.load_meta(task["id"])
                meta["raw"]["review"].append(record)
                storage.save_meta(task["id"], meta)

                response = flask_app.test_client().post(
                    f"/api/tasks/{task['id']}/raw/classify",
                    json={"file": record["file"], "kind": "sku", "name": "蓝色"},
                )

                self.assertEqual(200, response.status_code)
                moved = response.get_json()["data"]
                groups = storage.scan_raw(task["id"])
                updated = storage.load_meta(task["id"])

        self.assertEqual([], groups["review"])
        self.assertEqual(1, len(groups["sku"]))
        self.assertEqual("蓝色", updated["sku"][0]["name"])
        self.assertEqual(moved["file"], updated["sku"][0]["image"])


class RawDeletionTests(unittest.TestCase):
    def test_deleting_raw_sku_removes_file_and_rebuilds_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            tasks_dir = Path(temp_dir) / "tasks"
            with patch.object(storage.config, "TASKS_DIR", tasks_dir):
                task = storage.create_task(offer_id="12345678", title="test")
                image_data = io.BytesIO()
                Image.new("RGB", (320, 240), color=(30, 80, 120)).save(image_data, format="JPEG")
                image_data.seek(0)
                upload = FileStorage(stream=image_data, filename="blue.jpg")
                record = storage.save_upload(task["id"], "sku", "blue.jpg", upload, name="蓝色")
                meta = storage.load_meta(task["id"])
                meta["raw"]["sku"].append(record)
                meta["sku"] = storage.rebuild_sku_from_files(task["id"])
                storage.save_meta(task["id"], meta)

                response = flask_app.test_client().delete(
                    f"/api/tasks/{task['id']}/raw",
                    json={"file": record["file"]},
                )

                self.assertEqual(200, response.status_code)
                updated = storage.load_meta(task["id"])
                groups = storage.scan_raw(task["id"])

        self.assertEqual([], groups["sku"])
        self.assertEqual([], updated["raw"]["sku"])
        self.assertEqual([], updated["sku"])
        self.assertFalse((tasks_dir / task["id"] / record["file"]).exists())

    def test_delete_raw_endpoint_rejects_non_raw_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(offer_id="12345678", title="test")
                response = flask_app.test_client().delete(
                    f"/api/tasks/{task['id']}/raw",
                    json={"file": "task_meta.json"},
                )

        self.assertEqual(400, response.status_code)

    def test_missing_raw_media_returns_not_found(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(offer_id="12345678", title="test")
                response = flask_app.test_client().get(
                    f"/media/{task['id']}/raw/main/missing.jpg",
                )

        self.assertEqual(404, response.status_code)


if __name__ == "__main__":
    unittest.main()

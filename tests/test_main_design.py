import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image, ImageDraw

from app import app
from core import storage


class MainDesignTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(storage.config, "TASKS_DIR", Path(temp)))
        self.task_id = storage.create_task(title="商品")["id"]
        self.root = storage.task_path(self.task_id)
        self.client = app.test_client()
        self.endpoint = f"/api/tasks/{self.task_id}/main-design/main_pc/1"
        self.source = "raw/main/product.png"
        Image.new("RGB", (160, 180), (245, 20, 20)).save(self.root / self.source)

    def generate(self, template="split"):
        response = self.client.post(f"/api/tasks/{self.task_id}/generate/main", json={
            "slot": 1, "source": self.source, "template": template, "headline": "品质好物", "badge": "精选",
        })
        self.assertEqual(200, response.status_code, response.get_json())
        return response.get_json()["data"]

    def test_deleted_layer_is_removed_from_output_and_original_is_preserved(self):
        generated = self.generate("overlay")
        original = (self.root / self.source).read_bytes()
        mobile = (self.root / generated["mobile"]["file"]).read_bytes()
        data = self.client.get(self.endpoint).get_json()["data"]
        layers = data["record"]["editor"]["layers"]
        photo = next(layer for layer in layers if layer["replaceable"])
        order = [layer["id"] for layer in layers if layer != photo]
        payload = {"revision": data["revision"], "layers": {}, "order": order}
        self.assertEqual(400, self.client.post(self.endpoint, json=payload).status_code)
        response = self.client.post(self.endpoint, json={**payload, "removed": [photo["id"]]})
        self.assertEqual(200, response.status_code, response.get_json())
        record = self.client.get(self.endpoint).get_json()["data"]["record"]
        self.assertEqual(order, [layer["id"] for layer in record["editor"]["layers"]])
        with Image.open(self.root / record["file"]) as output:
            red, green, _ = output.getpixel((output.width // 2, output.height // 2))
            self.assertLess(red - green, 35)
        self.assertEqual(original, (self.root / self.source).read_bytes())
        self.assertEqual(mobile, (self.root / generated["mobile"]["file"]).read_bytes())

        current = self.client.get(self.endpoint).get_json()["data"]
        changed = (self.root / record["file"]).read_bytes()
        restore = self.client.post(self.endpoint, json={
            "action": "template-preview", "revision": current["revision"],
        })
        self.assertEqual(200, restore.status_code)
        baseline = restore.get_json()["data"]
        self.assertEqual([layer["id"] for layer in layers], [layer["id"] for layer in baseline["layers"]])
        self.assertEqual(changed, (self.root / record["file"]).read_bytes())
        saved = self.client.post(self.endpoint, json={
            "revision": current["revision"], "fromTemplate": True, "layers": {},
        })
        self.assertEqual(200, saved.status_code, saved.get_json())
        restored = saved.get_json()["data"]["record"]
        self.assertEqual(photo["file"], restored["editor"]["layers"][0]["file"])
        self.assertNotEqual(changed, (self.root / restored["file"]).read_bytes())
        self.assertEqual(mobile, (self.root / generated["mobile"]["file"]).read_bytes())

    def test_layer_order_and_inverse_cutout_are_persisted(self):
        source = Image.new("RGB", (160, 180), "white")
        ImageDraw.Draw(source).rectangle((32, 45, 128, 135), fill="red")
        source.save(self.root / self.source)
        original = (self.root / self.source).read_bytes()
        self.generate("overlay")
        data = self.client.get(self.endpoint).get_json()["data"]
        layers = data["record"]["editor"]["layers"]
        photo = next(layer for layer in layers if layer["replaceable"])
        change = {"edits": [{"type": "background"}, {"type": "keep", "box": [0.5, 0.3, 0.8, 0.7]}]}
        preview = self.client.post(self.endpoint, json={
            "action": "preview-layer", "revision": data["revision"], "layer": photo["id"], "change": change,
        })
        self.assertEqual(200, preview.status_code)
        with Image.open(io.BytesIO(preview.data)) as image:
            self.assertEqual(0, image.getpixel((image.width // 3, image.height // 2))[3])
            self.assertEqual(255, image.getpixel((int(image.width * 0.6), image.height // 2))[3])
        order = [layer["id"] for layer in reversed(layers)]
        response = self.client.post(self.endpoint, json={
            "revision": data["revision"], "order": order, "layers": {photo["id"]: change},
        })
        self.assertEqual(200, response.status_code)
        saved = response.get_json()["data"]["record"]["editor"]["layers"]
        self.assertEqual(order, [layer["id"] for layer in saved])
        with Image.open(self.root / saved[-1]["file"]) as image:
            self.assertEqual(0, image.getpixel((image.width // 3, image.height // 2))[3])
            self.assertEqual(255, image.getpixel((int(image.width * 0.6), image.height // 2))[3])
        self.assertEqual(original, (self.root / self.source).read_bytes())

    def test_resize_product_and_move_label_update_only_selected_output(self):
        before = self.generate()
        original = (self.root / self.source).read_bytes()
        mobile = (self.root / before["mobile"]["file"]).read_bytes()
        data = self.client.get(self.endpoint).get_json()["data"]
        layers = {layer["name"]: layer for layer in data["record"]["editor"]["layers"]}
        self.assertIn("精选", layers)
        photo, title = layers["商品图"], layers["品质好物"]
        changes = {
            photo["id"]: {"width": 110, "height": 115, "left": 10, "top": 10},
            title["id"]: {"left": 400, "top": 320},
        }
        response = self.client.post(self.endpoint, json={"revision": data["revision"], "layers": changes})
        self.assertEqual(200, response.status_code, response.get_json())
        saved = response.get_json()["data"]
        self.assertNotEqual(data["revision"], saved["revision"])
        reopened = self.client.get(self.endpoint).get_json()["data"]["record"]
        self.assertEqual(saved["record"], reopened)
        by_id = {layer["id"]: layer for layer in reopened["editor"]["layers"]}
        self.assertEqual(110, by_id[photo["id"]]["width"])
        self.assertEqual(320, by_id[title["id"]]["top"])
        with Image.open(self.root / reopened["file"]) as result:
            self.assertGreater(result.getpixel((30, 30))[0] - result.getpixel((30, 30))[1], 150)
            self.assertLess(result.getpixel((80, 250))[0] - result.getpixel((80, 250))[1], 35)
        self.assertEqual(original, (self.root / self.source).read_bytes())
        self.assertEqual(mobile, (self.root / before["mobile"]["file"]).read_bytes())
        self.assertEqual(409, self.client.post(self.endpoint, json={"revision": data["revision"], "layers": changes}).status_code)
        exported = self.client.post(f"/api/tasks/{self.task_id}/export", json={}).get_json()["data"]
        with ZipFile(self.root / exported["file"]) as archive:
            images = [archive.read(name) for name in archive.namelist() if name.endswith(".jpg")]
        self.assertIn((self.root / reopened["file"]).read_bytes(), images)

    def test_old_output_can_rebuild_without_changing_published_image(self):
        before = self.generate()
        path = self.root / before["pc"]["file"]
        old_bytes = path.read_bytes()

        def remove_manifest(meta):
            del meta["outputs"]["main_pc"]["1"]["editor"]

        storage.update_meta(self.task_id, remove_manifest)
        current = self.client.get(self.endpoint).get_json()["data"]
        response = self.client.post(self.endpoint, json={"action": "prepare", "revision": current["revision"]})
        self.assertEqual(200, response.status_code, response.get_json())
        self.assertTrue(response.get_json()["data"]["record"]["editor"]["reconstructed"])
        self.assertEqual(old_bytes, path.read_bytes())

    def test_replace_product_and_stretch_previously_locked_decoration(self):
        self.generate()
        replacement = "raw/detail/replacement.png"
        Image.new("RGBA", (120, 240), (15, 20, 240, 255)).save(self.root / replacement)
        original = (self.root / replacement).read_bytes()

        def mark_legacy_decoration(meta):
            for layer in meta["outputs"]["main_pc"]["1"]["editor"]["layers"]:
                if layer["name"] == "模板装饰":
                    layer["locked"] = True

        storage.update_meta(self.task_id, mark_legacy_decoration)
        data = self.client.get(self.endpoint).get_json()["data"]
        self.assertIn(replacement, data["library"]["detail"])
        layers = {layer["name"]: layer for layer in data["record"]["editor"]["layers"]}
        photo, decoration = layers["商品图"], layers["模板装饰"]
        self.assertFalse(decoration["locked"])
        invalid = self.client.post(self.endpoint, json={
            "revision": data["revision"], "layers": {decoration["id"]: {"asset": replacement}},
        })
        self.assertEqual(400, invalid.status_code)
        saved = self.client.post(self.endpoint, json={
            "revision": data["revision"],
            "layers": {
                photo["id"]: {"asset": replacement, "left": 0, "top": 0, "width": 120, "height": 240},
                decoration["id"]: {"width": 200, "height": 40, "opacity": 60},
            },
        })
        self.assertEqual(200, saved.status_code, saved.get_json())
        record = self.client.get(self.endpoint).get_json()["data"]["record"]
        by_id = {layer["id"]: layer for layer in record["editor"]["layers"]}
        self.assertEqual(replacement, by_id[photo["id"]]["asset"])
        self.assertEqual(replacement, record["source"])
        self.assertEqual(200, by_id[decoration["id"]]["width"])
        self.assertEqual(60, by_id[decoration["id"]]["opacity"])
        with Image.open(self.root / record["file"]) as output:
            red, _, blue = output.getpixel((50, 50))
            self.assertGreater(blue - red, 150)
        self.assertEqual(original, (self.root / replacement).read_bytes())

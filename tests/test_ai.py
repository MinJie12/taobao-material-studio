import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app as flask_app
from core import storage


class AiApiTests(unittest.TestCase):
    def test_status_is_available_without_a_model(self):
        response = flask_app.test_client().get("/api/ai/status")
        self.assertEqual(200, response.status_code)
        self.assertIn("available", response.get_json()["data"])

    def test_analyze_and_assistant_keep_working_with_local_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(storage.config, "TASKS_DIR", Path(temp_dir) / "tasks"):
                task = storage.create_task(title="春季针织衫", category="女装")
                client = flask_app.test_client()
                analysis = client.post(f"/api/tasks/{task['id']}/ai/analyze", json={})
                self.assertEqual(200, analysis.status_code)
                self.assertEqual("local-rule", analysis.get_json()["data"]["source"])

                preview = client.post(
                    f"/api/tasks/{task['id']}/ai/assistant/preview",
                    json={"instruction": "把背景换成浅灰色，商品主体放大20%，字体统一"},
                )
                self.assertEqual(200, preview.status_code)
                plan = preview.get_json()["data"]
                self.assertEqual(3, len(plan["operations"]))

                applied = client.post(
                    f"/api/tasks/{task['id']}/ai/assistant/apply",
                    json={"plan": plan},
                )
                self.assertEqual(200, applied.status_code)
                data = applied.get_json()["data"]
                self.assertEqual("#F2F3F5", data["design"]["background"])
                self.assertEqual(1.2, data["design"]["productScale"])
                self.assertEqual(1, len(data["history"]))

                undone = client.post(f"/api/tasks/{task['id']}/ai/assistant/undo", json={})
                self.assertEqual(200, undone.status_code)
                self.assertEqual("#F7F4F0", undone.get_json()["data"]["design"]["background"])
                redone = client.post(f"/api/tasks/{task['id']}/ai/assistant/redo", json={})
                self.assertEqual(200, redone.status_code)
                self.assertEqual("#F2F3F5", redone.get_json()["data"]["design"]["background"])

                saved = client.post(
                    f"/api/tasks/{task['id']}/design",
                    json={"design": {"canvas": {"width": 1000, "height": 1000}, "layers": []}, "note": "测试版本"},
                )
                self.assertEqual(200, saved.status_code)
                loaded = client.get(f"/api/tasks/{task['id']}/design")
                self.assertEqual(1000, loaded.get_json()["data"]["design"]["canvas"]["width"])
                self.assertEqual(2, len(loaded.get_json()["data"]["versions"]))


if __name__ == "__main__":
    unittest.main()

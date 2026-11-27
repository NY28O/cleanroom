"""在临时项目里运行真实 CLI；图像请求仅发往本机模拟服务。"""
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from PIL import Image


PROJECT = Path(__file__).resolve().parents[1]
PROMPT = Path("01_规则与提示词/温暖家居_编辑提示词.txt")
NAME = "7-1.png"
SIZE = (24, 16)


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


@contextmanager
def local_edits(raw):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            mime = ("Content-Type: " + self.headers["Content-Type"] + "\r\n\r\n").encode()
            requests.append((self.path, BytesParser(policy=policy.default).parsebytes(mime + body)))
            data = json.dumps({"data": [{"b64_json": base64.b64encode(raw).decode("ascii")}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("x-request-id", "local-request-01")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", requests
        finally:
            server.shutdown()
            thread.join()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "临时项目"
        self.source = Path(temp.name) / "外部 原图库"
        self.source.mkdir()
        self.batches = self.root / "03_批量运行"
        self.batches.mkdir(parents=True)
        self.products = self.root / "04_正式成品"
        self.products.mkdir()
        for script in PROJECT.glob("*.py"):
            shutil.copyfile(script, self.root / script.name)
        (self.root / PROMPT).parent.mkdir()
        shutil.copyfile(PROJECT / PROMPT, self.root / PROMPT)
        (self.batches / "已修改核对清单.md").write_text(
            "| 7-x | 小木箱 | 1 | 0 | 1 | 7-1 ☐ |\n"
            "| 8-x | 台灯 | 1 | 0 | 1 | 8-1 ☐ |\n", encoding="utf-8")

        # 离中心矩形，原图为冷色、编辑返回为暖色；透明边缘相同。
        large = Image.new("RGBA", (96, 64))
        large.paste((189, 96, 45, 255), (12, 24, 68, 52))
        self.raw = png(large)
        orig = Image.new("RGBA", SIZE, (28, 53, 130, 255))
        orig.putalpha(large.getchannel("A").resize(SIZE, Image.Resampling.LANCZOS))
        self.original = png(orig)
        (self.source / NAME).write_bytes(self.original)
        self.env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_PROXY="127.0.0.1",
                        OPENAI_BASE_URL="http://127.0.0.1:1/v1", OPENAI_API_KEY="offline-test-only")

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, "-B", "batch.py", *map(str, args)],
                                cwd=self.root, env=self.env, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=20)
        self.assertEqual(result.returncode == 0, success, f"{args}: {result.stdout}\n{result.stderr}")

    def init_batch(self):
        self.cli("init", "--start", 7, "--end", 7, "--source-dir", self.source)
        [batch] = [p for p in self.batches.iterdir() if p.is_dir()]
        return batch

    def test_missing_source_file_stops_before_creating_a_batch(self):
        self.cli("init", "--start", 7, "--end", 8, "--source-dir", self.source, success=False)
        self.assertFalse(any(p.is_dir() for p in self.batches.iterdir()))
        self.assertEqual((self.source / NAME).read_bytes(), self.original)

    def test_generation_restore_accept_publish_and_resume(self):
        with local_edits(self.raw) as (url, requests):
            self.env["OPENAI_BASE_URL"] = url
            batch = self.init_batch()
            self.assertEqual(requests, [])
            self.cli("submit", batch)
            self.cli("submit", batch)
            self.assertEqual(len(requests), 1, "续跑不应重复发送已成功的图")
            path, message = requests[0]
            self.assertEqual(path, "/v1/images/edits")
            self.assertEqual(message.get_content_type(), "multipart/form-data")
            parts = list(message.iter_parts())
            [upload] = [p for p in parts if p.get_filename() is not None]
            self.assertIn(upload.get_param("name", header="content-disposition"), ("image", "image[]"))
            self.assertEqual((upload.get_filename(), upload.get_content_type()), (NAME, "image/png"))
            self.assertEqual(upload.get_payload(decode=True), self.original)
            fields = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True).decode()
                      for p in parts if p.get_filename() is None}
            self.assertEqual(fields["background"], "transparent")
            self.assertEqual(fields["output_format"], "png")
            self.assertIn("小木箱", fields["prompt"])
            self.assertIn("24 × 16", fields["prompt"])
            self.assertIn((self.root / PROMPT).read_text(encoding="utf-8").split("\n\n")[-1].strip(),
                          fields["prompt"])
            self.assertEqual((batch / "raw" / NAME).read_bytes(), self.raw)
            logs = [json.loads(p.read_text(encoding="utf-8")) for p in (batch / "requests").glob("*.json")]
            [record] = [r for r in logs if r.get("request_id") == "local-request-01"]
            self.assertEqual(record["source_sha256"], hashlib.sha256(self.original).hexdigest())
            self.assertEqual(record["image_sha256"], hashlib.sha256(self.raw).hexdigest())
            self.assertEqual(record["prompt_sha256"], hashlib.sha256(fields["prompt"].encode()).hexdigest())
            self.assertNotIn(self.env["OPENAI_API_KEY"], json.dumps(logs))

            self.cli("restore", batch)
            ready = batch / "待验收图" / NAME
            restored = ready.read_bytes()
            with Image.open(ready) as image, Image.open(self.source / NAME) as original:
                self.assertEqual(image.size, SIZE)
                self.assertEqual(image.convert("RGBA").getchannel("A").tobytes(),
                                 original.getchannel("A").tobytes())
                self.assertEqual(image.convert("RGB").getpixel((8, 9)), (189, 96, 45))
            self.cli("publish", batch, NAME, success=False)
            self.assertFalse((self.products / NAME).exists())
            self.cli("accept", batch, NAME)
            self.assertFalse((self.products / NAME).exists())
            self.cli("publish", batch, NAME)
            self.assertEqual((self.products / NAME).read_bytes(), restored)
            self.cli("restore", batch)
            self.assertEqual(ready.read_bytes(), restored)
            self.assertEqual((batch / "raw" / NAME).read_bytes(), self.raw)
            self.assertEqual((self.source / NAME).read_bytes(), self.original)
            # 放入另一份同名成品，确保重复发布不会覆盖使用者已有内容。
            (self.products / NAME).write_bytes(self.original)
            self.cli("publish", batch, NAME, success=False)
            self.assertEqual((self.products / NAME).read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()

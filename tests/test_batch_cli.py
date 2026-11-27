import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import batch


class BatchCliTests(unittest.TestCase):
    def test_init_creates_candidates_for_requested_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            rows = []
            for group, count in ((1, 19), (2, 12), (3, 12)):
                names = " · ".join(f"{group}-{i} ☐" for i in range(1, count + 1))
                rows.append(f"| {group}-x | 组{group} | {count} | 0 | {count} | {names} |")
                for i in range(1, count + 1):
                    image = Image.new("RGBA", (24, 24))
                    ImageDraw.Draw(image).rectangle((5, 5, 18, 18), fill=(20, 30, 40, 255))
                    image.save(source / f"{group}-{i}.png")
            checklist = root / "03_批量运行"
            checklist.mkdir()
            (checklist / "已修改核对清单.md").write_text("\n".join(rows), encoding="utf-8")
            (root / "01_规则与提示词").mkdir()
            (root / "01_规则与提示词" / "温暖家居_编辑提示词.txt").write_text("只输出透明 PNG。", encoding="utf-8")
            batch_dir = batch.init_batch(root, source, 1, 3, batch_name="test-batch")
            candidates = [json.loads(line) for line in (batch_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(candidates), 43)
            self.assertEqual(candidates[0]["file"], "1-1.png")
            self.assertEqual(candidates[-1]["file"], "3-12.png")
            self.assertEqual((batch_dir / "raw").is_dir(), True)
            self.assertEqual((batch_dir / "meta.json").is_file(), True)


if __name__ == "__main__":
    unittest.main()

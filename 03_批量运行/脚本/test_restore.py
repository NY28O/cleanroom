import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from restore import build_review, normalize


class RestoreTests(unittest.TestCase):
    def test_same_canvas_keeps_hole_and_soft_edge(self):
        source = Image.new('RGBA', (18, 15))
        ImageDraw.Draw(source).rectangle((4, 4, 11, 9), fill=(10, 20, 30, 255))
        raw = source.copy()
        raw.putpixel((3, 6), (20, 40, 50, 90))
        raw.putpixel((7, 6), (0, 0, 0, 0))
        result, status, _ = normalize(source, raw)
        self.assertEqual(status, 'ready')
        self.assertEqual(result.size, (18, 15))
        self.assertEqual(result.getpixel((3, 6))[3], 90)
        self.assertEqual(result.getpixel((7, 6))[3], 0)

    def test_background_with_no_clear_pixels_is_held(self):
        source = Image.new('RGBA', (40, 30))
        ImageDraw.Draw(source).rectangle((10, 10, 20, 20), fill=(10, 20, 30, 255))
        raw = Image.new('RGBA', (40, 30), (20, 20, 20, 3))
        ImageDraw.Draw(raw).rectangle((10, 10, 20, 20), fill=(10, 20, 30, 255))
        self.assertEqual(normalize(source, raw), (None, 'background', None))

    def test_different_aspect_ratio_is_not_stretched(self):
        source = Image.new('RGBA', (40, 30))
        ImageDraw.Draw(source).rectangle((10, 5, 29, 24), fill=(10, 20, 30, 255))
        raw = Image.new('RGBA', (80, 60))
        ImageDraw.Draw(raw).rectangle((30, 10, 39, 29), fill=(20, 30, 40, 255))
        result, status, _ = normalize(source, raw)
        self.assertEqual(result.getbbox(), (15, 5, 25, 25))
        self.assertEqual(status, 'alignment')

    def test_missing_raw_image_stays_in_ledger_without_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            batch = root / 'batch'
            batch.mkdir()
            (batch / 'candidates.jsonl').write_text(json.dumps({
                'file': '1-2.png', 'source': '1-2.png', 'sha256': 'unused',
            }), encoding='utf-8')
            rows = build_review(root, batch)
            self.assertEqual(rows[0]['technical_status'], 'missing_raw')
            self.assertIsNone(rows[0]['review_path'])
            self.assertFalse(list((batch / '待验收图').glob('*.png')))


if __name__ == '__main__':
    unittest.main()

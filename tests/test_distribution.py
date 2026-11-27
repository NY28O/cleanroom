"""校验正式分发资源；验收进度是工作区状态，不与安装模板同步。"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill/prop-image-batch"


def catalog(path):
    groups = []
    for line in path.read_text("utf-8-sig").splitlines():
        cells = [v.strip() for v in line.split("|")]
        if len(cells) == 8 and re.fullmatch(r"[0-9]+-x", cells[1]):
            ids = re.findall(r"(?<![0-9-])([0-9]+-[0-9]+) [☐☑]", cells[6])
            groups.append((cells[1:4], ids))
    return groups


class DistributionTests(unittest.TestCase):
    def test_default_resources_match(self):
        for name in ("批量运行规则.md", "图片编辑与验收规则.md", "温暖家居_编辑提示词.txt", "最终效果约束.md", "定稿画风参照_玩具车.png", "requirements.txt"):
            rel = Path(name) if name == "requirements.txt" else Path("01_规则与提示词") / name
            packaged = (SKILL if name == "requirements.txt" else SKILL / "assets") / rel
            with self.subTest(file=name):
                if name.endswith(".png"):
                    self.assertEqual((ROOT / rel).read_bytes(), packaged.read_bytes())
                else:
                    self.assertEqual((ROOT / rel).read_text("utf8"), packaged.read_text("utf8"))
        index = "03_批量运行/已修改核对清单.md"
        groups = catalog(SKILL / "assets" / index)
        self.assertTrue(groups)
        self.assertEqual(catalog(ROOT / index), groups)
        for fields, ids in groups:
            self.assertEqual(len(ids), int(fields[2]), fields[0])

    def test_installed_document_links_resolve(self):
        docs = [SKILL / "SKILL.md", SKILL / "references/setup.md",
                *sorted((SKILL / "assets/01_规则与提示词").glob("*.md")),
                SKILL / "assets/03_批量运行/已修改核对清单.md"]
        for doc in docs:
            for link in re.findall(r"\\]\\(([^)]+)\\)", doc.read_text("utf8")):
                if "://" not in link and not link.startswith("#"):
                    with self.subTest(document=doc.name, link=link):
                        self.assertTrue((doc.parent / link).is_file())

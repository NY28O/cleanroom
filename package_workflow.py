"""只打包运行所需的项目文件。"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
FILES = (
    "AGENTS.md", "README.md", "项目入口.md", "道具图批量改款流程说明.md", "新风格参考提示词.md",
    "requirements.txt", "batch.py", "preflight.py", "restore_canvas.py", "transparent_png.py",
    "package_workflow.py", "03_批量运行/已修改核对清单.md", "03_批量运行/物品组核对图/索引.md",
    "04_正式成品/.gitkeep", "01_规则与提示词/定稿画风参照_玩具车.png", "01_规则与提示词/批量运行规则.md",
    "01_规则与提示词/图片编辑与验收规则.md", "01_规则与提示词/温暖家居_编辑提示词.txt", "01_规则与提示词/最终效果约束.md",
)
SKILL = ("SKILL.md", "agents/openai.yaml", "scripts/batch.py", "requirements.txt",
         *("scripts/engine/" + n for n in ("batch.py", "preflight.py", "restore_canvas.py", "transparent_png.py")),
         *("assets/" + n for n in FILES if n.startswith("01_规则与提示词/") or n.endswith("已修改核对清单.md")))


def package():
    dest = ROOT / "交付包" / "道具图批量修图.zip"
    dest.parent.mkdir(exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    with ZipFile(tmp, "w", ZIP_DEFLATED) as out:
        for name in FILES:
            out.write(ROOT / name, name)
        for name in SKILL:
            source = ROOT / "skill" / "prop-image-batch" / name
            out.write(source, "skill/prop-image-batch/" + name)
            out.write(source, ".agents/skills/prop-image-batch/" + name)
    tmp.replace(dest)
    return dest


if __name__ == "__main__":
    print(package())

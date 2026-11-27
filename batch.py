"""仓库兼容入口，实际实现随 Skill 发布。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skill/prop-image-batch/scripts"))
from engine import batch
from engine.batch import init_batch

if __name__ == "__main__":
    batch.ROOT = ROOT
    batch.PROMPT = ROOT / "01_规则与提示词/温暖家居_编辑提示词.txt"
    batch.CHECKLIST = ROOT / "03_批量运行/已修改核对清单.md"
    try:
        batch.main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None

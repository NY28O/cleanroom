"""仓库兼容入口，实际实现随 Skill 发布。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skill/prop-image-batch/scripts"))
from engine.restore_canvas import main, restore_one, run_batch as _run_batch


def run_batch(batch, source):
    return _run_batch(batch, source, ROOT)

if __name__ == "__main__":
    main(ROOT)

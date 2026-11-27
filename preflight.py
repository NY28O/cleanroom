"""仓库兼容入口，实际实现随 Skill 发布。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "skill/prop-image-batch/scripts"))
from engine.preflight import check, main, require_source_dir

if __name__ == "__main__":
    main(ROOT)

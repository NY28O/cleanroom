"""独立安装入口。安装目录只读，批次和清单状态归使用者的工作区。"""
import argparse
import os
from pathlib import Path
import sys
from importlib.metadata import PackageNotFoundError, version

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"
INDEX = Path("03_批量运行/已修改核对清单.md")
PROMPT = Path("01_规则与提示词/温暖家居_编辑提示词.txt")


def check_install():
    if sys.version_info < (3, 9):
        raise ValueError("需要 Python 3.9 或以上版本")
    try:
        import PIL.Image
        pillow = version("Pillow")
        from PIL.Image import Resampling
    except (ImportError, PackageNotFoundError):
        raise ValueError("请从此 Skill 的 requirements.txt 安装 Pillow>=9.1")
    for path in (INDEX, PROMPT):
        if not (ASSETS / path).is_file():
            raise ValueError("安装文件缺失：" + str(path))
    return pillow


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd() / "道具修图工作区")
    parser.add_argument("command", choices=("check-install", "preflight", "init", "submit", "restore", "accept", "reject", "publish", "status", "doctor"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    pillow = check_install()
    sys.path.insert(0, str(SKILL / "scripts/engine"))
    import batch as engine
    from preflight import check, require_source_dir
    if args.command == "check-install":
        print(f"Skill 安装完整，Pillow {pillow}。")
        for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "PROP_IMAGE_MODEL"):
            print(key, "已配置" if os.environ.get(key) else "未设置")
        return
    root = args.workspace.resolve()
    if root == SKILL or SKILL in root.parents:
        raise ValueError("工作区须位于 Skill 安装目录之外")
    engine.ROOT, engine.PROMPT, engine.CHECKLIST = root, root / PROMPT, root / INDEX
    if args.command in ("preflight", "init"):
        options = argparse.ArgumentParser()
        options.add_argument("--start", type=int, required=True)
        options.add_argument("--end", type=int, required=True)
        options.add_argument("--source-dir", required=True)
        if args.command == "init":
            options.add_argument("--name")
        opt = options.parse_args(args.args)
        source = require_source_dir(opt.source_dir)
        if root == source or source in root.parents or any(source == d or d in source.parents for d in (root / INDEX.parent, root / "04_正式成品", root / PROMPT.parent)):
            raise ValueError("请在原图库之外选择独立工作区")
        count = check(root if (root / INDEX).is_file() else ASSETS, opt.start, opt.end, source)
        if args.command == "preflight":
            print(f"预检通过：{count} 张原图")
            return
        for rel in (INDEX, PROMPT):
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                with dest.open("xb") as fp:
                    fp.write((ASSETS / rel).read_bytes())
    engine.main([args.command, *args.args])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None

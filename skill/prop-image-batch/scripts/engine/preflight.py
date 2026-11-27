"""只读检查仓库位置、原图库和用户选定的组。"""
import argparse
import re
from pathlib import Path

from .transparent_png import read_transparent


def require_source_dir(path):
    if not path.strip():
        raise ValueError("请明确指定原图库目录路径")
    source = Path(path).resolve()
    if not source.is_dir():
        raise ValueError(f"原图库路径不是可用目录：{source}")
    return source


def check(root, start, end, source):
    if not 0 < start <= end:
        raise ValueError("请明确指定有效的起止组号")
    index = (root / "03_批量运行/已修改核对清单.md").read_text(encoding="utf-8-sig")
    names = []
    for line in index.splitlines():
        group = re.match(r"^\| (\d+)-x \|", line)
        if group and start <= int(group[1]) <= end:
            names.extend(dict.fromkeys(re.findall(r"(?<![\d-])" + group[1] + r"-\d+\b", line)))
    if not names:
        raise ValueError("分组清单在指定范围内没有原图")
    for name in names:
        path = source / (name + ".png")
        try:
            read_transparent(path.read_bytes(), path.name)
        except (ValueError, OSError) as exc:
            raise ValueError(f"请核对 {path}：{exc}") from exc
    return len(names)


def main(root):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    parser.add_argument("--source-dir", required=True, help="直接存放原图 PNG 的目录路径")
    args = parser.parse_args()
    try:
        if root != Path.cwd().resolve():
            raise ValueError("请打开含 README.md 的仓库根目录后再运行")
        source = require_source_dir(args.source_dir)
        count = check(root, args.start, args.end, source)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"启动检查未通过：{exc}\n")
    print(f"启动检查通过：{source}；本次范围内共 {count} 张原图。")

"""只读检查仓库位置、原图库和用户选定的组。"""
import argparse
import re
from pathlib import Path

from transparent_png import read_transparent


def check(root, start, end):
    source = root / "OriginalRoomArt_PNG"
    if not source.is_dir() or source.name not in {p.name for p in root.iterdir()}:
        raise ValueError(f"请在仓库根目录准备名称完全一致的原图库：{source}")
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parent
        if root != Path.cwd().resolve():
            raise ValueError("请打开含 README.md 的仓库根目录后再运行")
        count = check(root, args.start, args.end)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"启动检查未通过：{exc}\n")
    print(f"启动检查通过：本次范围内共 {count} 张原图。")

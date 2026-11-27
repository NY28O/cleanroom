"""Restore this batch's existing PNGs and produce a local review ledger."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from PIL import Image, ImageChops


ALPHA_CUT = [0] * 128 + [255] * 128
MIN_OVERLAP = 0.85
FILENAME = re.compile(r'([0-9]+)-([0-9]+)\.png')


def normalize(source, raw):
    original = source.getchannel('A').point(ALPHA_CUT)
    alpha = raw.getchannel('A')
    src_box = original.getbbox()
    raw_box = alpha.point(ALPHA_CUT).getbbox()
    if not src_box:
        return None, 'source_mask', None
    if not raw_box or (original.histogram()[0] and not alpha.histogram()[0]):
        return None, 'background', None

    sx, sy, sr, sb = src_box
    x, y, right, bottom = raw_box
    w, h = right - x, bottom - y
    scale = min((sr - sx) / w, (sb - sy) / h)
    width, height = max(1, round(w * scale)), max(1, round(h * scale))
    left, top = sx + (sr - sx - width) // 2, sb - height
    # Transform the full raw canvas so soft edge pixels outside the solid box survive.
    rx, ry = w / width, h / height
    result = raw.transform(
        source.size, Image.Transform.AFFINE,
        (rx, 0, x - rx * left, 0, ry, y - ry * top),
        Image.Resampling.BICUBIC,
    )
    mask = result.getchannel('A').point(ALPHA_CUT)
    union = ImageChops.lighter(original, mask).histogram()[255]
    overlap = ImageChops.multiply(original, mask).histogram()[255] / union
    return result, 'alignment' if overlap < MIN_OVERLAP else 'ready', round(overlap, 3)


def read_png(path):
    with Image.open(path) as image:
        if image.format != 'PNG':
            raise ValueError('expected PNG')
        return image.convert('RGBA')


def replace_file(path, write):
    tmp = path.with_name(path.name + '.tmp')
    write(tmp)
    tmp.replace(path)


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines()
            if line.strip()]


def save_review_status(batch, rows):
    notes_path = batch / '初审标记.json'
    notes = json.loads(notes_path.read_text(encoding='utf-8-sig')) if notes_path.exists() else {}
    if extras := notes.keys() - {row['file'] for row in rows}:
        raise ValueError(f'unknown names in review notes: {sorted(extras)}')
    for row in rows:
        note = notes.get(row['file'], {})
        row.update(visual_status=note.get('status', 'pending'),
                   review_decision=note.get('decision', 'pending'), note=note.get('note', ''))
    replace_file(batch / '逐图台账.jsonl', lambda tmp: tmp.write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8'))
    return rows


def build_review(root, batch):
    rows = read_rows(batch / 'candidates.jsonl')
    files = [row['file'] for row in rows]
    if any(not FILENAME.fullmatch(name) for name in files) or len(files) != len(set(files)):
        raise ValueError('candidate names must be unique and use group-item.png')

    index = batch.parent / '已修改核对清单.md'
    names = {}
    if index.exists():
        names = dict(re.findall(r'^\| ([0-9]+)-x \| ([^|]+?) \|',
                                index.read_text(encoding='utf-8-sig'), re.M))
    destination = batch / '待验收图'
    destination.mkdir(exist_ok=True)
    ledger = []
    for row in rows:
        name = row['file']
        group = int(name.split('-')[0])
        src = (root / row['source']).resolve()
        raw_path = batch / 'raw' / name
        review_path = destination / name
        entry = {
            'file': name, 'group': group, 'group_name': names.get(str(group), ''),
            'checkpoint': next((n for n, end in enumerate((5, 12, 16, 18), 1) if group <= end), None),
            'source_path': Path(os.path.relpath(src, batch)).as_posix(),
            'source_sha256': row['sha256'], 'source_size': None, 'raw_size': None,
            'raw_path': f'raw/{name}' if raw_path.is_file() else None,
            'review_path': None, 'overlap': None, 'technical_status': 'missing_raw',
        }
        ledger.append(entry)
        if not raw_path.is_file():
            continue
        try:
            if not src.is_relative_to(root.resolve()) or hashlib.sha256(src.read_bytes()).hexdigest() != row['sha256']:
                entry['technical_status'] = 'source_changed'
                continue
            source = read_png(src)
            entry['source_size'] = source.size
            raw = read_png(raw_path)
            entry['raw_size'] = raw.size
        except (OSError, ValueError):
            entry['technical_status'] = 'read_error'
            continue

        result, status, overlap = normalize(source, raw)
        entry.update(technical_status=status, overlap=overlap)
        if result is not None:
            replace_file(review_path, lambda tmp: result.save(tmp, 'PNG'))
            entry['review_path'] = f'待验收图/{name}'

    return save_review_status(batch, ledger)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh-review', action='store_true',
                        help='refresh review decisions and HTML without touching PNGs')
    args = parser.parse_args()
    batch = Path(__file__).resolve().parent
    if args.refresh_review:
        rows = save_review_status(batch, read_rows(batch / '逐图台账.jsonl'))
    else:
        rows = build_review(batch.parents[1], batch)
    content = (batch / 'review_template.html').read_text(encoding='utf-8')
    data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    replace_file(batch / '逐图复核.html', lambda tmp: tmp.write_text(
        content.replace('/* REVIEW_DATA */ []', data), encoding='utf-8'))
    print(f'Images: {len(rows)}; restored: {sum(bool(row["review_path"]) for row in rows)}')
    print(dict(Counter(row['technical_status'] for row in rows)))
    print(dict(Counter(row['visual_status'] for row in rows)))
    print(dict(Counter(row['review_decision'] for row in rows)))


if __name__ == '__main__':
    main()

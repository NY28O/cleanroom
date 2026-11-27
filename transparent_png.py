"""Shared transparency checks for prop artwork."""
import argparse
import io
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


REQUEST_FIELDS = {'background': 'transparent', 'output_format': 'png'}


def require_transparent(image, label='图片'):
    alpha = image.convert('RGBA').getchannel('A')
    low, high = alpha.getextrema()
    if high == 0:
        raise ValueError(f'{label}完全透明，没有可见主体')
    w, h = alpha.size
    border = [(0, 0, w, 1), (0, h - 1, w, h), (0, 0, 1, h), (w - 1, 0, w, h)]
    if low != 0 or not any(alpha.crop(box).getextrema()[0] == 0 for box in border):
        raise ValueError(f'{label}没有完全透明的画布外缘')
    return alpha


def read_transparent(data, label='图片'):
    with Image.open(io.BytesIO(data)) as image:
        if image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1:
            raise ValueError(f'{label}不是单帧 PNG')
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert('RGBA')
    require_transparent(rgba, label)
    return rgba


def validate_asset(source, candidate, *, lock_alpha=True):
    src_alpha = require_transparent(source, '原图')
    dst_alpha = require_transparent(candidate, '输出图')
    if source.size != candidate.size:
        raise ValueError('输出图尺寸与原图不一致')
    if lock_alpha and src_alpha.tobytes() != dst_alpha.tobytes():
        raise ValueError('输出图 Alpha 与原图不一致')


def composite_interior(source, aligned):
    source_alpha = source.getchannel('A')
    mask = ImageChops.multiply(source_alpha.point([0] * 240 + [255] * 16),
                              aligned.getchannel('A').point([0] * 240 + [255] * 16))
    # Keep two pixels around the source edge and holes; soften the transition inward.
    soft = ImageChops.add(mask.filter(ImageFilter.MinFilter(5)).point(lambda x: x // 3),
                         mask.filter(ImageFilter.MinFilter(7)).point(lambda x: x // 3))
    soft = ImageChops.add(soft, mask.filter(ImageFilter.MinFilter(9)).point(lambda x: x // 3))
    if soft.getbbox() is None:
        raise ValueError('对位后没有可安全合成的主体内部')
    result = Image.composite(aligned, source, soft)
    result.putalpha(source_alpha)
    return result


def main():
    parser = argparse.ArgumentParser(description='离线检查道具 PNG 的透明度、原尺寸和文件名')
    parser.add_argument('source', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--allow-edge-change', action='store_true', help='仅用于已登记的局部轮廓调整')
    args = parser.parse_args()
    try:
        if args.source.name != args.candidate.name:
            raise ValueError('输出图文件名与原图不一致')
        validate_asset(read_transparent(args.source.read_bytes(), '原图'),
                       read_transparent(args.candidate.read_bytes(), '输出图'),
                       lock_alpha=not args.allow_edge_change)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'技术检查未通过：{exc}\n')
    print('透明度、尺寸和文件名检查通过；仍需外观验收。')


if __name__ == '__main__':
    main()

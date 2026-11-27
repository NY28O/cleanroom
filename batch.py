"""道具图批次 CLI：预检、建批次、提交、恢复、验收和发布。"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from urllib.parse import urlsplit
import hashlib
import json
import os
import re
import html
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from preflight import require_source_dir, check
from restore_canvas import restore_one
from transparent_png import REQUEST_FIELDS, read_transparent, validate_asset


ROOT = Path(__file__).resolve().parent
CHECKLIST = ROOT / "03_批量运行" / "已修改核对清单.md"
PROMPT = ROOT / "01_规则与提示词" / "温暖家居_编辑提示词.txt"
GROUP_LINE = re.compile(r"^\| (\d+)-x \| ([^|]+?) \|.*\| (.*?) \|$")
FILE_NAME = re.compile(r"^(\d+)-(\d+)\.png$")
DEFAULT_MODEL = "gpt-image-2.6-sunburst-tokenhub"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def group_rows(project_root: Path, start: int, end: int):
    text = (project_root / "03_批量运行" / "已修改核对清单.md").read_text(encoding="utf-8-sig")
    selected = []
    for line in text.splitlines():
        match = GROUP_LINE.match(line)
        if not match:
            continue
        group = int(match.group(1))
        if start <= group <= end:
            names = sorted(set(re.findall(rf"(?<![\d-])({group}-\d+) ☐", match.group(3))), key=lambda n: int(n.split("-")[1]))
            selected.extend((group, match.group(2).strip(), f"{name}.png") for name in names)
    if not selected:
        raise ValueError("分组清单在指定范围内没有原图")
    return selected


def build_candidates(project_root: Path, source_dir: Path, start: int, end: int):
    candidates = []
    seen = set()
    for group, group_name, filename in group_rows(project_root, start, end):
        if filename in seen:
            continue
        seen.add(filename)
        path = source_dir / filename
        data = path.read_bytes()
        image = read_transparent(data, filename)
        candidates.append({
            "file": filename,
            "source": filename,
            "group": group,
            "group_name": group_name,
            "sha256": sha256(data),
            "size": list(image.size),
            "status": "pending",
        })
    return candidates


def write_json(path: Path, value):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def init_batch(project_root: Path, source_dir: Path, start: int, end: int, batch_name: str | None = None):
    project_root = Path(project_root).resolve()
    source_dir = require_source_dir(str(source_dir))
    if not 0 < start <= end:
        raise ValueError("请明确指定有效的起止组号")
    check(project_root, start, end, source_dir)
    candidates = build_candidates(project_root, source_dir, start, end)
    if batch_name is None:
        batch_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_组{start}-{end}"
    if not re.fullmatch(r"[\w-]{1,80}", batch_name):
        raise ValueError("批次名只允许文字、数字、下划线和短横线")
    batch = project_root / "03_批量运行" / batch_name
    if source_dir == batch or source_dir in batch.parents or source_dir == project_root / "04_正式成品":
        raise ValueError("原图库与写入目录不能重叠")
    if batch.exists():
        raise ValueError(f"批次目录已存在：{batch}")
    template = (project_root / PROMPT.relative_to(ROOT)).read_text(encoding="utf-8")
    batch.mkdir()
    for name in ("raw", "requests", "恢复图", "待验收图"):
        (batch / name).mkdir(parents=True, exist_ok=True)
    (batch / "prompt.txt").write_text(template, encoding="utf-8")
    write_json(batch / "meta.json", {
        "created_at": now(), "project_root": str(project_root), "source_dir": str(source_dir),
        "start": start, "end": end, "candidate_count": len(candidates), "status": "prepared", "prompt_sha256": sha256(template.encode()),
    })
    (batch / "candidates.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates), encoding="utf-8"
    )
    write_json(batch / "review.json", {row["file"]: {"status": "pending", "note": ""} for row in candidates})
    (batch / "逐图台账.jsonl").write_text(
        "".join(json.dumps({"file": row["file"], "technical_status": "pending", "review_status": "pending"}, ensure_ascii=False) + "\n" for row in candidates),
        encoding="utf-8",
    )
    return batch


def read_candidates(batch: Path):
    rows = [json.loads(line) for line in (batch / "candidates.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    names = set()
    for r in rows:
        m = FILE_NAME.fullmatch(r["file"])
        if not m or r["file"] in names or r["source"] != r["file"] or int(m[1]) != r["group"]:
            raise ValueError("批次清单含无效或重复文件名")
        names.add(r["file"])
    return rows


def render_prompt(template: str, row: dict) -> str:
    width, height = row["size"]
    return (template.replace("{道具}", row["group_name"])
            .replace("{宽} × {高}", f"{width} × {height}")
            .replace("{主辅色}", "采用明显区别于原图的中低饱和暖色与一处清晰点色")
            .replace("{内部款式}", "保留原图结构并做清楚、克制的内部款式变化"))


def _multipart(fields: dict, filename: str, source: bytes):
    boundary = uuid.uuid4().hex
    body = b"".join(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
        for key, value in fields.items()
    )
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{filename}\"\r\n"
             "Content-Type: image/png\r\n\r\n").encode() + source + f"\r\n--{boundary}--\r\n".encode()
    return boundary, body


def submit_batch(batch: Path, first_only: bool = False):
    batch = Path(batch).resolve()
    meta = json.loads((batch / "meta.json").read_text(encoding="utf-8"))
    source_dir = require_source_dir(meta["source_dir"])
    template = (batch / "prompt.txt").read_text(encoding="utf-8")
    base = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    if not base or not key:
        raise ValueError("请先配置 OPENAI_BASE_URL 和 OPENAI_API_KEY。")
    endpoint = urlsplit(base)
    if not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or not (
        endpoint.scheme == "https" or endpoint.scheme == "http" and endpoint.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise ValueError("服务地址须为 HTTPS 或本机回环地址")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    model = os.environ.get("PROP_IMAGE_MODEL") or DEFAULT_MODEL
    quality = os.environ.get("PROP_IMAGE_QUALITY", "low")
    candidates = read_candidates(batch)
    review = json.loads((batch / "review.json").read_text("utf8"))
    check(ROOT, meta["start"], meta["end"], source_dir)
    if meta.get("prompt_sha256") != sha256(template.encode()):
        raise ValueError("提示词快照变化或缺少校验值，请另建批次")
    for row in candidates:
        if sha256((source_dir / row["file"]).read_bytes()) != row["sha256"]:
            raise ValueError("原图已变化：" + row["file"])
    for group in sorted({r["group"] for r in candidates}):
        rows = [r for r in candidates if r["group"] == group]
        states = [review[r["file"]]["status"] for r in rows]
        passed = sum(st in ("accepted", "published") for st in states)
        if all(st in ("accepted", "published", "rejected") for st in states) and passed * 10 >= len(rows) * 9 and states[0] != "rejected":
            continue
        if states[0] == "rejected":
            raise ValueError("代表图已退回，暂停本组")
        pilot = rows[0]
        selected = rows[1:] if review[pilot["file"]]["status"] in ("accepted", "published") else rows[:1]
        pending = [r for r in selected if review[r["file"]]["status"] == "pending" and not (batch / "raw" / r["file"]).exists()]
        if first_only:
            pending = pending[:1]
        for row in pending:
            name = row["file"]
            source = (source_dir / name).read_bytes()
            if sha256(source) != row["sha256"]:
                raise ValueError("原图发生变化：" + name)
            prompt = render_prompt(template, row)
            fields = dict(model=model, prompt=prompt, quality=quality,
                          size="{}x{}".format(*row["size"]), **REQUEST_FIELDS)
            logs = batch / "requests"
            if list(logs.glob(name + ".*.json")):
                raise ValueError(name + " 已有请求记录但没有原稿；先核查服务状态，不自动重发")
            for attempt in range(1, 4):
                log = logs / f"{name}.{attempt}.json"
                rec = dict(file=name, started_at=now(), attempt=attempt, settings=fields,
                           prompt_sha256=sha256(prompt.encode()), source_sha256=row["sha256"], status="processing")
                write_json(log, rec)
                start = time.monotonic()
                retry = False
                try:
                    boundary, body = _multipart(fields, name, source)
                    req = urllib.request.Request(base + "/images/edits", data=body, headers={
                        "Authorization": "Bearer " + key, "Content-Type": "multipart/form-data; boundary=" + boundary})
                    with opener.open(req, timeout=175) as resp:
                        rec.update(http=resp.status, request_id=resp.headers.get("x-request-id"))
                        payload = json.load(resp)
                    image = base64.b64decode(payload["data"][0]["b64_json"], validate=True)
                    with (batch / "raw" / name).open("xb") as fp:
                        fp.write(image)
                    rec.update(image_sha256=sha256(image), response_model=payload.get("model"), usage=payload.get("usage"))
                    read_transparent(image, "模型返回")
                    rec["status"] = "generated"
                except urllib.error.HTTPError as exc:
                    rec.update(http=exc.code, request_id=exc.headers.get("x-request-id"), status="rejected")
                    retry = exc.code == 429 and attempt < 3
                    delay = exc.headers.get("Retry-After", "")
                    if delay and not delay.isdecimal():
                        retry = False
                    wait = max((5, 15, 15)[attempt - 1], int(delay) if delay.isdecimal() else 0)
                except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
                    rec.update(status="hold", error=str(exc).replace(key, "[redacted]")[:400])
                finally:
                    rec["elapsed_seconds"] = round(time.monotonic() - start, 2)
                    write_json(log, rec)
                if rec["status"] == "generated":
                    break
                if not retry:
                    raise ValueError(f"{name} 请求未通过，请检查 {log.name}；未继续提交")
                time.sleep(wait)
        return [f"第 {group} 组本次提交 {len(pending)} 张；恢复后请复核。"]
    return ["本批次已全部放行。"]


def restore_batch(batch):
    source = require_source_dir(json.loads((batch / "meta.json").read_text("utf8"))["source_dir"])
    review = json.loads((batch / "review.json").read_text("utf8"))
    results = []
    for row in read_candidates(batch):
        name = row["file"]
        if not (batch / "raw" / name).is_file():
            results.append(dict(file=name, status="未生成"))
            continue
        try:
            result = restore_one(batch, source, row)
        except (ValueError, OSError) as exc:
            results.append(dict(file=name, status="技术未过", reason=str(exc)))
            continue
        results.append(result)
        if result["status"] == "待验收":
            data = (batch / result["output"]).read_bytes()
            target = batch / "待验收图" / name
            if target.exists() and target.read_bytes() != data:
                raise ValueError("待验收图发生变化：" + name)
            if not target.exists():
                with target.open("xb") as fp:
                    fp.write(data)
            result["review_sha256"] = sha256(data)
        result["review_status"] = review[name]["status"]
    write_json(batch / "恢复核验.json", results)
    ledger(batch)
    from urllib.parse import quote
    cards = []
    for r in results:
        if "output" not in r:
            continue
        n = r["file"]
        orig = (source / n).resolve().as_uri()
        restored = quote(r["output"])
        cards.append(f'<section><h2>{html.escape(n)}</h2><p>{html.escape(r["status"])}，Alpha 差异 {r["alpha_different_pixels"]} 像素</p>'
                     f'<p>原图 / 恢复稿（浅底、深底）</p><img src="{orig}"> <img src="{restored}"> <img class="dark" src="{restored}"></section>')
    (batch / "复核.html").write_text('<!doctype html><meta charset=utf-8><title>批次复核</title><style>img{background:#fafafa}img.dark{background:#34383b}</style>' + "".join(cards), encoding="utf8")
    return results


def ledger(batch):
    reports = batch / "恢复核验.json"
    results = {r["file"]:r for r in json.loads(reports.read_text("utf8"))} if reports.exists() else {}
    review = json.loads((batch / "review.json").read_text("utf8"))
    rows = [dict(file=n, technical_status=results.get(n, {}).get("status", "未生成"), review_status=v["status"])
            for n, v in review.items()]
    (batch / "逐图台账.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf8")


def verified(batch, name):
    rows = {r["file"]:r for r in read_candidates(batch)}
    if name not in rows:
        raise ValueError("文件不在当前批次：" + name)
    results = {r["file"]:r for r in json.loads((batch / "恢复核验.json").read_text("utf8"))}
    report = results.get(name, {})
    if report.get("status") != "待验收":
        raise ValueError("图片尚未通过技术检查：" + name)
    source = Path(json.loads((batch / "meta.json").read_text("utf8"))["source_dir"])
    orig = (source / name).read_bytes()
    data = (batch / "待验收图" / name).read_bytes()
    if sha256(orig) != rows[name]["sha256"] or sha256(data) != report["review_sha256"]:
        raise ValueError("原图或待验收图发生变化：" + name)
    validate_asset(read_transparent(orig), read_transparent(data))
    return data


def update_review(batch, files, status, note=""):
    path = batch / "review.json"
    review = json.loads(path.read_text("utf8"))
    for name in files:
        data = verified(batch, name)
        if review[name]["status"] != "published":
            review[name] = dict(status=status, note=note, updated_at=now(), sha256=sha256(data))
    write_json(path, review)
    ledger(batch)


def update_index(batch, names):
    index = ROOT / "03_批量运行" / "已修改核对清单.md"
    lines = index.read_text("utf-8-sig").splitlines()
    total = done = 0
    for i, line in enumerate(lines):
        m = GROUP_LINE.match(line)
        if not m:
            continue
        cols = line.split("|")
        for name in names:
            stem = Path(name).stem
            if stem.split("-")[0] == m[1]:
                cols[6] = re.sub(r"(?<![0-9-])" + re.escape(stem) + r" ☐", f"[{stem} ☑ 已验收](../04_正式成品/{name})", cols[6])
        n = cols[6].count("☑")
        total += int(cols[3])
        done += n
        cols[4], cols[5] = f" {n} ", f" {int(cols[3])-n} "
        if any(name.split("-")[0] == m[1] for name in names):
            lines[i] = "|".join(cols)
    content = "\n".join(lines) + "\n"
    content = re.sub(r"统一绘本风格已输出 \*\*[\d,]+ 张\*\*，待输出 \*\*[\d,]+ 张\*\*",
                     f"统一绘本风格已输出 **{done:,} 张**，待输出 **{total-done:,} 张**", content)
    tmp = index.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf8")
    tmp.replace(index)


def publish_batch(batch, files=None):
    path = batch / "review.json"
    review = json.loads(path.read_text("utf8"))
    names = files or [n for n,i in review.items() if i["status"] == "accepted"]
    dest = ROOT / "04_正式成品"
    planned = {}
    for n in names:
        if review.get(n, {}).get("status") != "accepted":
            raise ValueError("尚未放行：" + n)
        data = verified(batch, n)
        if review[n]["sha256"] != sha256(data) or (dest/n).exists():
            raise ValueError("验收稿变化或已有同名成品：" + n)
        planned[n] = data
    dest.mkdir(exist_ok=True)
    for n, data in planned.items():
        with (dest/n).open("xb") as out:
            out.write(data)
        review[n]["status"] = "published"
    update_index(batch, planned)
    write_json(path, review)
    ledger(batch)
    return names


@contextmanager
def lock(path):
    try:
        fp = path.open("x", encoding="utf8")
    except FileExistsError:
        raise ValueError(f"有操作正在进行；如上次中断，请先核实记录再清理 {path.name}") from None
    try:
        with fp:
            fp.write(str(os.getpid()))
        yield
    finally:
        path.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--start", type=int, required=True)
    init.add_argument("--end", type=int, required=True)
    init.add_argument("--source-dir", required=True)
    init.add_argument("--name")
    submit = sub.add_parser("submit")
    submit.add_argument("batch", type=Path)
    submit.add_argument("--first-only", action="store_true")
    restore = sub.add_parser("restore")
    restore.add_argument("batch", type=Path)
    accept = sub.add_parser("accept")
    accept.add_argument("batch", type=Path)
    accept.add_argument("files", nargs="+")
    publish = sub.add_parser("publish")
    publish.add_argument("batch", type=Path)
    publish.add_argument("files", nargs="*")
    status = sub.add_parser("status")
    status.add_argument("batch", type=Path)
    sub.add_parser("doctor", help="离线检查配置，不显示密钥")
    reject = sub.add_parser("reject")
    reject.add_argument("batch", type=Path)
    reject.add_argument("files", nargs="+")
    reject.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    if args.command == "doctor":
        missing = [k for k in ("OPENAI_BASE_URL","OPENAI_API_KEY") if not os.environ.get(k)]
        if missing:
            raise ValueError("请设置：" + "、".join(missing))
        print("本机服务配置已设置；未联网验证模型和服务。")
        return
    if args.command == "init":
        print(init_batch(ROOT, Path(args.source_dir), args.start, args.end, args.name))
        return
    args.batch = args.batch.resolve()
    if args.batch.parent != (ROOT / "03_批量运行").resolve():
        raise ValueError("请选择本项目内的独立批次目录")
    if args.command == "status":
        print((args.batch / "逐图台账.jsonl").read_text("utf8"))
        return
    with lock(args.batch / ".run.lock"):
        perform(args)


def perform(args):
    if args.command == "submit":
        print("\n".join(submit_batch(args.batch, args.first_only)))
    elif args.command == "restore":
        print(json.dumps(restore_batch(args.batch), ensure_ascii=False, indent=2))
    elif args.command == "reject":
        path = args.batch / "review.json"
        review = json.loads(path.read_text("utf8"))
        for n in args.files:
            if n not in review or review[n]["status"] == "published":
                raise ValueError("不在批次内或已发布：" + n)
            review[n] = dict(status="rejected", note=args.reason, updated_at=now())
        write_json(path, review)
        ledger(args.batch)
    elif args.command == "accept":
        update_review(args.batch, args.files, "accepted")
    elif args.command == "publish":
        with lock(ROOT / "03_批量运行" / ".publish.lock"):
            print("\n".join(publish_batch(args.batch, args.files or None)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None

"""独立安装入口。安装目录只读，批次和清单状态归使用者的工作区。"""
import argparse
import os
from pathlib import Path
import sys
import json
import shutil
import re
import tempfile
import zipfile
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"
INDEX = Path("03_批量运行/已修改核对清单.md")
PROMPT = Path("01_规则与提示词/温暖家居_编辑提示词.txt")
STATE = SKILL / ".skill-state.json"
REPO = "NY28O/cleanroom"
SKILL_PATH = "skill/prop-image-batch"


def check_install():
    if sys.version_info < (3, 9):
        raise ValueError("需要 Python 3.9 或以上版本")
    try:
        import PIL.Image
        pillow = version("Pillow")
        from PIL.Image import Resampling
    except (ImportError, PackageNotFoundError):
        raise ValueError(f'尚不能预检：此 Python 缺少可用的 Pillow。用同一解释器执行 -m pip install -r "{SKILL / "requirements.txt"}"，然后重跑 check-install。')
    for path in (INDEX, PROMPT):
        if not (ASSETS / path).is_file():
            raise ValueError("安装文件缺失：" + str(path))
    return pillow


def service_issues():
    """只返回操作提示，避免把配置值或 URL 解析错误带进日志。"""
    issues = []
    base = os.environ.get("OPENAI_BASE_URL", "")
    if not base.strip():
        issues.append("缺服务地址 OPENAI_BASE_URL：向服务商或团队管理员索取 API 基础地址（含服务要求的前缀）。")
    else:
        try:
            url = urlsplit(base)
            valid = (url.hostname and not url.username and not url.password and not url.query
                     and not url.fragment and not any(c.isspace() for c in base)
                     and not url.path.rstrip("/").endswith("/images/edits")
                     and (url.scheme == "https" or url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")))
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            issues.append("请更正 OPENAI_BASE_URL：填写 HTTPS 基础地址，不带密钥、查询参数或 /images/edits；本机回环地址可用 HTTP。")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        issues.append("缺访问密钥 OPENAI_API_KEY：从该服务领取，在本机填写，不要发到聊天里。")
    return issues


def _remote_revision():
    url = os.environ.get("PROP_IMAGE_UPDATE_API") or (
        f"https://api.github.com/repos/{REPO}/commits?path={SKILL_PATH}&per_page=1")
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "prop-image-batch-skill"})
    with urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not isinstance(payload, list) or not payload:
        raise ValueError("远端没有找到 Skill 版本记录")
    item = payload[0]
    sha = item["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha): raise ValueError("远端缺少完整版本标识")
    with urlopen(f"https://raw.githubusercontent.com/{REPO}/{sha}/{SKILL_PATH}/VERSION.json",timeout=20) as response:
        release = json.load(response).get("release")
    return {"revision": sha, "release": release, "message": item["commit"]["message"].splitlines()[0],
            "date": item["commit"]["committer"]["date"]}


def _installed_revision():
    if STATE.is_file():
        return json.loads(STATE.read_text("utf8"))
    version_file = SKILL / "VERSION.json"
    if version_file.is_file():
        return json.loads(version_file.read_text("utf8"))
    return {"revision": None, "message": "旧安装未记录版本"}


def same_revision(local, remote):
    if local.get("revision") and remote.get("revision"):
        return local["revision"] == remote["revision"]
    return bool(local.get("release")) and local["release"] == remote.get("release")


def check_update():
    local = _installed_revision()
    try:
        remote = _remote_revision()
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(f"暂时无法核对远端版本（{getattr(exc,'code',None) or '网络或版本信息不可用'}），本地文件未改变。")
        return local, None
    if same_revision(local, remote):
        print(f"Skill 已是最新版本：{remote['revision'][:12]}")
    elif local.get("revision") or local.get("release"):
        print(f"发现新版本：本地 {str(local.get('revision') or local.get('release'))[:16]} → 远端 {remote['revision'][:12]}")
        print(f"变更摘要：{remote['message']}")
        print("当前未更新；用户明确说“更新”后再执行 update。")
    else:
        print("当前 Skill 未记录版本，无法安全比较；用户明确说“更新”后将获取远端版本。")
        print(f"远端版本：{remote['revision'][:12]}；摘要：{remote['message']}")
    return local, remote


def update_skill():
    if (SKILL.parents[1] / "package_workflow.py").is_file() or (SKILL.parents[1] / ".git").exists() and SKILL.parent.name == "skill":
        raise ValueError("仓库副本不使用安装更新命令，请通过仓库发布流程更新")
    local, remote = check_update()
    if remote is None: raise ValueError("本次未更新；可稍后重试")
    if same_revision(local, remote):
        return
    archive_url = os.environ.get("PROP_IMAGE_UPDATE_ARCHIVE") or f"https://github.com/{REPO}/archive/{remote['revision']}.zip"
    with tempfile.TemporaryDirectory(prefix="prop-image-update-") as folder:
        archive = Path(folder) / "repo.zip"
        request = Request(archive_url, headers={"User-Agent": "prop-image-batch-skill"})
        with urlopen(request, timeout=60) as response:
            archive.write_bytes(response.read())
        extract = Path(folder) / "extract"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extract)
        candidates = list(extract.glob(f"*/{SKILL_PATH}"))
        if len(candidates) != 1 or not (candidates[0] / "SKILL.md").is_file():
            raise ValueError("远端压缩包中没有有效的 Skill 目录")
        source = candidates[0]
        for item in source.rglob("*"):
            if item.is_file():
                target = SKILL / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    STATE.write_text(json.dumps(remote, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(f"Skill 已更新到 {remote['revision'][:12]}。工作区、批次和本机配置未修改。")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd() / "道具修图工作区")
    parser.add_argument("command", choices=("check-install", "check-update", "update", "preflight", "init", "checkpoint", "submit", "restore", "accept", "reject", "publish", "status", "doctor"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    pillow = check_install()
    sys.path.insert(0, str(SKILL / "scripts"))
    from engine import batch as engine
    from engine.preflight import check, require_source_dir
    if args.command in ("check-install", "doctor"):
        print(f"本机可以预检原图（Pillow {pillow}）。")
        issues = service_issues()
        print("出图：配置待完善。" if issues else "出图：本地配置检查通过，尚未实际验证。")
        for issue in issues:
            print(issue)
        if not os.environ.get("PROP_IMAGE_MODEL", "").strip():
            print("未指定模型：将使用内置默认值；请向服务方确认支持的图像编辑模型，必要时设置 PROP_IMAGE_MODEL。")
        if issues:
            print("下一步：按本机系统查看 " + str(SKILL / "references" / "setup.md"))
            if args.command == "doctor":
                raise SystemExit(1)
        return
    if args.command == "check-update":
        check_update(); return
    if args.command == "update":
        update_skill(); return
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

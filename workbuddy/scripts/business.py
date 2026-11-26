"""WorkBuddy-only launcher for a persistent, isolated business workspace."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

if __package__:
    from .python_runtime import RuntimeSetupError, prepare_python
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from python_runtime import RuntimeSetupError, prepare_python

SECTIONS = {"sellers", "buyers", "format_defaults", "terms_templates", "defaults", "packing"}


class SetupError(Exception):
    pass


@contextmanager
def workspace_lock(root):
    with (root / ".workbuddy.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SetupError("这个业务目录正在使用，请稍后再试。") from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SetupError("这个业务目录正在使用，请稍后再试。") from exc
        yield


def engine_config(engine):
    return engine / "trade_pipeline/config/config.yaml"


def restored_engine(container):
    if container.resolve() != container:
        raise SetupError("隔离引擎目录经符号链接转向其它位置。")
    if not container.is_dir():
        return None
    for attempt in sorted(container.iterdir()):
        if attempt.is_dir() and not attempt.is_symlink():
            marker = attempt / "ready"
            engine = attempt / "engine"
            if (not marker.is_symlink() and marker.is_file() and marker.read_bytes() == b"ready"
                    and engine.resolve() == engine and engine_config(engine).is_file()):
                return engine
    return None


def workspace_engine(root):
    if engine_config(root).is_file():
        return root
    legacy = root / "engine"
    if legacy.exists() or legacy.is_symlink():
        return legacy
    return restored_engine(root / ".workbuddy-engines" / "shared") or legacy


def restore_engine(container):
    previous = restored_engine(container)
    if previous is not None:
        return previous
    container.mkdir(parents=True, exist_ok=True)
    attempt = container / uuid4().hex
    attempt.mkdir()
    engine = attempt / "engine"
    subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).with_name("prepare_engine.py")), str(engine)],
        check=True, stdout=sys.stderr,
    )
    with (attempt / "ready").open("xb") as stream:
        stream.write(b"ready")
        stream.flush()
        os.fsync(stream.fileno())
    return engine


def prepare(root, dedicated=False):
    if dedicated:
        manifest = Path(__file__).with_name("engine_manifest.json")
        content_id = hashlib.sha256(manifest.read_bytes()).hexdigest()[:24]
        engine = restore_engine(root / ".workbuddy-engines" / content_id)
    else:
        engine = workspace_engine(root)
        if not engine.exists() and not engine.is_symlink():
            engine = restore_engine(root / ".workbuddy-engines" / "shared")
    config = engine_config(engine)
    if engine.is_symlink() or not config.is_file() or config.resolve() != config:
        raise SetupError("这个业务目录缺少可用配置，请检查原目录或选择一个新的空业务目录。")

    return engine, prepare_python(root, dedicated)


def merge_fields(target, changes):
    target = target.copy()
    for key, value in changes.items():
        if not isinstance(key, str) or not key:
            raise SetupError("配置字段名无效。")
        if isinstance(value, dict):
            child = target.get(key, {})
            if not isinstance(child, dict):
                raise SetupError("配置字段结构不同，请重新核对要修改的字段。")
            target[key] = merge_fields(child, value)
        else:
            if isinstance(target.get(key), dict):
                raise SetupError("请逐项修改配置，不能用单个值替换整个配置段。")
            target[key] = value
    return target


def patch_config(config: Path, patch: Path, expected: str):
    import yaml

    original = config.read_bytes()
    if hashlib.sha256(original).hexdigest() != expected:
        raise SetupError("配置已改动，请重新读取配置并确认本次修改。")
    changes = json.loads(patch.read_text(encoding="utf-8"))
    if (not isinstance(changes, dict) or not changes or changes.keys() - SECTIONS
            or any(not isinstance(value, dict) for value in changes.values())):
        raise SetupError("请按公司、客户、单据格式、条款、默认值或包装中的具体字段提交修改。")
    try:
        current = yaml.safe_load(original)
    except yaml.YAMLError as exc:
        raise SetupError("业务配置格式无法读取，请先检查原文件。") from exc
    if not isinstance(current, dict):
        raise SetupError("业务配置格式无法读取，请先检查原文件。")
    updated = merge_fields(current, changes)
    if updated == current:
        print("配置已是确认后的内容。")
        return
    data = yaml.safe_dump(updated, allow_unicode=True, sort_keys=False).encode("utf-8")
    with tempfile.TemporaryDirectory(dir=config.parent) as scratch:
        replacement = Path(scratch) / "config.yaml"
        replacement.write_bytes(data)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix="config-", suffix=".yaml.bak", dir=config.parent, delete=False,
        ) as backup:
            backup.write(original)
        os.replace(replacement, config)
    print("配置已更新。旧版本备份：" + backup.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("locate")
    actions.add_parser("prepare")
    for action in ("inspect", "draft"):
        intake = actions.add_parser(action)
        intake.add_argument("source", type=Path)
        intake.add_argument("output", type=Path)
    patch = actions.add_parser("patch")
    patch.add_argument("file", type=Path)
    patch.add_argument("revision")
    quote = actions.add_parser("quote")
    quote.add_argument("inquiry", type=Path)
    quote.add_argument("order")
    quote.add_argument("buyer")
    quote.add_argument("output", type=Path)
    quote.add_argument("--confirm", type=Path)
    for action in ("terms-review", "writeback"):
        formal = actions.add_parser(action)
        formal.add_argument("quotation", type=Path)
        formal.add_argument("model", type=Path)
        formal.add_argument("--documents", nargs="+", choices=("pi", "ci", "pl"), default=["pi"])
        formal.add_argument("--output-dir", type=Path)
        if action == "writeback":
            formal.add_argument("--review-token")
    documents = actions.add_parser("documents")
    documents.add_argument("operation", choices=(
        "check", "review", "draft", "formal", "snapshot", "status", "delivery", "confirm-actuals",
    ))
    documents.add_argument("order")
    documents.add_argument("--source", type=Path, action="append", default=[])
    documents.add_argument("--snapshot", type=Path)
    documents.add_argument("--documents", nargs="+", choices=("pi", "ci", "pl"))
    documents.add_argument("--review-token")
    documents.add_argument("--sync", action="store_true")
    documents.add_argument("--file", type=Path, action="append", default=[])
    args = parser.parse_args()

    if sys.version_info < (3, 11):
        raise SetupError("真实业务需要 WorkBuddy 能调用 Python 3.11 或更新版本。你仍可以直接试用示例。")
    if args.workspace == Path("default"):
        args.workspace = Path.home() / "Documents" / "外贸单证管线"
    if not args.workspace.is_absolute():
        raise SetupError("请选择一个明确的长期业务目录。")
    root = args.workspace.resolve()
    if args.action == "locate":
        config = engine_config(workspace_engine(root))
        if not config.is_file() or config.resolve() != config:
            raise SetupError("此目录还没有可复用的业务配置。可以先处理当前文件。")
        print(str(config))
        return 0
    root.mkdir(parents=True, exist_ok=True)
    if args.action == "documents":
        with workspace_lock(root):
            engine, python = prepare(root, dedicated=True)
        command = [
            str(python), "-I", "-B", str(Path(__file__).with_name("documents.py")),
            str(engine), str(root), args.operation, args.order,
        ]
        for source in args.source:
            command.extend(["--source", str(source.resolve(strict=True))])
        if args.snapshot:
            command.extend(["--snapshot", str(args.snapshot.resolve(strict=True))])
        if args.documents:
            command.extend(["--documents", *args.documents])
        if args.review_token:
            command.extend(["--review-token", args.review_token])
        if args.sync:
            command.append("--sync")
        for path in args.file:
            command.extend(["--file", str(path)])
        return subprocess.call(command, cwd=engine)
    with workspace_lock(root):
        engine, python = prepare(root, dedicated=args.action in ("inspect", "draft"))
        config = engine / "trade_pipeline/config/config.yaml"
        if args.action == "prepare":
            print("可复用业务配置：" + str(config))
            print("配置版本：" + hashlib.sha256(config.read_bytes()).hexdigest())
            return 0
        if args.action in ("inspect", "draft"):
            return subprocess.call([
                str(python), "-I", "-B", str(Path(__file__).with_name("intake.py")),
                args.action, str(args.source.resolve(strict=True)), str(args.output.resolve()),
            ])
        if args.action == "patch":
            # Run with the isolated YAML dependency. The parent holds the workspace lock.
            return subprocess.call([
                str(python), "-I", "-B", str(Path(__file__).resolve()), "_patch",
                str(config), str(args.file.resolve(strict=True)), args.revision,
            ])
        if args.action in ("terms-review", "writeback"):
            command = [
                str(python), "-I", "-B", str(Path(__file__).with_name("formal.py")),
                str(engine), args.action, str(args.quotation.resolve(strict=True)),
                str(args.model.resolve(strict=True)), "--documents", *args.documents,
            ]
            if args.output_dir:
                command.extend(["--output-dir", str(args.output_dir.resolve(strict=True))])
            if args.action == "writeback" and args.review_token:
                command.extend(["--review-token", args.review_token])
            return subprocess.call(command, cwd=engine)
        if subprocess.run([
            str(python), "-I", "-B", "-c",
            "import sys, yaml; "
            "data = yaml.safe_load(open(sys.argv[1], encoding='utf-8')); "
            "sys.exit(0 if isinstance(data, dict) and data.get('sellers') else 1)",
            str(config),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise SetupError("请先在 WorkBuddy 核对并保存真实卖家资料。")
        if not args.order or not all(c.isalnum() or c in "-_" for c in args.order):
            raise SetupError("订单号只接受字母、数字、短横线和下划线。")
        inquiry = args.inquiry.resolve(strict=True)
        review = args.confirm.resolve(strict=True) if args.confirm else None
        output = args.output.resolve()
        if output.exists():
            raise SetupError("输出目录已经存在，请为本次报价选择新目录。")
        output.mkdir(parents=True, exist_ok=False)
        command = [
            "--input", str(inquiry), "--order", args.order,
            "--buyer", args.buyer, "--output-dir", str(output), "--quote-only",
            "--no-catalog-save",
        ]
        if review:
            command.extend(["--confirm", str(review)])
        return subprocess.call([str(python), "-E", "-s", "-B", "-m", "trade_pipeline", *command],
                               cwd=engine)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 5 and sys.argv[1] == "_patch":
            patch_config(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
        else:
            sys.exit(main())
    except (SetupError, RuntimeSetupError, OSError, ValueError, subprocess.SubprocessError) as exc:
        # Do not expose YAML/JSON contents or pip's raw logs in the user-facing summary.
        message = str(exc) if isinstance(exc, (SetupError, RuntimeSetupError)) else "无法完成操作，请检查所选目录和文件后重试。"
        sys.exit(message)

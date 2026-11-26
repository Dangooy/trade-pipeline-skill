"""Prepare or reuse WorkBuddy's isolated Python runtime without running pip."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

READINESS = """
import json, sys
from importlib.metadata import version
from pathlib import Path
import et_xmlfile, openpyxl, yaml

if sys.prefix == sys.base_prefix:
    raise SystemExit(1)
dedicated, archive, versions = sys.argv[1:]
if dedicated == "1" and openpyxl.__version__.split(".")[:2] != ["3", "1"]:
    raise SystemExit(1)
if archive:
    expected = json.loads(versions)
    for name, module in (("openpyxl", openpyxl), ("et-xmlfile", et_xmlfile), ("PyYAML", yaml)):
        if version(name) != expected[name] or not Path(module.__file__).is_relative_to(archive):
            raise SystemExit(1)
"""


class RuntimeSetupError(Exception):
    pass


def interpreter(environment):
    relative = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return environment / relative


def ready(environment, dedicated, *, archive=None, versions=None):
    settings = environment / "pyvenv.cfg"
    python = interpreter(environment)
    if (environment.resolve() != environment or settings.is_symlink()
            or not settings.is_file() or not python.is_file()):
        return False
    config = dict(
        (key.strip().casefold(), value.strip().casefold())
        for line in settings.read_text(encoding="utf-8").splitlines()
        if "=" in line for key, _, value in [line.partition("=")]
    )
    if config.get("include-system-site-packages") != "false":
        return False
    return subprocess.run(
        [str(python), "-I", "-B", "-c", READINESS, str(int(dedicated)),
         str(archive or ""), json.dumps(versions or {})],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def write_new(path, contents):
    with path.open("xb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())


def bundled_runtime(package):
    manifest = json.loads((package / "python_runtime.json").read_bytes())
    archive = (package / "python_runtime.zip").read_bytes()
    identifier = hashlib.sha256(archive).hexdigest()
    if identifier != manifest["sha256"]:
        raise RuntimeSetupError("技能包内的 Python 组件校验失败，请重新导入完整技能包。")
    return identifier, archive, manifest["versions"]


def prepare_python(root, dedicated=False):
    legacy = root / ".workbuddy-venv"
    try:
        if ready(legacy, dedicated):
            return interpreter(legacy)
        identifier, archive, versions = bundled_runtime(Path(__file__).resolve().parent)
        bucket = root / ".workbuddy-python" / identifier
        if bucket.resolve() != bucket:
            raise RuntimeSetupError("隔离 Python 环境目录经符号链接转向了其它位置。")
        bucket.mkdir(parents=True, exist_ok=True)
        marker_contents = identifier.encode("ascii")
        for attempt in sorted(bucket.iterdir()):
            marker = attempt / "runtime.ready"
            archive_path = attempt / "dependencies.zip"
            if (attempt.is_symlink() or marker.is_symlink() or archive_path.is_symlink()
                    or not marker.is_file() or marker.read_bytes() != marker_contents
                    or not archive_path.is_file()):
                continue
            if hashlib.sha256(archive_path.read_bytes()).hexdigest() != identifier:
                continue
            if ready(attempt / "venv", dedicated, archive=archive_path, versions=versions):
                return interpreter(attempt / "venv")

        # Each interrupted attempt stays private. A new attempt never writes over it.
        attempt = bucket / uuid4().hex
        attempt.mkdir()
        environment = attempt / "venv"
        subprocess.run([sys.executable, "-I", "-B", "-m", "venv", "--without-pip", str(environment)],
                       check=True, timeout=60)
        python = interpreter(environment)
        site_packages = Path(subprocess.check_output(
            [str(python), "-I", "-B", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True, timeout=30,
        ).strip())
        if (site_packages.resolve() != site_packages or environment not in site_packages.parents
                or not site_packages.is_dir()):
            raise RuntimeSetupError("无法确认独立 Python 环境的组件路径，已停止准备。")

        archive_path = attempt / "dependencies.zip"
        write_new(archive_path, archive)
        # Relative to the venv's site-packages. site adds the ZIP without unpacking it.
        archive_entry = os.path.relpath(archive_path, site_packages).encode("ascii")
        write_new(site_packages / "workbuddy_runtime.pth", archive_entry + b"\n")
        if not ready(environment, dedicated, archive=archive_path, versions=versions):
            raise RuntimeSetupError("技能包内的 Python 组件无法载入，请重新导入完整技能包。")
        write_new(attempt / "runtime.ready", marker_contents)
        return python
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        raise RuntimeSetupError("独立 Python 环境暂未准备好。请在 WorkBuddy 重试，原文件保持原样。") from exc

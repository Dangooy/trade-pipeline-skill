"""WorkBuddy runtime bootstrap is isolated, offline and safe to retry."""
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from workbuddy.scripts import python_runtime


@pytest.fixture
def offline_bundle(tmp_path, monkeypatch):
    output = io.BytesIO()
    versions = {"openpyxl": "3.1.5", "et-xmlfile": "2.0.0", "PyYAML": "6.0.3"}
    with ZipFile(output, "w") as archive:
        for name, module in (("openpyxl", "openpyxl"), ("et-xmlfile", "et_xmlfile"), ("PyYAML", "yaml")):
            version = versions[name]
            archive.writestr(f"{module}/__init__.py", f"__version__ = {version!r}\n")
            dist = f"{name.replace('-', '_')}-{version}.dist-info"
            archive.writestr(f"{dist}/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    content = output.getvalue()
    identifier = hashlib.sha256(content).hexdigest()
    package = tmp_path / "package"
    package.mkdir()
    (package / "python_runtime.zip").write_bytes(content)
    (package / "python_runtime.json").write_text(
        json.dumps({"sha256": identifier, "versions": versions}), encoding="utf-8",
    )
    monkeypatch.setattr(python_runtime, "__file__", str(package / "python_runtime.py"))
    return package, identifier


def test_cold_python_uses_no_pip_or_global_site_packages(tmp_path, offline_bundle, monkeypatch):
    root = tmp_path / "虚构业务"
    commands = []
    original = subprocess.run

    def record(args, **kwargs):
        commands.append(args)
        assert "pip" not in args and "ensurepip" not in args
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", record)
    python = python_runtime.prepare_python(root, dedicated=True)
    creates = [args for args in commands if "-m" in args]
    assert len(creates) == 1 and "--without-pip" in creates[0]
    probe = subprocess.check_output(
        [str(python), "-I", "-B", "-c",
         "import importlib.util, sys; import openpyxl; "
         "assert importlib.util.find_spec('pip') is None; print(sys.prefix); print(openpyxl.__file__)"],
        text=True,
    ).splitlines()
    assert Path(probe[0]).is_relative_to(root / ".workbuddy-python")
    assert "dependencies.zip" in probe[1]
    assert not list(root.glob("**/__pycache__"))
    assert python_runtime.prepare_python(root, dedicated=True) == python
    assert len([args for args in commands if "-m" in args]) == 1


def test_interrupted_bootstrap_starts_a_new_private_attempt(tmp_path, offline_bundle, monkeypatch):
    _, identifier = offline_bundle
    root = tmp_path / "fake-business"
    root.mkdir()
    old = root / ".workbuddy-venv"
    old.mkdir()
    (old / "protected.txt").write_text("old version")
    write = python_runtime.write_new

    def interrupted(path, data):
        if path.suffix == ".pth":
            write(path, data[:4])
            raise PermissionError("simulated partial setup")
        write(path, data)

    with monkeypatch.context() as failure:
        failure.setattr(python_runtime, "write_new", interrupted)
        with pytest.raises(python_runtime.RuntimeSetupError):
            python_runtime.prepare_python(root, dedicated=True)
    bucket = root / ".workbuddy-python" / identifier
    initial, = tuple(bucket.iterdir())
    pth, = tuple(initial.glob("**/*.pth"))
    partial = pth.read_bytes()
    assert not (initial / "runtime.ready").exists()
    python = python_runtime.prepare_python(root, dedicated=True)
    assert not python.is_relative_to(initial)
    assert pth.read_bytes() == partial
    assert (old / "protected.txt").read_text() == "old version"
    assert python_runtime.prepare_python(root, dedicated=True) == python
    assert sum(1 for path in bucket.iterdir() if (path / "runtime.ready").is_file()) == 1


def test_prepared_legacy_environment_is_reused(tmp_path, offline_bundle, monkeypatch):
    package, _ = offline_bundle
    root = tmp_path / "legacy-business"
    legacy = root / ".workbuddy-venv"
    subprocess.run([sys.executable, "-I", "-B", "-m", "venv", "--without-pip", str(legacy)], check=True)
    python = python_runtime.interpreter(legacy)
    site_packages = Path(subprocess.check_output(
        [str(python), "-I", "-B", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        text=True,
    ).strip())
    archive = site_packages / "previous-install.zip"
    archive.write_bytes((package / "python_runtime.zip").read_bytes())
    (site_packages / "previous-install.pth").write_text(archive.name + "\n", encoding="utf-8")
    monkeypatch.setattr(python_runtime, "bundled_runtime", lambda _: pytest.fail("rebuilt an existing runtime"))
    assert python_runtime.prepare_python(root, dedicated=True) == python
    assert not (root / ".workbuddy-python").exists()


def test_bad_archive_is_rejected_before_preparing_environment(tmp_path, offline_bundle):
    package, _ = offline_bundle
    (package / "python_runtime.zip").write_bytes(b"changed")
    root = tmp_path / "new-business"
    with pytest.raises(python_runtime.RuntimeSetupError, match="校验失败"):
        python_runtime.prepare_python(root, dedicated=True)
    assert not root.exists()

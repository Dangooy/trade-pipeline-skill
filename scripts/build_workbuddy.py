"""Build the WorkBuddy ZIP from the tracked v1.6.0 engine."""
import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from importlib.metadata import distribution
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
ENGINE = "65d83125c7513b5e891b58def3c3e17b377897fb"  # v1.6.0
ASSETS = (
    "LICENSE", "README.md", "pyproject.toml", "requirements.txt",
    "examples/demo_config.yaml", "examples/sample_inquiry.xlsx", "trade_pipeline",
)
ENGINE_UPDATES = {
    # 打印版式的共享函数放在 base_writer.py，必须与三个 Writer 一起从
    # 工作树覆盖进包，否则打包后会回退到 v1.6.0 的旧 base_writer，
    # Writer 引用的新函数不存在，版式也不一致。
    "trade_pipeline/writers/base_writer.py",
    "trade_pipeline/writers/pi_writer.py", "trade_pipeline/writers/ci_writer.py",
    "trade_pipeline/writers/pl_writer_lite.py",
}
PYTHON_PACKAGES = {
    "openpyxl": ("3.1.5", "openpyxl"),
    "et-xmlfile": ("2.0.0", "et_xmlfile"),
    "PyYAML": ("6.0.3", "yaml"),
}


def build_python_runtime():
    """Bundle the known pure Python modules and their upstream attribution."""
    contents = io.BytesIO()
    versions = {}
    with zipfile.ZipFile(contents, "w", compression=zipfile.ZIP_DEFLATED) as runtime:
        for name, (version, module) in PYTHON_PACKAGES.items():
            dist = distribution(name)
            if dist.version != version or not dist.files:
                raise ValueError(f"Build requires {name}=={version} from an installed wheel.")
            licences = set(dist.metadata.get_all("License-File") or ())
            upstream = {"METADATA", *(Path(label).name for label in licences)}
            recorded = set()
            package_files = []
            for item in dist.files:
                if item.is_absolute() or ".." in item.parts or len(item.parts) < 2:
                    continue
                top = item.parts[0]
                if top == module and item.suffix in {".py", ".typed"}:
                    package_files.append(item)
                elif top.endswith(".dist-info") and item.name in upstream:
                    package_files.append(item)
                    recorded.add(item.name)
            if not licences or not upstream <= recorded:
                raise ValueError(f"Missing upstream licence or metadata for {name}.")
            for item in sorted(package_files):
                data = dist.locate_file(item).read_bytes()
                hashed = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                if not item.hash or item.hash.mode != "sha256" or hashed != item.hash.value:
                    raise ValueError(f"Installed distribution failed its RECORD check: {item}")
                # A stable timestamp keeps the runtime fingerprint the same across builds.
                entry = zipfile.ZipInfo(item.as_posix())
                runtime.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED)
            versions[name] = version
    archive = contents.getvalue()
    integrity = {"versions": versions, "sha256": hashlib.sha256(archive).hexdigest()}
    return archive, integrity


def build(output: Path, engine_repo: Path = ROOT) -> None:
    archive = subprocess.check_output(["git", "archive", ENGINE, *ASSETS], cwd=engine_repo)
    runtime, integrity = build_python_runtime()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar, tempfile.TemporaryDirectory() as tmp:
        engine = Path(tmp)
        manifest = []
        payloads = {}
        for item in sorted(tar, key=lambda item: item.name):
            if not item.isfile():
                continue
            if item.name == "requirements.txt":
                data = (ROOT / "workbuddy" / "requirements.txt").read_bytes()
            elif item.name in ENGINE_UPDATES:
                data = (ROOT / item.name).read_bytes()
            else:
                data = tar.extractfile(item).read()
            name = f"payload_{len(manifest):03d}{Path(item.name).suffix}"
            manifest.append({
                "path": item.name,
                "file": name,
                "sha256": hashlib.sha256(data).hexdigest(),
            })
            payloads[name] = data
            target = engine / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        subprocess.run([
            sys.executable, "-E", "-s", "-m", "trade_pipeline",
            "--input", "examples/sample_inquiry.xlsx", "--order", "DEMO-WORKBUDDY",
            "--buyer", "global_fasteners", "--quote-only", "--no-catalog-save",
        ], cwd=engine, check=True)
        sample = engine / "output/DEMO-WORKBUDDY/DEMO-WORKBUDDY_quotation.xlsx"
        workbook = load_workbook(sample)
        sheet = workbook["Quotation"]
        for row in sheet.iter_rows():
            if row[0].value == "QUOTATION":
                row[0].value = "DEMO QUOTATION / 示例报价单（虚构数据）"
        workbook.save(sample)
        workbook.close()

        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as package:
            package.write(ROOT / "workbuddy/SKILL.md", "SKILL.md")
            for name in ("prepare_engine.py", "business.py", "intake.py", "formal.py", "approval.py",
                         "documents.py", "actuals.py", "order_store.py", "workbook_output.py",
                         "python_runtime.py", "delivery.py"):
                package.write(ROOT / "workbuddy/scripts" / name, f"scripts/{name}")
            package.writestr("scripts/python_runtime.zip", runtime)
            package.writestr("scripts/python_runtime.json", json.dumps(integrity, indent=2))
            package.write(sample, "references/demo_quotation.xlsx")
            package.write(ROOT / "workbuddy/references/orders.md", "references/orders.md")
            package.writestr("scripts/engine_manifest.json", json.dumps(manifest, indent=2))
            for name, data in payloads.items():
                package.writestr(f"scripts/{name}", data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine-repo", type=Path, default=ROOT)
    args = parser.parse_args()
    build(args.output, args.engine_repo)

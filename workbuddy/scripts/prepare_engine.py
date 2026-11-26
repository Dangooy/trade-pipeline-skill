"""Reconstruct the published engine in a new, user-selected directory."""
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python prepare_engine.py /absolute/new-directory")
    dest = Path(sys.argv[1])
    if not dest.is_absolute() or not dest.parent.is_dir() or dest.exists() or dest.is_symlink():
        raise SystemExit("Target must be a new absolute path under an existing directory.")
    source = Path(__file__).resolve().parent
    entries = json.loads((source / "engine_manifest.json").read_text(encoding="utf-8"))
    seen = set()
    payloads = []
    for item in entries:
        rel = PurePosixPath(item["path"])
        name = item["file"]
        if (rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") for p in rel.parts)
                or "\\" in item["path"] or not name.startswith("payload_")
                or Path(name).name != name or item["path"] in seen):
            raise SystemExit("Invalid manifest path or duplicate entry.")
        seen.add(item["path"])
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise SystemExit("Missing or unsafe payload: " + name)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise SystemExit("Integrity check failed: " + name)
        payloads.append((rel, data))
    dest.mkdir()
    for rel, data in payloads:
        target = dest.joinpath(*rel.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as out:
            out.write(data)
    print("Engine prepared:", dest)


if __name__ == "__main__":
    main()

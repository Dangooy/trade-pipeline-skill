"""Publish immutable order revisions by writing one completion marker last."""
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

ATTEMPT = re.compile(r"(\d{12})-[a-f0-9]{32}")


class OrderStoreError(Exception):
    pass


def json_bytes(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, payload):
    """Only new files are written. Readers ignore an absent or incomplete marker."""
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


class OrderStore:
    def __init__(self, root, order):
        self.order = order
        self.root = root
        self.directory = root / ".workbuddy-orders" / order
        self.attempts = self.directory / "revisions"
        self.legacy_state = self.directory / "current.json"
        self.legacy_output = root / "output" / order
        for path in (self.attempts, self.legacy_state, self.legacy_output):
            if path.resolve() != path:
                raise OrderStoreError("订单目录经符号链接转向其它位置，请选择明确的工作目录。")

    def revisions(self):
        if not self.attempts.is_dir():
            return []
        return sorted((path for path in self.attempts.iterdir()
                       if ATTEMPT.fullmatch(path.name) and path.is_dir() and not path.is_symlink()),
                      reverse=True)

    def read(self):
        pending = 0
        for attempt in self.revisions():
            marker = attempt / "committed"
            if (
                marker.is_symlink() or not marker.is_file() or marker.stat().st_size != 65
                or not re.fullmatch(rb"[a-f0-9]{64}\n", marker.read_bytes())
            ):
                pending += 1
                continue
            identifier = marker.read_text(encoding="ascii").strip()
            state = attempt / "order.json"
            if state.is_symlink() or not state.is_file():
                raise OrderStoreError("当前订单的已提交记录缺失，请先检查该版本。")
            data = state.read_bytes()
            if identifier != digest(data):
                raise OrderStoreError("当前订单的已提交记录已变更，请先检查该版本。")
            return identifier, json.loads(data), pending
        if self.legacy_state.is_file():
            payload = self.legacy_state.read_bytes()
            saved = json.loads(payload)
            for kind, record in saved.get("artifacts", {}).items():
                record["path"] = str(self.legacy_output / f"{self.order}_{kind}.xlsx")
            return digest(payload), saved, pending
        return None, {}, pending

    def start(self):
        self.attempts.mkdir(parents=True, exist_ok=True)
        revisions = self.revisions()
        sequence = int(revisions[0].name.split("-", 1)[0]) + 1 if revisions else 1
        attempt = self.attempts / f"{sequence:012d}-{uuid4().hex}"
        attempt.mkdir()
        return attempt

    def check_file(self, kind, record):
        path = Path(record["path"])
        if (
            path.name != f"{self.order}_{kind}.xlsx" or path.resolve() != path
            or not (path.parent == self.legacy_output or path.parent.parent == self.attempts)
            or not path.is_file() or file_digest(path) != record["sha256"]
        ):
            raise OrderStoreError(f"当前 {kind.upper()} 的文件丢失或被手动修改，请核对原成果。")
        return path

    def commit(self, attempt, data):
        payload = json_bytes(data)
        write_new(attempt / "order.json", payload)
        write_new(attempt / "committed", (digest(payload) + "\n").encode("ascii"))

    def attestation(self, identifier):
        path = self.directory / "actual-verifications" / identifier
        if path.resolve() != path:
            raise OrderStoreError("实际资料核对路径经符号链接转向其它位置。")
        return path

    def manual_verified(self, identifier):
        if not identifier:
            return False
        path = self.attestation(identifier)
        expected = (identifier + "\n").encode("ascii")
        return any(
            not candidate.is_symlink() and candidate.is_file()
            and candidate.stat().st_size == len(expected) and candidate.read_bytes() == expected
            for candidate in path.glob("*.confirmed")
        )

    def confirm_manual(self, identifier):
        path = self.attestation(identifier)
        path.mkdir(parents=True, exist_ok=True)
        write_new(path / f"{uuid4().hex}.confirmed", (identifier + "\n").encode("ascii"))

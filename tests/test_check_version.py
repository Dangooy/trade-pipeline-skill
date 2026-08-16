"""B2:版本一致性检查脚本的测试。"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_version.py"


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)],
        capture_output=True, text=True,
    )


def test_passes_on_repo_itself():
    """仓库自身三处版本声明一致(发版不写日志/漏改 plugin.json 会被 CI 拦下)。"""
    r = _run(REPO_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


def _make_repo(tmp_path: Path, py: str, plugin: str, changelog_entry: str | None) -> Path:
    root = tmp_path / "repo"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "{py}"\n', encoding="utf-8")
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "x", "version": plugin}), encoding="utf-8")
    entry = f"## [{changelog_entry}]\n" if changelog_entry else ""
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n{entry}", encoding="utf-8")
    return root


def test_mismatched_versions_fail(tmp_path):
    root = _make_repo(tmp_path, "1.4.2", "1.4.1", "1.4.2")
    r = _run(root)
    assert r.returncode == 1
    assert "plugin.json" in r.stdout


def test_missing_changelog_section_fails(tmp_path):
    root = _make_repo(tmp_path, "1.4.2", "1.4.2", changelog_entry=None)
    r = _run(root)
    assert r.returncode == 1
    assert "CHANGELOG" in r.stdout


def test_consistent_repo_passes(tmp_path):
    root = _make_repo(tmp_path, "1.4.2", "1.4.2", "1.4.2")
    assert _run(root).returncode == 0


def test_missing_file_fails(tmp_path):
    root = _make_repo(tmp_path, "1.4.2", "1.4.2", "1.4.2")
    (root / ".claude-plugin" / "plugin.json").unlink()
    r = _run(root)
    assert r.returncode == 1

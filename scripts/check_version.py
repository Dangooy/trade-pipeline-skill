#!/usr/bin/env python3
"""版本一致性检查(B2)——CI 与本地均可运行。

校验三处版本声明互相一致:
  1. pyproject.toml 的 project.version
  2. .claude-plugin/plugin.json 的 version
  3. CHANGELOG.md 存在对应 "## [x.y.z]" 小节

任何一处不一致 exit 1 并指出哪个文件落后。防的是真实发生过的事:
plugin.json 曾落后 pyproject 两个版本无人发现(v1.4.1 收尾时才补上)。

用法: python3 scripts/check_version.py [repo_root]
"""
import json
import re
import sys
import tomllib
from pathlib import Path


def main(root: Path) -> int:
    problems = []

    pyproject = root / "pyproject.toml"
    plugin = root / ".claude-plugin" / "plugin.json"
    changelog = root / "CHANGELOG.md"

    for f in (pyproject, plugin, changelog):
        if not f.exists():
            print(f"FAIL: 缺少文件 {f}")
            return 1

    py_version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    plugin_version = json.loads(plugin.read_text(encoding="utf-8"))["version"]

    if py_version != plugin_version:
        problems.append(
            f"版本不一致: pyproject.toml={py_version} vs "
            f".claude-plugin/plugin.json={plugin_version}"
            f"(落后的文件需要同步更新)"
        )

    if not re.search(rf"^## \[{re.escape(py_version)}\]", changelog.read_text(encoding="utf-8"), re.M):
        problems.append(
            f"CHANGELOG.md 缺少 [## [{py_version}]] 小节(发版必须写更新日志)"
        )

    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        return 1

    print(f"OK: 版本一致 ({py_version}),CHANGELOG 已有对应小节")
    return 0


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    sys.exit(main(root))

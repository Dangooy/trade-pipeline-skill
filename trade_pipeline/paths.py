"""
trade_pipeline/paths.py — Frozen-aware path resolution

Provides path functions that work both in development (running from source)
and in PyInstaller-frozen .exe distributions.

In dev mode:
  - bundle_root() = project root (parent of trade_pipeline/)
  - user_data_root() = project root
  - output_root() = project_root/output

In frozen .exe mode:
  - bundle_root() = sys._MEIPASS (read-only, extracted at startup)
  - user_data_root() = %APPDATA%/TradePipeline (writable, persistent)
  - output_root() = ~/Documents/外贸单证助手 (visible to user)
"""
import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running from a PyInstaller-built .exe."""
    return getattr(sys, "frozen", False)


def bundle_root() -> Path:
    """Read-only resource root. In dev: project root. In exe: _MEIPASS."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def user_data_root() -> Path:
    """Writable persistent storage root."""
    if is_frozen():
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "TradePipeline"
    else:
        base = Path(__file__).resolve().parent.parent
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    """
    Path to the user's config.yaml.
    On first frozen run, copies the bundled default config to user_data_root.
    """
    if is_frozen():
        target = user_data_root() / "config" / "config.yaml"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            default = bundle_root() / "trade_pipeline" / "config" / "config.yaml"
            if default.exists():
                shutil.copy(default, target)
        return target
    return Path(__file__).resolve().parent / "config" / "config.yaml"


def output_root() -> Path:
    """Default output directory for generated documents."""
    if is_frozen():
        base = Path.home() / "Documents" / "外贸单证助手"
    else:
        base = Path(__file__).resolve().parent.parent / "output"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sample_inquiry_path() -> Path:
    """Path to the bundled sample inquiry Excel file."""
    return bundle_root() / "examples" / "sample_inquiry.xlsx"


def demo_config_path() -> Path:
    """Path to the bundled demo sellers/buyers config (示例卖家/买家数据).

    首启体验：模板 config.yaml 的 sellers/buyers 留空，示例实体放在这里，
    供 GUI「加载示例数据试用」按钮一键合并。frozen 模式下随包分发（见 .spec）。
    """
    return bundle_root() / "examples" / "demo_config.yaml"


def app_icon_path() -> Path:
    """Path to the application .ico for runtime window/taskbar icon.

    dev 模式在源码 `packaging/app.ico`；frozen 模式 spec 把它放到 bundle 根
    （datas `(.../app.ico, ".")`），故两模式路径不同。调用方应处理文件不存在的情况
    （图标缺失不应让 GUI 崩）。
    """
    if is_frozen():
        return bundle_root() / "app.ico"
    return bundle_root() / "packaging" / "app.ico"


def install_noop_stdout():
    """
    Install no-op stdout/stderr when running --windowed (no console).
    PyInstaller --windowed sets sys.stdout = None, which breaks print().
    """
    import io
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

"""
trade_pipeline/config_service.py — Config (yaml) CRUD service layer (v1.2.0)

纯 Python（无 PySide6 依赖）。负责 config.yaml 的安全读写：
  - 原子写（先写 .tmp，再 os.replace）
  - 写前备份（config.yaml → config.yaml.bak）
  - 字段隔离：CRUD 只动 sellers / buyers 段，其余段保持原样
  - ID 生成（复用 cli/init_wizard 的 _make_*_id 思路）

GUI 层（ConfigTab）通过 ConfigService 操作 yaml，单元测试可独立验证（无需 QApplication）。
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from trade_pipeline.paths import config_path as _default_config_path


# ── ID 生成（与 cli/init_wizard 保持一致语义） ──
_STOPWORDS = {"co", "ltd", "inc", "llc", "corp", "limited", "company", "ooo", "ооо", "gmbh"}


def make_entity_id(name_en: str, fallback: str = "entity") -> str:
    """从英文公司名生成 snake_case ID。去掉常见后缀词，取前两个有效词。"""
    if not name_en or not name_en.strip():
        return fallback
    words = re.split(r"[\s,\.\"']+", name_en.lower())
    key_words = [w for w in words if w and w not in _STOPWORDS]
    return "_".join(key_words[:2]) if key_words else fallback


def ensure_unique_id(base_id: str, existing_ids: set[str]) -> str:
    """若 base_id 已存在，追加 _2 / _3 ... 直到唯一。"""
    if base_id not in existing_ids:
        return base_id
    n = 2
    while f"{base_id}_{n}" in existing_ids:
        n += 1
    return f"{base_id}_{n}"


# ── 字段校验 ──
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_seller(data: dict) -> list[str]:
    """返回错误消息列表；空列表表示通过。"""
    errors = []
    if not (data.get("name_en") or "").strip():
        errors.append("公司名（英文）不能为空")
    email = (data.get("email") or "").strip()
    if email and not _EMAIL_RE.match(email):
        errors.append(f"邮箱格式不正确：{email}")
    bank = data.get("bank") or {}
    swift = (bank.get("swift") or "").strip()
    if swift and len(swift) not in (8, 11):
        errors.append(f"SWIFT 码应为 8 或 11 位，当前 {len(swift)} 位")
    return errors


def validate_buyer(data: dict) -> list[str]:
    errors = []
    if not (data.get("name_en") or "").strip():
        errors.append("公司名（英文）不能为空")
    email = (data.get("email") or "").strip()
    if email and not _EMAIL_RE.match(email):
        errors.append(f"邮箱格式不正确：{email}")
    return errors


# ── 默认数据模板（新增时填空白结构） ──
def empty_seller() -> dict:
    return {
        "name_cn": "",
        "name_en": "",
        "address": "",
        "address_lines": [],
        "contact": "",
        "tel": "",
        "email": "",
        "bank": {
            "name": "",
            "address": "",
            "swift": "",
            "account_no": "",
            "account_name": "",
        },
    }


def empty_buyer() -> dict:
    return {
        "name_en": "",
        "name_ru": None,
        "legal_names": [],
        "aliases": [],
        "address": "",
        "address_lines": [],
        "contact": "",
        "email": "",
        "inn": "",
    }


# ── ConfigService ──
class ConfigService:
    """
    封装 config.yaml 的读写。所有写操作经过 save() 走原子写 + 备份。

    用法：
        svc = ConfigService()           # 用 paths.config_path() 默认路径
        svc = ConfigService(custom)     # 测试时传临时路径
        svc.load()
        svc.add_seller("acme", {...})
        svc.save()                      # 触发备份 + 原子写
    """

    def __init__(self, path: Path | None = None):
        self.path: Path = Path(path) if path else _default_config_path()
        self._data: dict[str, Any] = {}

    # ── load / save ──
    def load(self) -> dict:
        if not self.path.exists():
            self._data = {}
            return self._data
        with open(self.path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        return self._data

    def save(self) -> None:
        """原子写 + 备份。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 备份现有 config
        if self.path.exists():
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            shutil.copy2(self.path, backup)
        # 写临时文件 + 原子改名
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.dump(
                self._data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        os.replace(tmp, self.path)

    # ── data accessors ──
    @property
    def data(self) -> dict:
        return self._data

    def sellers(self) -> dict:
        if not isinstance(self._data.get("sellers"), dict):
            self._data["sellers"] = {}
        return self._data["sellers"]

    def buyers(self) -> dict:
        if not isinstance(self._data.get("buyers"), dict):
            self._data["buyers"] = {}
        return self._data["buyers"]

    # ── seller CRUD ──
    def add_seller(self, seller_id: str, seller_data: dict) -> None:
        self.sellers()[seller_id] = seller_data

    def update_seller(self, seller_id: str, seller_data: dict) -> None:
        if seller_id not in self.sellers():
            raise KeyError(f"seller '{seller_id}' 不存在")
        self.sellers()[seller_id] = seller_data

    def delete_seller(self, seller_id: str) -> None:
        if seller_id in self.sellers():
            del self.sellers()[seller_id]

    # ── buyer CRUD ──
    def add_buyer(self, buyer_id: str, buyer_data: dict) -> None:
        self.buyers()[buyer_id] = buyer_data

    def update_buyer(self, buyer_id: str, buyer_data: dict) -> None:
        if buyer_id not in self.buyers():
            raise KeyError(f"buyer '{buyer_id}' 不存在")
        self.buyers()[buyer_id] = buyer_data

    def delete_buyer(self, buyer_id: str) -> None:
        if buyer_id in self.buyers():
            del self.buyers()[buyer_id]

    # ── 引用检查（Codex review P1#2） ──
    def find_seller_references(self, seller_id: str) -> list[str]:
        """返回所有 format_defaults 中引用此 seller_id 的 format 名称列表。"""
        refs = []
        fmt_defaults = self._data.get("format_defaults") or {}
        if not isinstance(fmt_defaults, dict):
            return refs
        for fmt_name, fmt_cfg in fmt_defaults.items():
            if isinstance(fmt_cfg, dict) and fmt_cfg.get("seller_id") == seller_id:
                refs.append(fmt_name)
        return refs

    def clear_format_references(self, fmt_names: list[str]) -> None:
        """删除 format_defaults 中指定的 format 段（用于联动清理孤儿）。"""
        fmt_defaults = self._data.get("format_defaults") or {}
        if not isinstance(fmt_defaults, dict):
            return
        for fmt in fmt_names:
            if fmt in fmt_defaults:
                del fmt_defaults[fmt]

    # ── ID helpers ──
    def make_unique_seller_id(self, name_en: str) -> str:
        base = make_entity_id(name_en, fallback="seller")
        return ensure_unique_id(base, set(self.sellers().keys()))

    def make_unique_buyer_id(self, name_en: str) -> str:
        base = make_entity_id(name_en, fallback="buyer")
        return ensure_unique_id(base, set(self.buyers().keys()))

    # ── demo 数据合并（首启体验） ──
    def merge_demo(self, demo_data: dict) -> dict:
        """增量合并示例 sellers/buyers 到当前 config。

        语义：对每个 demo 实体，只有当 ID 在当前 config 中**不存在**时才加入；
        已存在的同名实体**保持用户原值不被覆盖**（进 skipped 统计）。
        有任何新增时才落盘（走 save()：原子写 + 自动备份）。

        Args:
            demo_data: 形如 {"sellers": {...}, "buyers": {...}} 的 dict
                       （通常来自 demo_config.yaml）

        Returns:
            合并统计 dict：
              {"sellers_added": [id...], "buyers_added": [id...], "skipped": ["seller:id"...]}
        """
        stats: dict[str, list[str]] = {"sellers_added": [], "buyers_added": [], "skipped": []}

        for sid, sdata in (demo_data.get("sellers") or {}).items():
            if sid in self.sellers():
                stats["skipped"].append(f"seller:{sid}")
            else:
                self.add_seller(sid, sdata)
                stats["sellers_added"].append(sid)

        for bid, bdata in (demo_data.get("buyers") or {}).items():
            if bid in self.buyers():
                stats["skipped"].append(f"buyer:{bid}")
            else:
                self.add_buyer(bid, bdata)
                stats["buyers_added"].append(bid)

        if stats["sellers_added"] or stats["buyers_added"]:
            self.save()

        return stats

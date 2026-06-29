"""
understanding/cache.py — 分层 LLM 解析缓存（L1 extractor + L2 understanding）

L1: file_hash + extractor_version → ExtractedDocument（跳过文件解析）
L2: content_hash + prompt_version + model_name + schema_version → RFQCanonical（跳过 LLM 调用）

缓存失效条件：
  - 版本号变更（prompt_version / schema_version / extractor_version）
  - TTL 过期（默认 7 天）
  - 手动 invalidate
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta


DEFAULT_TTL_DAYS = 7


class BaseCache:
    """缓存基类，提供公共的 get/put/invalidate/stats 逻辑"""

    def __init__(self, cache_dir: str, ttl_days: int = DEFAULT_TTL_DAYS):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(days=ttl_days)

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _is_expired(self, data: dict) -> bool:
        """检查缓存是否过期"""
        parsed_at = data.get("_cache_meta", {}).get("parsed_at")
        if not parsed_at:
            return True
        try:
            ts = datetime.fromisoformat(parsed_at)
            return datetime.now() - ts > self.ttl
        except (ValueError, TypeError):
            return True

    def _read_cache_file(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache_file(self, path: Path, data: dict) -> Path:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    def invalidate(self, content_hash: str | None = None):
        """删除指定哈希的缓存，或 content_hash=None 时清除所有缓存"""
        if content_hash is None:
            count = 0
            for f in self.cache_dir.glob("*.json"):
                f.unlink()
                count += 1
            return count
        count = 0
        for f in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("_cache_meta", {}).get("content_hash") == content_hash:
                    f.unlink()
                    count += 1
            except (json.JSONDecodeError, OSError):
                pass
        return count

    def cleanup_expired(self) -> int:
        """清除所有过期缓存条目，返回删除数量"""
        removed = 0
        for f in self.cache_dir.glob("*.json"):
            data = self._read_cache_file(f)
            if data and self._is_expired(data):
                f.unlink()
                removed += 1
        return removed

    def stats(self) -> dict:
        """缓存统计信息"""
        files = list(self.cache_dir.glob("*.json"))
        expired = 0
        for f in files:
            data = self._read_cache_file(f)
            if data and self._is_expired(data):
                expired += 1
        return {
            "cache_dir": str(self.cache_dir),
            "entries": len(files),
            "expired": expired,
            "active": len(files) - expired,
            "ttl_days": self.ttl.days,
        }


class ExtractorCache(BaseCache):
    """
    L1 缓存：file_hash + extractor_version → ExtractedDocument

    跳过文件解析阶段。适用于同一文件多次运行。
    """

    def __init__(self, cache_dir: str, extractor_version: str,
                 ttl_days: int = DEFAULT_TTL_DAYS):
        super().__init__(cache_dir, ttl_days)
        self.extractor_version = extractor_version

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """计算文件内容的 SHA-256 哈希"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _cache_key(self, file_hash: str) -> str:
        raw = f"{file_hash}|{self.extractor_version}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, file_hash: str) -> dict | None:
        """命中返回 ExtractedDocument dict，未命中返回 None"""
        key = self._cache_key(file_hash)
        data = self._read_cache_file(self._cache_path(key))
        if data is None:
            return None
        if self._is_expired(data):
            return None
        meta = data.get("_cache_meta", {})
        if meta.get("extractor_version") != self.extractor_version:
            return None
        return data.get("document")

    def put(self, file_hash: str, doc_dict: dict) -> Path:
        """写入缓存"""
        key = self._cache_key(file_hash)
        data = {
            "document": doc_dict,
            "_cache_meta": {
                "content_hash": file_hash,
                "extractor_version": self.extractor_version,
                "parsed_at": datetime.now().isoformat(),
            },
        }
        return self._write_cache_file(self._cache_path(key), data)

    def stats(self) -> dict:
        s = super().stats()
        s["extractor_version"] = self.extractor_version
        s["layer"] = "L1"
        return s


class UnderstandingCache(BaseCache):
    """
    L2 缓存：content_hash + prompt_version + model_name + schema_version → RFQCanonical

    跳过 Claude API 调用。
    """

    def __init__(self, cache_dir: str, prompt_version: str, schema_version: str,
                 ttl_days: int = DEFAULT_TTL_DAYS):
        super().__init__(cache_dir, ttl_days)
        self.prompt_version = prompt_version
        self.schema_version = schema_version

    def _cache_key(self, content_hash: str, model_name: str) -> str:
        raw = f"{content_hash}|{self.prompt_version}|{model_name}|{self.schema_version}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, content_hash: str, model_name: str) -> dict | None:
        """命中返回 RFQ dict，未命中返回 None"""
        key = self._cache_key(content_hash, model_name)
        data = self._read_cache_file(self._cache_path(key))
        if data is None:
            return None
        if self._is_expired(data):
            return None
        meta = data.get("_cache_meta", {})
        if (meta.get("prompt_version") == self.prompt_version
                and meta.get("schema_version") == self.schema_version):
            return data.get("rfq")
        return None

    def put(self, content_hash: str, model_name: str, rfq_dict: dict) -> Path:
        """写入缓存"""
        key = self._cache_key(content_hash, model_name)
        data = {
            "rfq": rfq_dict,
            "_cache_meta": {
                "content_hash": content_hash,
                "prompt_version": self.prompt_version,
                "model_name": model_name,
                "schema_version": self.schema_version,
                "parsed_at": datetime.now().isoformat(),
            },
        }
        return self._write_cache_file(self._cache_path(key), data)

    def stats(self) -> dict:
        s = super().stats()
        s["prompt_version"] = self.prompt_version
        s["schema_version"] = self.schema_version
        s["layer"] = "L2"
        return s

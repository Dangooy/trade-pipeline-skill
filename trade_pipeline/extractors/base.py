"""
extractors/base.py — ExtractedDocument 及 ContentBlock 定义
"""
import hashlib
from dataclasses import dataclass, field


@dataclass
class ContentBlock:
    """文档中的一个内容块"""
    block_type: str         # "table" | "text" | "header" | "image_region"
    content: str            # 纯文本内容
    rows: list[list[str]] | None = None  # 表格型 block 的结构化行列
    source_page: int | None = None       # PDF 页码
    source_region: str | None = None     # 区域描述
    lang_hint: str | None = None         # "en" | "ru" | "zh"


@dataclass
class ExtractedDocument:
    """提取后的结构化文档"""
    content_text: str               # 全文本（tab分隔，兼容现有 parser）
    blocks: list[ContentBlock]      # 结构化内容块
    meta: dict                      # {"filename", "format", "pages", "sheets", ...}
    confidence: float               # 提取整体置信度 0.0-1.0
    source_path: str                # 原始文件路径
    extraction_method: str          # "openpyxl" | "pdfplumber" | "ocr" | ...
    warnings: list[str] = field(default_factory=list)
    content_hash: str = ""          # SHA-256(content_text)，用于 L2 缓存 key

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.content_text.encode("utf-8")
            ).hexdigest()

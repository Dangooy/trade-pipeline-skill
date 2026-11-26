"""Format links and pending fields from a committed document receipt."""
from pathlib import Path
from urllib.parse import quote

DOCUMENT_ORDER = ("pi", "ci", "pl")
DOCUMENT_LABELS = {"pi": "形式发票（PI）", "ci": "商业发票（CI）", "pl": "装箱单（PL）"}
STATUS_LABELS = {"draft": "内部工作稿", "formal": "正式单据"}


def markdown_target(path):
    target = "".join(
        quote(char, safe="") if char in "%#?<>\\[]" or ord(char) < 32 or ord(char) == 127
        else char for char in path.as_posix()
    )
    if any(char.isspace() or char in "()" for char in target):
        return f"<{target}>"
    return target


def delivery_markdown(result, action, requested=None, *, sync=False, include_pending=False):
    """Format only files owned by this successful request or recovery receipt."""
    if action not in ("draft", "formal", "status", "delivery") or result.get("status") != "committed":
        return ""
    receipt = result.get("receipt", {})
    scope = set(receipt.get("requested", ()))
    if sync:
        scope &= set(receipt.get("changed", ()))
    if action in ("status", "delivery") and requested:
        scope &= set(requested)
    files = result.get("documents", {})
    pending = result.get("draft_pending", {})
    lines = []
    notes = []
    for kind in DOCUMENT_ORDER:
        if kind not in scope or kind not in files:
            continue
        record = files[kind] if action in ("status", "delivery") else files[kind].get("file", {})
        title = STATUS_LABELS.get(record.get("status"))
        version = record.get("version")
        location = record.get("path")
        if not title or type(version) is not int or version < 1 or not isinstance(location, str):
            continue
        path = Path(location)
        if not path.is_absolute() or path.name != f"{result['order']}_{kind}.xlsx":
            continue
        changed = kind in receipt.get("changed", ())
        state = f"{title} · 本次更新" if changed and version > 1 else title
        lines.append(f"- [{DOCUMENT_LABELS[kind]}]({markdown_target(path)}) · {state}")
        if include_pending and record["status"] == "draft":
            note = pending.get(kind, {})
            fields = note.get("fields", ())
            if fields:
                names = "、".join(fields[:4]) + ("等" if len(fields) > 4 else "")
                notes.append(f"{DOCUMENT_LABELS[kind]}的{names}仍待确认。")
            if note.get("amount_pending"):
                notes.append(f"{DOCUMENT_LABELS[kind]}的金额待核算。")
    return "\n".join(lines) + ("\n\n" + "\n\n".join(notes) if notes else "")

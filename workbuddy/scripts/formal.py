"""Review one order and write only its approved, requested formal documents."""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from zipfile import BadZipFile

if __package__:
    from .approval import ApprovalUnavailable, approve_on_desktop
else:
    # The skill is launched with -I. Admit the skill's own module directory.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from approval import ApprovalUnavailable, approve_on_desktop

DOCUMENT_NAMES = {"pi": "形式发票", "pl": "装箱单", "ci": "商业发票"}
REQUIRED_TERMS = {"payment": "付款条款", "delivery": "交货条款"}
PLACEHOLDER = re.compile(
    r"待确认|待定|未确认|未定|待补|"
    r"\b(?:tbd|tbc|to be (?:confirmed|determined|agreed|provided))\b",
    re.IGNORECASE,
)
EMPTY_TERM = re.compile(r"(?:n/?a|none|unknown|pending|not applicable|not set)[.!]?", re.I)


class FormalError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def missing_terms(terms):
    missing = []
    for field, label in REQUIRED_TERMS.items():
        value = terms.get(field)
        if (not isinstance(value, str) or not any(c.isalnum() for c in value)
                or PLACEHOLDER.search(value)
                or EMPTY_TERM.fullmatch(value.rsplit(":", 1)[-1].strip())):
            missing.append(label)
    return missing


def blocking_checks(model, documents):
    from trade_pipeline.validation.engine import validate_order

    report = validate_order(model)
    # These warnings concern documents containing shipping or packing data.
    ignored_warnings = {"R004", "R007"} if documents == ("pi",) else set()
    return [
        issue.message for issue in report.errors + report.warnings
        if issue.rule_id not in ignored_warnings or issue in report.errors
    ]


def write_selected(model, config, staged_files):
    from trade_pipeline.validation.cross_doc import check_ci_pl_gross_weight, check_ci_pl_net_weight
    from trade_pipeline.writers.ci_writer import CIWriter
    from trade_pipeline.writers.pi_writer import PIWriter
    from trade_pipeline.writers.pl_writer import PLWriter
    from trade_pipeline.writers.pl_writer_lite import (
        _check_weight_completeness, apply_packing_summary_to_derived, compute_packing_summary,
    )

    if staged_files.keys() & {"ci", "pl"} and not _check_weight_completeness(model.items):
        _, summary = compute_packing_summary(model.items, config)
        apply_packing_summary_to_derived(model, summary)
    if "pi" in staged_files:
        PIWriter(model, config).write(str(staged_files["pi"]))
    pl = PLWriter(model, config).write(str(staged_files["pl"])) if "pl" in staged_files else None
    if pl is not None and not pl.get("success"):
        raise FormalError("装箱单生成失败，请核对装箱资料。")
    if pl is not None and pl.get("pl_path"):
        staged_files["pl"] = Path(pl["pl_path"])
    ci = CIWriter(model, config).write(str(staged_files["ci"])) if "ci" in staged_files else None
    for warning in (check_ci_pl_gross_weight(ci, pl), check_ci_pl_net_weight(ci, pl)):
        if warning:
            print(warning)


def publish_files(staged, destinations, commit_model):
    """Create new outputs exclusively and undo this attempt if the commit fails."""
    published = []
    try:
        for kind, path in destinations.items():
            os.link(staged[kind], path)
            published.append((staged[kind], path))
        commit_model()
    except (OSError, FormalError) as exc:
        for source, path in reversed(published):
            if path.exists() and path.samefile(source):
                path.unlink()
        if isinstance(exc, FormalError):
            raise
        raise FormalError("无法安全保存单据。请检查输出目录是否可写或已有同名文件。") from exc


def review_and_write(config_path, quotation_path, model_path, *, review=False, review_token=None,
                     documents=("pi",), output_dir=None):
    import yaml
    from openpyxl.utils.exceptions import InvalidFileException

    from trade_pipeline.models.order_model import OrderModel
    from trade_pipeline.pipeline.price_updater import PriceUpdateError, update_prices
    from trade_pipeline.understanding.assembler import EntityResolutionError, resolve_entities
    from trade_pipeline.writers.pl_writer_lite import PackingInfoMissingError

    documents = tuple(kind for kind in DOCUMENT_NAMES if kind in documents)
    if not documents:
        raise FormalError("请选择需要生成的单据。")
    output_dir = (output_dir or model_path.parent).resolve(strict=True)
    if not output_dir.is_dir():
        raise FormalError("请选择已有的可写输出目录。")
    paths = {"config": config_path, "quotation": quotation_path, "model": model_path}
    inputs = {key: path.read_bytes() for key, path in paths.items()}
    revisions = {key: digest(data) for key, data in inputs.items()}

    def require_current_inputs():
        if any(digest(path.read_bytes()) != revisions[key] for key, path in paths.items()):
            raise FormalError("本单资料已改动，请重新核对并确认。")

    try:
        config = yaml.safe_load(inputs["config"])
    except yaml.YAMLError as exc:
        raise FormalError("业务配置无法读取，请检查配置后重试。") from exc
    if not isinstance(config, dict):
        raise FormalError("业务配置无法读取，请检查配置后重试。")
    with tempfile.TemporaryDirectory() as scratch:
        snapshot_path = Path(scratch) / "model.json"
        snapshot_path.write_bytes(inputs["model"])
        model = OrderModel.from_json(snapshot_path)

    order_no = model.order.order_no
    if not order_no or not all(c.isalnum() or c in "-_" for c in order_no):
        raise FormalError("订单号只接受字母、数字、短横线和下划线。")
    try:
        resolve_entities(model, config)
    except EntityResolutionError as exc:
        raise FormalError("找不到本单适用的卖家，请核对订单与业务配置。") from exc
    terms = model.resolved.terms if isinstance(model.resolved.terms, dict) else {}
    model.resolved.terms = terms
    missing = missing_terms(terms)
    if missing and not review:
        raise FormalError("请补齐本单的" + "、".join(missing) + "，再核对正式出单。")
    try:
        prices = update_prices(model, io.BytesIO(inputs["quotation"]))
    except (PriceUpdateError, InvalidFileException, BadZipFile) as exc:
        raise FormalError("无法回填单价，请核对报价单和对应的订单模型。") from exc

    issues = prices["errors"] + prices["warnings"] + blocking_checks(model, documents)
    ready = not (missing or issues)
    binding = json.dumps({
        "paths": {key: str(path.resolve()) for key, path in paths.items()},
        "revisions": revisions,
        "documents": documents,
        "output": str(output_dir),
    }, sort_keys=True).encode()
    token = digest(binding)[:24]
    seller = model.resolved.seller.get("name_en") or model.resolved.seller.get("name_cn")
    buyer = model.resolved.buyer.get("name_en") or model.resolved.buyer.get("name_ru")
    if review:
        print(json.dumps({
            "状态": "可核对" if ready else "待确认",
            "订单号": order_no,
            "卖方": seller,
            "买方": buyer,
            "币种": model.order.currency,
            "计价单位": model.order.price_unit,
            "待出单据": [DOCUMENT_NAMES[kind] for kind in documents],
            "输出目录": str(output_dir),
            "条款模板": model.refs.terms_id,
            "本单条款": terms,
            "缺少条款": missing,
            "预检待处理": issues,
            "核对编号": token if ready else None,
        }, ensure_ascii=False, indent=2, default=str))
        return

    if not review_token:
        raise FormalError("请先查看本单核对结果，再请用户确认正式出单。")
    if review_token != token:
        raise FormalError("核对编号与当前订单、报价、业务配置或输出范围不匹配，请重新核对。")
    if issues:
        raise FormalError("正式出单还有待处理事项。\n" + "\n".join(issues))
    destinations = {kind: output_dir / f"{order_no}_{kind}.xlsx" for kind in documents}
    if any(path.exists() or path.is_symlink() for path in destinations.values()):
        raise FormalError("输出目录已有同名单据。请复用当前成果，或明确选择其他目录保存修订件。")
    backup_dir = model_path.parent / ".workbuddy-backups"
    if backup_dir.is_symlink() or (backup_dir.exists() and not backup_dir.is_dir()):
        raise FormalError("内部备份目录不可用，请检查订单目录。")

    message = (
        f"订单：{order_no}\n卖方：{seller}\n买方：{buyer}\n"
        f"币种和计价：{model.order.currency} / {model.order.price_unit}\n"
        f"付款：{terms['payment']}\n交货：{terms['delivery']}\n"
        f"将生成：{'、'.join(DOCUMENT_NAMES[kind] for kind in documents)}\n"
        f"核对编号：{token}\n\n请本人核对后点击确认。"
    )
    try:
        approved = approve_on_desktop(message)
    except ApprovalUnavailable as exc:
        raise FormalError(str(exc)) from exc
    if not approved:
        raise FormalError("桌面确认未通过，已保留当前成果。")

    require_current_inputs()
    with (tempfile.TemporaryDirectory(dir=output_dir) as report_stage,
          tempfile.TemporaryDirectory(dir=model_path.parent) as model_stage):
        staged = {kind: Path(report_stage) / path.name for kind, path in destinations.items()}
        replacement = Path(model_stage) / model_path.name
        model.to_json(replacement)
        os.chmod(replacement, model_path.stat().st_mode & 0o777)
        try:
            write_selected(model, config, staged)
        except PackingInfoMissingError as exc:
            raise FormalError(f"装箱资料待补充：{exc}") from exc
        if any(not file.is_file() or file.resolve().parent != Path(report_stage)
               for file in staged.values()):
            raise FormalError("有单据未成功生成，请核对输入后重试。")
        require_current_inputs()

        def commit_model():
            require_current_inputs()
            backup_dir.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=backup_dir, prefix=f"{order_no}-", suffix=".json.bak", delete=False,
            ) as backup:
                backup.write(inputs["model"])
            os.replace(replacement, model_path)

        publish_files(staged, destinations, commit_model)
    for file in destinations.values():
        print("已生成：" + str(file))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("action", choices=["terms-review", "writeback"])
    parser.add_argument("quotation", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("--review-token")
    parser.add_argument("--documents", nargs="+", choices=DOCUMENT_NAMES, default=["pi"])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.engine))
    try:
        review_and_write(
            args.engine / "trade_pipeline/config/config.yaml",
            args.quotation, args.model, review=args.action == "terms-review",
            review_token=args.review_token, documents=args.documents, output_dir=args.output_dir,
        )
    except FormalError as exc:
        parser.exit(1, str(exc) + "\n")
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, "无法核对或保存单据，请检查订单模型、报价单、业务配置和输出目录。\n")


if __name__ == "__main__":
    main()

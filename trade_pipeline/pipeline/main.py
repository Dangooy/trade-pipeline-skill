"""
pipeline/main.py — MVP 主编排脚本

链路：
  RFQ Excel → extract → parse → canonicalize → assemble → quote → PI → CI → PL

用法:
  python -m trade_pipeline --input <询价单.xlsx> --order <订单号> --buyer <buyer_id>
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Callable

import yaml

from trade_pipeline.extractors.excel_extractor import extract
from trade_pipeline.paths import config_path, output_root
from trade_pipeline.understanding.llm_parser import parse
from trade_pipeline.understanding.canonicalizer import canonicalize
from trade_pipeline.understanding.assembler import (
    EntityResolutionError, assemble, resolve_entities,
)
from trade_pipeline.understanding.buyer_matcher import BuyerMatchError
from trade_pipeline.writers.quote_writer import QuoteWriter
from trade_pipeline.writers.pi_writer import PIWriter
from trade_pipeline.writers.ci_writer import CIWriter
from trade_pipeline.writers.pl_writer import PLWriter
from trade_pipeline.pipeline.price_updater import update_prices
from trade_pipeline.validation.manual_completion import (
    ReviewItem, apply_review, generate_review,
)
from trade_pipeline.validation.engine import validate_order
from trade_pipeline.validation.reporters import to_markdown, to_text

ProgressFn = Callable[[str], None]


# ── Pre-generation Check ─────────────────────────────────────────


def _write_precheck_md(report, output_dir: str, order_no: str) -> str | None:
    """落盘检查报告 Markdown：{order}_precheck.md。失败返回 None（不抛）。"""
    md_path = str(Path(output_dir) / f"{order_no}_precheck.md")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(report))
    except OSError as e:
        print(f"  ⚠ 检查报告落盘失败: {e}")
        return None
    return md_path


def _run_precheck(model, output_dir: str, order_no: str) -> dict:
    """跑生成前检查：渲染中文报告 → 终端打印 → 落盘 Markdown。

    纯副作用（打印 + 写文件）+ 返回报告对象与产物路径，不做阻断决策。
    是否因 error 停止生成由调用方按 CLI 标志决定。

    返回:
        {"report": ValidationReport, "precheck_md": <path>}
    """
    report = validate_order(model)

    # 终端用纯文本（不依赖 Markdown 渲染器）
    print()
    print(to_text(report))

    # 同时落盘一份 Markdown，纳入 outputs，便于回溯
    md_path = _write_precheck_md(report, output_dir, order_no)

    return {"report": report, "precheck_md": md_path}


def load_config() -> dict:
    with open(config_path(), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _emit(progress: ProgressFn | None, msg: str):
    """Safe progress emit: falls back to print but never crashes on None stdout."""
    if progress is not None:
        progress(msg)
        return
    try:
        print(msg)
    except (ValueError, OSError):
        pass


# ── Step Functions ───────────────────────────────────────────────


def _extract_and_parse(input_path: str, use_llm: bool,
                       l1_cache_dir: str | None, l2_cache_dir: str | None,
                       output_dir: str, order_no: str,
                       total_steps: int) -> tuple[dict, dict]:
    """Steps 1-3: Extract → Parse → Canonicalize. Returns (rfq, partial_results)."""
    results = {"outputs": {}, "errors": []}

    print(f"[1/{total_steps}] 提取询价单: {input_path}")
    doc = extract(input_path, cache_dir=l1_cache_dir)
    fmt = doc.meta.get("format", "unknown")
    print(f"      格式: {fmt} | 行数: {doc.meta.get('rows', '?')} | Sheet: {doc.meta.get('sheet', '?')}")

    print(f"[2/{total_steps}] 解析询价单 ({'LLM' if use_llm else '规则'}模式)")
    rfq = parse(doc, use_llm=use_llm, cache_dir=l2_cache_dir)
    print(f"      产品: {len(rfq.get('items', []))} 条 | 货币: {rfq.get('currency', '?')}")

    rfq_path = str(Path(output_dir) / f"{order_no}_rfq.json")
    with open(rfq_path, "w", encoding="utf-8") as f:
        json.dump(rfq, f, ensure_ascii=False, indent=2)
    results["outputs"]["rfq_json"] = rfq_path

    print(f"[3/{total_steps}] 标准化字段")
    rfq = canonicalize(rfq)

    return rfq, results


def _assemble_model(rfq: dict, config: dict, order_no: str,
                    buyer_id: str | None, review_path: str | None,
                    interactive: bool, output_dir: str,
                    total_steps: int) -> tuple | dict:
    """Step 4: Assemble OrderModel. Returns model or error results dict."""
    print(f"[4/{total_steps}] 组装 OrderModel")

    confirm_buyer_id = None
    if review_path:
        try:
            from trade_pipeline.validation.manual_completion import ReviewFile
            review_data = ReviewFile.from_json(review_path)
            for item in review_data.items:
                if item.field_path == "refs.buyer_id" and item.resolved:
                    confirm_buyer_id = item.resolved_value
                    print(f"  → review.json buyer: {confirm_buyer_id}")
                    break
        except Exception:
            pass

    effective_buyer_id = confirm_buyer_id or buyer_id

    try:
        model = assemble(rfq, config, order_no, hint_buyer_id=effective_buyer_id)
        print(f"      buyer: {model.refs.buyer_id} | seller: {model.refs.seller_id}")
        print(f"      items: {len(model.items)} | format: {model.order.format}")
    except EntityResolutionError as e:
        # assemble() 在 format_defaults 缺 seller_id 时 fail-loud（v1.2.0）。
        # 与 resolve_entities 的同类错误一样返回结构化错误，不让异常冒泡成 traceback。
        print(f"  ✗ 实体解析失败: {e}")
        return {
            "outputs": {},
            "errors": [str(e)],
        }
    except BuyerMatchError as e:
        print(f"  ⚠ buyer 匹配失败: {e.extracted_name}")

        resolved = False
        if interactive:
            try:
                from trade_pipeline.cli.init_wizard import add_buyer_interactive
                new_id = add_buyer_interactive(config, e.extracted_name)
                if new_id:
                    model = assemble(rfq, config, order_no, hint_buyer_id=new_id)
                    print(f"      buyer: {model.refs.buyer_id} | seller: {model.refs.seller_id}")
                    print(f"      items: {len(model.items)} | format: {model.order.format}")
                    resolved = True
            except EOFError:
                pass

        if not resolved:
            review_items = [ReviewItem(
                field_path="refs.buyer_id",
                current_value=None,
                candidate_values=[c["id"] for c in e.candidates],
                confidence=0.0,
                source="matcher",
                reason=str(e),
                required_action="select",
            )]
            rp = generate_review(order_no, review_items, output_dir)
            print(f"  → review.json 已生成: {rp}")
            print(f"  → 编辑后重新运行: --confirm {rp}")
            return {"outputs": {"review_json": rp},
                    "errors": [f"需要人工确认 buyer: {rp}"]}

    if review_path:
        print(f"  → 应用 review: {review_path}")
        r = apply_review(model, review_path)
        print(f"     applied={r['applied']}, pending={r['still_pending']}")

    # Codex review 二轮 P1#2：seller 在 config 中不存在 → 硬阻断
    try:
        model = resolve_entities(model, config)
    except EntityResolutionError as e:
        print(f"  ✗ 实体解析失败: {e}")
        return {
            "outputs": {},
            "errors": [str(e)],
        }

    model_path = str(Path(output_dir) / f"{order_no}_model.json")
    model.to_json(model_path)
    print(f"      OrderModel → {model_path}")

    return model, model_path


def _write_quotation(model, config: dict, output_dir: str, order_no: str,
                     total_steps: int) -> tuple[str, dict]:
    """Step 5: Generate quotation with UUID anchoring."""
    print(f"[5/{total_steps}] 生成报价单 (含 uuid 列)")
    quote_path = str(Path(output_dir) / f"{order_no}_quotation.xlsx")
    writer = QuoteWriter(model, config)
    quote_info = writer.write(quote_path)
    print(f"      → {quote_path}")
    print(f"      uuid列: {quote_info['uuid_col_letter']} (隐藏) | 数据起始行: {quote_info['data_start_row']}")
    return quote_path, quote_info


def _write_trade_docs(model, config: dict, output_dir: str, order_no: str,
                      total_steps: int, packing_review=None) -> dict:
    """Steps 6-8: PI + CI + PL generation.

    v1.1.0: 接受可选 packing_review（PackingReview 对象）传给 PLWriter。
    PackingInfoMissingError 时自动生成 review.json，供用户填写 + --confirm-packing 重跑。
    """
    results = {"outputs": {}, "warnings": []}

    print(f"[6/{total_steps}] 生成 PI 形式发票")
    pi_path = str(Path(output_dir) / f"{order_no}_pi.xlsx")
    try:
        pi_writer = PIWriter(model, config)
        pi_info = pi_writer.write(pi_path)
        results["outputs"]["pi_xlsx"] = pi_path
        print(f"      → {pi_path}")
        print(f"      PI No.: {pi_info['pi_number']} | 产品: {pi_info['items']} 条")
    except Exception as e:
        msg = f"PI 生成失败: {type(e).__name__}: {e}"
        results["warnings"].append(msg)
        print(f"      ⚠ {msg}")

    print(f"[7/{total_steps}] 生成 CI 商业发票")
    ci_path = str(Path(output_dir) / f"{order_no}_ci.xlsx")
    try:
        ci_writer = CIWriter(model, config)
        ci_info = ci_writer.write(ci_path)
        results["outputs"]["ci_xlsx"] = ci_path
        print(f"      → {ci_path}")
        print(f"      CI No.: {ci_info['ci_number']} | 金额: {model.order.currency} {ci_info['total_amount']:,.2f}")
    except Exception as e:
        msg = f"CI 生成失败: {type(e).__name__}: {e}"
        results["warnings"].append(msg)
        print(f"      ⚠ {msg}")

    print(f"[8/{total_steps}] 生成 PL 装箱单")
    pl_writer = PLWriter(model, config)
    pl_kwargs = {}
    if packing_review is not None:
        pl_kwargs["packing_review"] = packing_review
    try:
        pl_result = pl_writer.write(
            str(Path(output_dir) / f"{order_no}_pl.xlsx"),
            **pl_kwargs,
        )
        if pl_result.get("success"):
            results["outputs"]["pl_xlsx"] = pl_result.get("pl_path", "")
            print(f"      → {pl_result.get('pl_path', '')}")
        else:
            err = pl_result.get("error") or pl_result.get("stderr", "未知错误")
            results["warnings"].append(f"PL 生成失败: {err}")
            print(f"      ⚠ PL 生成失败: {err}")
    except Exception as e:
        from trade_pipeline.writers.pl_writer_lite import PackingInfoMissingError
        if isinstance(e, PackingInfoMissingError):
            # v1.1.0: 自动生成 packing_review.json 引导用户补全
            from trade_pipeline.validation.packing_review import (
                build_review_from_missing, review_path_for,
            )
            review = build_review_from_missing(model, e.missing_items, config)
            review_p = review_path_for(output_dir, order_no)
            review.to_json(str(review_p))
            results["outputs"]["packing_review_json"] = str(review_p)
            auto_filled = sum(1 for it in review.items if it.resolved)
            still_pending = review.unresolved_count()
            msg = (
                f"PL 装箱单未生成：{still_pending} 项需补充包装信息。\n"
                f"      → 已自动生成 review 文件: {review_p}\n"
            )
            if auto_filled:
                msg += f"      → 其中 {auto_filled} 项已从 product_catalog 自动填充\n"
            msg += (
                f"      → 编辑后重新运行: --confirm-packing {review_p}"
            )
            results["warnings"].append(msg)
            print(f"      ⚠ {msg}")
        else:
            msg = f"PL 生成异常: {type(e).__name__}: {e}"
            results["warnings"].append(msg)
            print(f"      ⚠ {msg}")

    return results


# ── Main Orchestrator ────────────────────────────────────────────


def run(
    input_path: str,
    order_no: str,
    buyer_id: str | None = None,
    output_dir: str | None = None,
    use_llm: bool = False,
    review_path: str | None = None,
    interactive: bool = False,
    quote_only: bool = False,
    packing_review_path: str | None = None,
    save_packing_to_catalog: bool = True,
    precheck: bool = True,
    skip_warnings: bool = False,
    check_only: bool = False,
) -> dict:
    """
    执行完整 MVP 链路。

    生成前检查（precheck）：
      - precheck=True（默认）在组装出 OrderModel 后运行 validate_order，
        打印中文报告并落盘 {order}_precheck.md。
      - 主流程的报价单刚组装时单价/重量必然为空（这是"先出报价单"的
        正常状态），因此本路径**不因 error 阻断**——只报告。真正的
        error 阻断在 run_price_update()（报价回写后准备出正式单据时）。
      - check_only=True：跑完检查即停，不写任何单据（报价单/PI/CI/PL），
        但 rfq.json / model.json 等检查所需的中间产物仍会生成。
      - precheck=False：完全跳过检查（兼容旧流程）。
      - skip_warnings：本路径不阻断，故仅影响 check_only 的退出说明措辞。

    返回:
        {"success": bool, "outputs": {...}, "errors": [...]}
    """
    config = load_config()
    cache_cfg = config.get("cache", {})
    cache_enabled = cache_cfg.get("enabled", True)

    if output_dir is None:
        output_dir = str(output_root() / order_no)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    l1_cache_dir = str(Path(output_dir) / ".cache" / "l1") if cache_enabled else None
    l2_cache_dir = str(Path(output_dir) / ".cache" / "l2") if cache_enabled else None

    results = {"success": False, "outputs": {}, "errors": [], "warnings": []}
    total_steps = 5 if quote_only else 8

    # Steps 1-3: Extract → Parse → Canonicalize
    try:
        rfq, extract_results = _extract_and_parse(
            input_path, use_llm, l1_cache_dir, l2_cache_dir,
            output_dir, order_no, total_steps)
        results["outputs"].update(extract_results["outputs"])
    except Exception as e:
        results["errors"].append(str(e))
        print(f"  ✗ {e}")
        return results

    # Step 4: Assemble OrderModel
    assemble_result = _assemble_model(
        rfq, config, order_no, buyer_id, review_path,
        interactive, output_dir, total_steps)

    if isinstance(assemble_result, dict):
        results["outputs"].update(assemble_result["outputs"])
        results["errors"].extend(assemble_result["errors"])
        return results

    model, model_path = assemble_result
    results["outputs"]["model_json"] = model_path

    # 生成前检查（早期）：打印报告 + 落盘 precheck.md + check_only 短路。
    # error 的阻断判定推迟到 packing review 应用之后（见下方"晚期阻断判定"），
    # 因为补录重量可能消掉 R007 等 error，必须检查"最终要写单据的 model"。
    if precheck or check_only:
        pc = _run_precheck(model, output_dir, order_no)
        if pc["precheck_md"]:
            results["outputs"]["precheck_md"] = pc["precheck_md"]
        report = pc["report"]
        # check_only：只出检查报告，不写任何单据。
        # error 始终判为失败（不被 skip_warnings 放过）。
        if check_only:
            results["success"] = not report.has_errors
            print()
            if report.has_errors:
                print(f"⚠ --check-only：发现 {len(report.errors)} 条错误，未生成任何单据。")
            else:
                print("✓ --check-only：检查完成，未生成任何单据。")
            return results

    # Step 5: Quotation（始终生成——报价单刚组装时缺价是正常状态）
    quote_path, _ = _write_quotation(model, config, output_dir, order_no, total_steps)
    results["outputs"]["quotation_xlsx"] = quote_path

    # v1.1.0: 如果提供了 packing_review.json，加载并应用到 model
    packing_review_obj = None
    if packing_review_path and not quote_only:
        try:
            from trade_pipeline.validation.packing_review import (
                PackingReview, ReviewMismatchError, ReviewSchemaError,
                apply_to_model,
            )
            # 校验 order_no 必须匹配，避免错传别的订单的 review
            packing_review_obj = PackingReview.from_json(
                packing_review_path, expected_order_no=order_no,
            )
            apply_res = apply_to_model(
                model, packing_review_obj, config=config,
                save_new_to_catalog=save_packing_to_catalog,
                config_path=config_path(),
            )
            print(f"  → 应用 packing review: {packing_review_path}")
            mb = apply_res.get("matched_by", {})
            print(f"     applied={apply_res['applied']}, "
                  f"still_pending={apply_res['still_pending']}, "
                  f"saved_to_catalog={apply_res['saved_to_catalog']}")
            print(f"     matched_by: uuid={mb.get('uuid', 0)}, "
                  f"desc_qty={mb.get('desc_qty', 0)}, "
                  f"missed={mb.get('missed', 0)}")
            if mb.get("missed", 0) > 0:
                results["warnings"].append(
                    f"packing review 有 {mb['missed']} 项无法匹配到 model "
                    "（description/quantity 都不一致），可能 review.json 已过期"
                )
            overwritten = apply_res.get("overwritten", 0)
            if overwritten > 0:
                results["warnings"].append(
                    f"packing review 覆盖了 {overwritten} 项已有 weight_kg "
                    "（与原值差异 >1%），请确认是否预期"
                )
                print(f"     ⚠ 覆盖了 {overwritten} 项原有 weight_kg")
            # 重新保存 model.json（含新填的字段）
            model.to_json(model_path)
        except (ReviewMismatchError, ReviewSchemaError) as e:
            # 这两种错误是用户传错文件，直接报错不继续
            results["errors"].append(f"packing review 校验失败: {e}")
            print(f"  ✗ packing review 校验失败: {e}")
            return results
        except Exception as e:
            results["warnings"].append(f"加载 packing review 失败: {e}")
            print(f"  ⚠ 加载 packing review 失败: {e}")

    # 晚期阻断判定：对补录后的最终 model 重新校验（用纯函数，避免报告二次打印）。
    # 有 error → 报价单照出，但 PI/CI/PL 停止生成。warning 在主流程不阻断
    # （主流程是宽松路径，阻断职责在 run_price_update）。quote_only 无正式单据可拦。
    block_trade_docs = False
    if precheck and not quote_only:
        final_report = validate_order(model)
        # 落盘报告必须反映补录后的最终 model（覆盖早期版本；不二次打印全文）
        final_md = _write_precheck_md(final_report, output_dir, order_no)
        if final_md:
            results["outputs"]["precheck_md"] = final_md
        if final_report.has_errors:
            block_trade_docs = True
            for e in final_report.errors:
                results["errors"].append(f"precheck: [{e.rule_id}] {e.message}")
            print()
            print(f"  ✗ 检查发现 {len(final_report.errors)} 条错误，"
                  f"报价单已生成，PI/CI/PL 已跳过。")
            print("    请填价回写（--price-update）或补齐信息后重试，"
                  "或加 --no-precheck 跳过检查。")

    # Steps 6-8: PI + CI + PL（quote_only 或 error 阻断时跳过）
    if not quote_only and not block_trade_docs:
        trade_results = _write_trade_docs(
            model, config, output_dir, order_no, total_steps,
            packing_review=packing_review_obj,
        )
        results["outputs"].update(trade_results["outputs"])
        results["warnings"].extend(trade_results["warnings"])

    # Done
    results["success"] = not block_trade_docs
    print()
    print("=" * 60)
    if block_trade_docs:
        print(f"⚠ 报价单已生成，但 PI/CI/PL 因检查错误被跳过！订单: {order_no}")
    elif quote_only:
        print(f"✅ 报价单已生成！订单: {order_no}")
    else:
        print(f"✅ 全套单据已生成！订单: {order_no}")
    print(f"   输出目录: {output_dir}")
    for k, v in results["outputs"].items():
        print(f"   {k}: {Path(v).name}")
    print("=" * 60)

    print()
    print("下一步：")
    print(f"  1. 打开报价单填写单价: {quote_path}")
    print("  2. 确认后运行价格回写 + 生成正式单据:")
    print("     python -m trade_pipeline \\")
    print(f"       --price-update {quote_path} \\")
    print(f"       --model {model_path}")

    return results


# ── Price Update ─────────────────────────────────────────────────


def run_price_update(
    quotation_path: str,
    model_path: str,
    packing_review_path: str | None = None,
    precheck: bool = True,
    skip_warnings: bool = False,
    check_only: bool = False,
) -> dict:
    """单独运行价格回写：读取价格 → 回写 OrderModel → 重新生成 PI/CI/PL。

    v1.1.0 (C15 fix): 接受 packing_review_path 参数；PI/CI/PL 写入用 try/except
    避免单步失败让前面生成的输出全丢。

    生成前检查（precheck）——这是会阻断的路径：
      - 价格回写后 model 已带价，是"准备出正式 PI/CI"的真实时刻。
      - precheck=True（默认）在 resolve_entities 后运行检查并落盘报告。
        若有 error 且未加 skip_warnings → 停止，不写 PI/CI/PL。
      - skip_warnings：有 warning 不阻断（error 仍阻断）。
      - check_only=True：只出检查报告，不重新生成任何单据。
      - precheck=False：跳过检查（兼容旧流程）。
    """
    from trade_pipeline.models.order_model import OrderModel

    print(f"[价格回写] 报价单: {quotation_path}")
    print(f"           模型: {model_path}")
    if packing_review_path:
        print(f"           装箱信息: {packing_review_path}")

    model = OrderModel.from_json(model_path)
    result = update_prices(model, quotation_path)

    print(f"  updated: {result['updated']}")
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  ⚠ {w}")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ✗ {e}")

    if result["errors"]:
        print(f"\n  ✗ 价格回写有 {len(result['errors'])} 个错误，停止。请修正后重试。")
        return result

    model.to_json(model_path)
    print(f"  → 模型已更新: {model_path}")

    config = load_config()
    # Codex review 二轮 P1#2：price-update 路径也走 seller 硬校验
    try:
        model = resolve_entities(model, config)
    except EntityResolutionError as e:
        print(f"  ✗ 实体解析失败: {e}")
        result["errors"].append(str(e))
        return result

    output_dir = str(Path(model_path).parent)

    # v1.1.0: 如果提供了 packing_review，先加载并应用（必须在 precheck 之前）。
    # 原因：packing review 用来补录重量/装箱信息，apply_to_model 会回填 weight_kg；
    # 若先 precheck，吐价订单（R007 缺重量=error）会在补录前被误拦。检查必须看
    # "补录后、最终准备写单据的 model"。
    packing_review_obj = None
    if packing_review_path:
        try:
            from trade_pipeline.validation.packing_review import (
                PackingReview, ReviewMismatchError, ReviewSchemaError,
                apply_to_model,
            )
            packing_review_obj = PackingReview.from_json(
                packing_review_path, expected_order_no=model.order.order_no,
            )
            apply_res = apply_to_model(
                model, packing_review_obj, config=config,
                save_new_to_catalog=True, config_path=config_path(),
            )
            print(f"  → 应用 packing review: applied={apply_res['applied']}, "
                  f"still_pending={apply_res['still_pending']}")
            model.to_json(model_path)
        except (ReviewMismatchError, ReviewSchemaError) as e:
            print(f"  ✗ packing review 校验失败: {e}")
            result["errors"].append(str(e))
            return result
        except Exception as e:
            print(f"  ⚠ 加载 packing review 失败: {e}")

    # 生成前检查（阻断路径）：model 此时已带价且已补录装箱信息，是出正式单据前的检查时刻
    if precheck or check_only:
        pc = _run_precheck(model, output_dir, model.order.order_no)
        report = pc["report"]
        if pc["precheck_md"]:
            result.setdefault("outputs", {})["precheck_md"] = pc["precheck_md"]
        # 结构化检查结果（任务卡 #3.5）：纯加法，供 GUI 精确区分 error/warning 阻断，
        # 不再靠 errors 文案关键词。放 dict（非 ValidationReport 本体）→ 可序列化、解耦。
        # 在所有后续 return 分支之前塞入，确保 check_only / error 阻断 / warning 阻断
        # 三条 return 路径都带上它。
        result["precheck_report"] = {
            "has_errors": report.has_errors,
            "has_warnings": bool(report.warnings),
            "errors": [{"rule_id": r.rule_id, "message": r.message} for r in report.errors],
            "warnings": [{"rule_id": r.rule_id, "message": r.message} for r in report.warnings],
        }
        if check_only:
            # check_only 也必须尊重检查结果：有 error → errors 非空 → CLI exit 1
            print()
            if report.has_errors:
                print(f"✗ --check-only：检查发现 {len(report.errors)} 条错误，"
                      f"未重新生成任何单据。")
                result["errors"].append(
                    f"precheck: {len(report.errors)} 条错误（--check-only）"
                )
            else:
                print("✓ --check-only：检查完成，未重新生成任何单据。")
            return result
        # error 始终阻断；warning 默认阻断，--skip-warnings 放行；info 从不阻断
        if report.has_errors:
            print()
            print(f"  ✗ 生成前检查发现 {len(report.errors)} 条错误，停止。"
                  f"请处理后重试，或加 --no-precheck 跳过检查。")
            result["errors"].append(
                f"precheck: {len(report.errors)} 条错误阻断了单据生成"
            )
            return result
        if report.warnings and not skip_warnings:
            print()
            print(f"  ✗ 生成前检查发现 {len(report.warnings)} 条警告，停止。"
                  f"确认无误请加 --skip-warnings 继续，或加 --no-precheck 跳过检查。")
            result["errors"].append(
                f"precheck: {len(report.warnings)} 条警告阻断了单据生成"
                f"（可用 --skip-warnings 放行）"
            )
            return result

    # PI
    pi_path = str(Path(output_dir) / f"{model.order.order_no}_pi.xlsx")
    try:
        pi_writer = PIWriter(model, config)
        pi_info = pi_writer.write(pi_path)
        print(f"  → PI 已重新生成: {pi_path}")
        print(f"     PI No.: {pi_info['pi_number']} | 产品: {pi_info['items']} 条")
        result["pi_path"] = pi_path
    except Exception as e:
        print(f"  ⚠ PI 重新生成失败: {type(e).__name__}: {e}")
        result.setdefault("warnings", []).append(f"PI: {e}")

    # CI
    ci_path = str(Path(output_dir) / f"{model.order.order_no}_ci.xlsx")
    try:
        ci_writer = CIWriter(model, config)
        ci_info = ci_writer.write(ci_path)
        print(f"  → CI 已重新生成: {ci_path}")
        print(f"     CI No.: {ci_info['ci_number']} | 金额: {model.order.currency} {ci_info['total_amount']:,.2f}")
        result["ci_path"] = ci_path
    except Exception as e:
        print(f"  ⚠ CI 重新生成失败: {type(e).__name__}: {e}")
        result.setdefault("warnings", []).append(f"CI: {e}")

    # PL
    pl_path = str(Path(output_dir) / f"{model.order.order_no}_pl.xlsx")
    try:
        pl_writer = PLWriter(model, config)
        pl_kwargs = {}
        if packing_review_obj is not None:
            pl_kwargs["packing_review"] = packing_review_obj
        pl_result = pl_writer.write(pl_path, **pl_kwargs)
        if pl_result.get("success"):
            print(f"  → PL 已生成: {pl_result.get('pl_path', pl_path)}")
            result["pl_path"] = pl_result.get("pl_path", pl_path)
        else:
            err = pl_result.get("error") or pl_result.get("stderr", "未知错误")
            print(f"  ⚠ PL 生成失败: {err}")
    except Exception as e:
        from trade_pipeline.writers.pl_writer_lite import PackingInfoMissingError
        if isinstance(e, PackingInfoMissingError):
            print(f"  ⚠ PL 缺装箱信息：{e}")
            print("     → 请先用主流程 --confirm-packing 生成 PL，"
                  "或在 price-update 时附加 --confirm-packing 参数")
            # 任务卡 #3.5：与 run() 路径对齐——产出结构化 review.json，
            # 让 GUI 能弹 Gateway 补录后带 --confirm-packing 重跑（不再只靠提示降级）。
            # 仅当本次未提供 packing_review_path 时生成（已带 review 仍失败不再重复生成）。
            if not packing_review_path:
                try:
                    from trade_pipeline.validation.packing_review import (
                        build_review_from_missing, review_path_for,
                    )
                    review = build_review_from_missing(model, e.missing_items, config)
                    review_p = review_path_for(output_dir, model.order.order_no)
                    review.to_json(str(review_p))
                    result.setdefault("outputs", {})["packing_review_json"] = str(review_p)
                    print(f"     → 已生成装箱信息待补文件: {review_p}")
                except Exception as gen_e:
                    print(f"     ⚠ 生成装箱 review 失败: {gen_e}")
        else:
            print(f"  ⚠ PL 异常: {type(e).__name__}: {e}")
        result.setdefault("warnings", []).append(f"PL: {e}")

    return result


# ── CLI Entry Point ──────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="trade_pipeline MVP")
    parser.add_argument("--input", help="询价单 Excel 路径")
    parser.add_argument("--order", help="订单号")
    parser.add_argument("--buyer", help="buyer_id (跳过匹配)", default=None)
    parser.add_argument("--output-dir", help="输出目录", default=None)
    parser.add_argument("--use-llm", action="store_true", help="使用 Claude API 解析")
    parser.add_argument("--confirm", help="review.json 路径", default=None)
    parser.add_argument("--interactive", action="store_true",
                        help="buyer 匹配失败时交互式创建新客户")
    parser.add_argument("--quote-only", action="store_true",
                        help="只生成报价单，不生成 PI/CI/PL")
    parser.add_argument("--price-update", help="填好单价的报价单路径", default=None)
    parser.add_argument("--model", help="OrderModel JSON 路径 (配合 --price-update)", default=None)
    parser.add_argument("--confirm-packing",
                        help="装箱信息 review.json 路径（PL 缺重量时自动生成）",
                        default=None)
    parser.add_argument("--no-catalog-save", action="store_true",
                        help="禁用 packing 信息自动写回 product_catalog（默认会写）")
    parser.add_argument("--check-only", action="store_true",
                        help="只生成检查报告，不生成 PI/CI/PL（也不写报价单）")
    parser.add_argument("--skip-warnings", action="store_true",
                        help="有 warning 时不阻断，直接继续（error 仍阻断）")
    parser.add_argument("--no-precheck", action="store_true",
                        help="完全跳过生成前检查（兼容旧流程）")
    args = parser.parse_args()

    if args.price_update:
        if not args.model:
            print("错误: --price-update 需要同时提供 --model")
            sys.exit(1)
        result = run_price_update(
            args.price_update, args.model,
            packing_review_path=args.confirm_packing,
            precheck=not args.no_precheck,
            skip_warnings=args.skip_warnings,
            check_only=args.check_only,
        )
        if result.get("errors"):
            sys.exit(1)
        return

    if not args.input or not args.order:
        parser.print_help()
        sys.exit(1)

    result = run(
        input_path=args.input,
        order_no=args.order,
        buyer_id=args.buyer,
        output_dir=args.output_dir,
        use_llm=args.use_llm,
        review_path=args.confirm,
        interactive=args.interactive,
        quote_only=args.quote_only,
        packing_review_path=args.confirm_packing,
        save_packing_to_catalog=not args.no_catalog_save,
        precheck=not args.no_precheck,
        skip_warnings=args.skip_warnings,
        check_only=args.check_only,
    )

    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()

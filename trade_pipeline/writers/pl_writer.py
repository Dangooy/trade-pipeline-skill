"""
writers/pl_writer.py — Unified PL Writer interface

Two modes:
  1. Full mode: delegates to external pl-gen engine via legacy/pl_gen_bridge.py
  2. Lite mode: uses built-in PLWriterLite when pl-gen is not available

Pipeline interface stays consistent regardless of which mode is active.
"""
from pathlib import Path

from trade_pipeline.writers.base_writer import BaseWriter
from trade_pipeline.adapters.pl_adapter import resolve_pl_config_name, PLConfigError
from trade_pipeline.legacy.pl_gen_bridge import bridge, PL_GEN_DIR


class PLWriter(BaseWriter):
    """
    Unified PL Writer interface.

    Automatically falls back to PLWriterLite when the external pl-gen
    engine is not available.
    """

    # kwargs that are only meaningful for PLWriterLite (Gateway mode).
    # Full-mode (pl-gen) ignores them, so we warn explicitly.
    _LITE_ONLY_KWARGS = ("packing_review", "allow_missing_weight")

    def write(self, output_path: str, document_profile: str = "default", **kwargs) -> dict:
        buyer_id = self.model.refs.buyer_id

        if not PL_GEN_DIR.exists():
            from trade_pipeline.writers.pl_writer_lite import PLWriterLite
            lite = PLWriterLite(self.model, self.config)
            # Forward Gateway-related kwargs (packing_review, allow_missing_weight)
            result = lite.write(output_path, **kwargs)
            result["mode"] = "lite"
            return result

        # Full mode: pl-gen subprocess cannot accept lite-only kwargs.
        # Explicitly warn rather than silently dropping them.
        ignored = [k for k in self._LITE_ONLY_KWARGS if k in kwargs]
        warnings_list = []
        if ignored:
            warnings_list.append(
                f"full mode (pl-gen) ignored lite-only kwargs: {ignored}. "
                "Use lite mode or compose packing config via pl-gen template."
            )

        try:
            pl_config_name = resolve_pl_config_name(
                self.config, buyer_id, document_profile
            )
        except PLConfigError as e:
            return {"success": False, "error": str(e)}

        output_dir = str(Path(output_path).parent)
        result = bridge(
            self.model,
            output_dir,
            pl_config_name=pl_config_name,
        )
        result["pl_config"] = pl_config_name
        result["document_profile"] = document_profile
        result["mode"] = "full"
        if warnings_list:
            result.setdefault("warnings", []).extend(warnings_list)
        return result

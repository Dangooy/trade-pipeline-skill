"""
adapters/pl_adapter.py — PL 配置双维度映射

buyer_id + document_profile → pl_config 名称
禁止硬编码 "standard"。

config.yaml 中 pl_profiles 的结构：

  pl_profiles:
    default:                      # 全局 fallback
      pl_config: "standard"
      packing_profile: "standard_25kg"
    buyer_a:                      # buyer 专属
      default:                    # 默认 profile
        pl_config: "standard"
      bulk:                       # 散装 profile
        pl_config: "standard-bulk"
    buyer_b:
      default:
        pl_config: "custom_layout"
"""


class PLConfigError(Exception):
    """PL 配置查找失败"""
    pass


def resolve_pl_config(
    config: dict,
    buyer_id: str,
    document_profile: str = "default",
) -> dict:
    """
    buyer_id + document_profile → PL 配置。

    查找优先级：
      1. pl_profiles[buyer_id][document_profile]
      2. pl_profiles[buyer_id]["default"]
      3. pl_profiles["default"]
      4. 全部未命中 → raise PLConfigError

    参数:
        config: 完整 config dict（含 pl_profiles 段）
        buyer_id: buyer key
        document_profile: 文档 profile（默认 "default"）

    返回:
        dict — {"pl_config": "standard", "packing_profile": "standard_25kg", ...}
    """
    profiles = config.get("pl_profiles", {})
    if not profiles:
        raise PLConfigError("config.yaml 中缺少 pl_profiles 段")

    # 优先级 1: buyer + 指定 profile
    if buyer_id in profiles:
        buyer_section = profiles[buyer_id]
        if isinstance(buyer_section, dict):
            if document_profile in buyer_section:
                entry = buyer_section[document_profile]
                if isinstance(entry, dict) and "pl_config" in entry:
                    return entry

            # 优先级 2: buyer + default profile
            if document_profile != "default" and "default" in buyer_section:
                entry = buyer_section["default"]
                if isinstance(entry, dict) and "pl_config" in entry:
                    return entry

    # 优先级 3: 全局 default
    if "default" in profiles:
        entry = profiles["default"]
        if isinstance(entry, dict) and "pl_config" in entry:
            return entry

    raise PLConfigError(
        f"无法为 buyer_id='{buyer_id}', document_profile='{document_profile}' "
        f"找到 PL 配置。可用 profiles: {list(profiles.keys())}"
    )


def resolve_pl_config_name(
    config: dict,
    buyer_id: str,
    document_profile: str = "default",
) -> str:
    """便捷方法：直接返回 pl_config 名称字符串"""
    return resolve_pl_config(config, buyer_id, document_profile)["pl_config"]

"""
cli/init_wizard.py — Interactive cold-start setup wizard

Guides first-time users through configuring their seller info,
default trade terms, and first buyer. Writes to config/config.yaml.

Usage:
    python -m trade_pipeline init
"""
import yaml
from pathlib import Path

from trade_pipeline.paths import config_path as _config_path


def _get_config_path() -> Path:
    """Backward-compat shim; uses frozen-aware paths module."""
    return _config_path()


CONFIG_PATH = _get_config_path()

TRADE_TERMS_OPTIONS = {
    "1": ("FOB", "Free On Board — seller delivers to port, buyer handles shipping"),
    "2": ("CIF", "Cost, Insurance, Freight — seller pays shipping + insurance to destination"),
    "3": ("DDP", "Delivered Duty Paid — seller handles everything to buyer's door"),
    "4": ("EXW", "Ex Works — buyer picks up from seller's factory"),
    "5": ("CFR", "Cost and Freight — seller pays shipping, buyer handles insurance"),
}

CURRENCY_OPTIONS = {"1": "USD", "2": "CNY", "3": "EUR"}


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val if val else default


def _ask_choice(prompt: str, options: dict, default: str = "1") -> str:
    print(f"\n  {prompt}")
    for k, v in options.items():
        if isinstance(v, tuple):
            print(f"    {k}. {v[0]} — {v[1]}")
        else:
            print(f"    {k}. {v}")
    choice = input(f"  Enter choice [{default}]: ").strip()
    return choice if choice in options else default


def _make_seller_id(name_en: str) -> str:
    words = name_en.lower().replace(",", "").replace(".", "").split()
    key_words = [w for w in words if w not in ("co", "ltd", "inc", "llc", "corp", "limited", "company")]
    return "_".join(key_words[:2]) if key_words else "my_company"


def _make_buyer_id(name_en: str) -> str:
    words = name_en.lower().replace(",", "").replace(".", "").replace('"', "").replace("'", "").split()
    key_words = [w for w in words if w not in ("co", "ltd", "inc", "llc", "corp", "limited", "company", "ooo", "ооо")]
    return "_".join(key_words[:2]) if key_words else "buyer_1"


def run_init():
    print()
    print("=" * 60)
    print("  Trade Pipeline — First-Time Setup")
    print("=" * 60)

    # Check existing config
    if CONFIG_PATH.exists():
        overwrite = input("\n  config.yaml already exists. Overwrite? (y/N): ").strip().lower()
        if overwrite != "y":
            print("  Setup cancelled. Edit config/config.yaml manually if needed.")
            return

    # ── Seller info ──
    print("\n── Your Company (Seller) ─────────────────────────")
    seller_name_cn = _ask("Company name (Chinese, optional)", "")
    seller_name_en = _ask("Company name (English)", "ACME EXPORT CO., LTD.")
    seller_id = _make_seller_id(seller_name_en)
    seller_address = _ask("Address", "")
    seller_contact = _ask("Contact person", "")
    seller_email = _ask("Email", "")
    seller_tel = _ask("Phone", "")

    print("\n  Bank info (optional, can fill later):")
    bank_name = _ask("Bank name", "")
    bank_swift = _ask("SWIFT code", "")
    bank_account = _ask("Account number", "")

    # ── Trade terms ──
    print("\n── Default Trade Terms ───────────────────────────")
    terms_choice = _ask_choice("Default trade terms:", TRADE_TERMS_OPTIONS, "1")
    terms_name = TRADE_TERMS_OPTIONS[terms_choice][0]

    currency_choice = _ask_choice("Default currency:", CURRENCY_OPTIONS, "1")
    currency = CURRENCY_OPTIONS[currency_choice]

    port = _ask("Default port of loading", "QINGDAO,CHINA")

    payment = _ask("Payment terms", "30% T/T deposit; 70% before shipment")
    lead_time = _ask("Lead time", "45-60 days after deposit")
    validity = _ask("Quote validity", "10 days")

    # ── Price unit ──
    if currency == "CNY":
        price_unit = "CNY/MPCS"
    elif currency == "USD":
        pu_choice = _ask_choice("Pricing unit:", {"1": "USD/PC (per piece)", "2": "USD/TON (per ton)"}, "1")
        price_unit = "USD/PC" if pu_choice == "1" else "USD/TON"
    else:
        price_unit = f"{currency}/PC"

    # ── First buyer ──
    print("\n── First Buyer (optional, can add later) ────────")
    add_buyer = input("  Add a buyer now? (Y/n): ").strip().lower()
    buyer = None
    buyer_id = None
    if add_buyer != "n":
        buyer_name = _ask("Buyer company name (English)", "")
        if buyer_name:
            buyer_id = _make_buyer_id(buyer_name)
            buyer_address = _ask("Buyer address", "")
            buyer_contact = _ask("Buyer contact person", "")
            buyer_email = _ask("Buyer email", "")
            buyer = {
                "name_en": buyer_name,
                "name_ru": None,
                "legal_names": [buyer_name],
                "aliases": [buyer_name.split()[0]] if buyer_name else [],
                "address": buyer_address,
                "address_lines": [buyer_address] if buyer_address else [],
                "contact": buyer_contact,
                "email": buyer_email,
                "inn": "",
            }

    # ── Build config ──
    terms_id = f"default_{currency.lower()}"
    config = {
        "sellers": {
            seller_id: {
                "name_cn": seller_name_cn,
                "name_en": seller_name_en,
                "address": seller_address,
                "address_lines": [seller_address] if seller_address else [],
                "contact": seller_contact,
                "tel": seller_tel,
                "email": seller_email,
                "bank": {
                    "name": bank_name,
                    "address": "",
                    "swift": bank_swift,
                    "account_no": bank_account,
                    "account_name": seller_name_en,
                },
            }
        },
        "buyers": {},
        "format_defaults": {
            "standard": {
                "seller_id": seller_id,
                "currency": currency,
                "price_unit": price_unit,
                "terms_id": terms_id,
            },
        },
        "terms_templates": {
            terms_id: {
                "payment": payment,
                "delivery": f"{terms_name} {port}, Incoterms 2020. Price quoted in {currency}.",
                "lead_time": lead_time,
                "validity": validity,
                "packing": "Standard export packaging: 25 kg cartons, Euro pallets, stretch film.",
                "quality": "100% inspection before shipment.",
            },
        },
        "defaults": {
            "port_of_loading": port,
            "port_of_destination": None,
            "pi_number_pattern": "PI-{order_no}",
            "ci_number_pattern": "CI-{order_no}",
            "quote_no_pattern": "QT-{order_no}",
            "date_format": "%d %B %Y",
        },
        "packing": {
            "carton_weight_kg": 25,
            "pallet_self_weight_kg": 28,
            "cartons_per_pallet": 36,
        },
        "pl_profiles": {
            "default": {
                "pl_config": "standard",
                "packing_profile": "standard_25kg",
            },
        },
        "cache": {
            "dir": ".cache/understanding",
            "prompt_version": "v1.0",
            "schema_version": "v1.0",
            "enabled": True,
        },
        "ocr_review": {
            "force_review_fields": ["description", "standard", "quantity", "unit", "weight_kg"],
            "confidence_threshold": 0.90,
        },
    }

    if buyer and buyer_id:
        config["buyers"][buyer_id] = buyer
        config["pl_profiles"][buyer_id] = {
            "default": {"pl_config": "standard", "packing_profile": "standard_25kg"}
        }

    # ── Write config ──
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print()
    print("=" * 60)
    print(f"  Config saved to: {CONFIG_PATH}")
    print()
    print(f"  Seller: {seller_name_en} (id: {seller_id})")
    if buyer_id:
        print(f"  Buyer:  {buyer.get('name_en', '')} (id: {buyer_id})")
    print(f"  Terms:  {terms_name} | Currency: {currency} | Port: {port}")
    print()
    print("  Next steps:")
    print("    python -m trade_pipeline --input <inquiry.xlsx> --order <no>", end="")
    if buyer_id:
        print(f" --buyer {buyer_id}")
    else:
        print(" --buyer _new")
    print("=" * 60)
    print()


def add_buyer_interactive(config: dict, extracted_name: str) -> str | None:
    """Prompt user to create a new buyer when matching fails."""
    print()
    print(f"  Buyer '{extracted_name}' not found in config.")
    create = input("  Create new buyer? (Y/n): ").strip().lower()
    if create == "n":
        return None

    name_en = _ask("Buyer name (English)", extracted_name)
    buyer_id = _make_buyer_id(name_en)
    address = _ask("Address (optional)", "")
    contact = _ask("Contact (optional)", "")
    email = _ask("Email (optional)", "")

    buyer_data = {
        "name_en": name_en,
        "name_ru": None,
        "legal_names": [name_en],
        "aliases": [extracted_name] if extracted_name != name_en else [],
        "address": address,
        "address_lines": [address] if address else [],
        "contact": contact,
        "email": email,
        "inn": "",
    }

    config.setdefault("buyers", {})[buyer_id] = buyer_data

    # Write back config
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"  Buyer '{name_en}' saved as '{buyer_id}' in config.yaml")
    return buyer_id

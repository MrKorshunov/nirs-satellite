"""Load synthetic Payload 02 provenance, no Basilisk dependency."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CONFIG = Path(__file__).with_name("config.json")


def read_payload02_config() -> tuple[dict, str]:
    raw = CONFIG.read_bytes()
    cfg = json.loads(raw)
    if not str(cfg.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("Payload 02 inputs must declare synthetic provenance")
    if cfg["maximum_products_per_run"] != 1:
        raise ValueError("The first physical-capture scenario supports one product")
    return cfg, hashlib.sha256(raw).hexdigest()

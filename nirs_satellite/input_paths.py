"""Single authoritative registry of editable NIRS input files.

Source files are under inputs/; simulations and tests MUST reference these
paths rather than maintaining copies under individual experiment packages.
"""
from __future__ import annotations

from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "inputs"

FILES: dict[str, tuple[str, str]] = {
    "orbit": ("physical/orbit.json", "Орбита, масса и инерция корпуса"),
    "earth_target": ("physical/earth_target.json", "Земля, первая цель и видимость"),
    "adcs_wheels": ("physical/adcs_wheels.json", "Ориентация и три маховика Basilisk"),
    "power": ("physical/power.json", "Аккумулятор, панель, условное Солнце и потребители"),
    "camera_storage_radio": ("physical/camera_storage_radio.json", "Один снимок, память, канал и станция"),
    "camera_storage_radio_slow": ("physical/camera_storage_radio_slow.json", "Контрольный медленный радиоканал"),
    "observation_tasks": ("research/observation_tasks.json", "Многозадачные цели, станции и условные ресурсы"),
    "mission_execution": ("physical/mission_execution.json", "Физическое переключение двух целей и резерв заряда"),
    "adcs_ideal_legacy": ("physical/adcs_ideal_legacy.json", "Исторический ADCS без маховиков — только диагностика"),
    "payload_demo_legacy": ("physical/payload_demo_legacy.json", "Историческая проверка прибора"),
}


def input_path(name: str) -> Path:
    """Return a project-local input path; no arbitrary filesystem targets."""
    if name not in FILES:
        raise KeyError(f"Unknown input configuration: {name}")
    return INPUT_ROOT / FILES[name][0]


def load_input(name: str) -> dict:
    with input_path(name).open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Input {name} must contain a JSON object")
    return data

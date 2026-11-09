"""Safe, testable command plans for the Russian Windows launcher.

This module deliberately does not import Tkinter or Basilisk.
The front-end must not execute a shell or interpolate arbitrary user strings.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re

ROOT = Path(__file__).resolve().parents[1]
VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")

PROFILE_PHYSICAL = "physical"
PROFILE_RESEARCH = "research"
PROFILE_TEST = "tests"

PROFILES = {
    PROFILE_PHYSICAL: "Физическая модель: 1 съёмка, Basilisk + RW + питание + связь",
    PROFILE_RESEARCH: "Проверка планирования: несколько заданий, FIFO / EDF / Priority",
    PROFILE_TEST: "Автоматические проверки Python (без визуализации)",
}


@dataclass(frozen=True)
class RunPlan:
    profile: str
    argv: tuple[str, ...]
    result_dir: Path | None
    vizard_file: Path | None


def simulator_python(root: Path = ROOT) -> Path:
    """Interpreter in the isolated local environment, never global Python."""
    if __import__("os").name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def build_plan(
    *,
    profile: str,
    name: str,
    hours: float,
    python_executable: str | Path,
    record_vizard: bool,
    root: Path = ROOT,
    local_appdata: str | None = None,
) -> RunPlan:
    if profile not in PROFILES:
        raise ValueError("Неизвестный режим запуска")
    python_executable = str(python_executable)
    if not python_executable:
        raise ValueError("Не найден Python")
    if profile == PROFILE_TEST:
        argv = (
            python_executable, "-m", "unittest", "discover",
            "-s", "tests", "-p", "test_*.py", "-v",
        )
        return RunPlan(profile, argv, None, None)

    if not VALID_NAME.fullmatch(name):
        raise ValueError("Имя запуска: только латиница, цифры, _ и -, не больше 48 символов")
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("Длительность должна быть положительным числом часов")
    if profile == PROFILE_PHYSICAL:
        if hours < 0.2 or hours > 12:
            raise ValueError("Физическая модель: от 0.2 до 12 часов")
        # The one-product Mission 01 test assumes the original capture/contact
        # geometry. A very short run may not contain all the downlink window.
        argv = (
            python_executable, "-m", "experiments.mission_01.run_mission",
            "--actuator", "rw", "--power",
            "--duration-hours", str(hours),
            "--viz-mode", "file" if record_vizard else "off",
            "--output-name", name,
        )
        if record_vizard:
            argv += ("--viz-step-s", "10")
        vizard_base = (Path(local_appdata) if local_appdata else
                       Path.home() if __import__("os").name != "nt" else
                       Path(__import__("os").environ.get("LOCALAPPDATA", str(Path.home()))))
        viz = vizard_base / "NIRS_Satellite" / "viz" / (name + ".bin") if record_vizard else None
    else:
        if hours < 0.2 or hours > 24:
            raise ValueError("Планирование: от 0.2 до 24 часов")
        argv = (
            python_executable, "-m", "experiments.mission_02.run",
            "--duration-hours", str(hours),
            "--step-s", "10",
            "--output-name", name,
        )
        viz = None
    return RunPlan(profile, argv, root / "results" / name, viz)

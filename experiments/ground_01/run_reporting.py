"""Input provenance, machine-readable run manifest, and human-readable result guide.

No dependence on Basilisk. This does NOT assert physical accuracy of input data.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform


INPUT_FIELDS = {
    "initial_altitude_m": ("m", "orbit_01/config.json", "Synthetic circular-orbit initial altitude"),
    "eccentricity": ("1", "orbit_01/config.json", "Orbital eccentricity; zero means circular"),
    "inclination_deg": ("deg", "orbit_01/config.json", "Orbit plane tilt relative to reference equator"),
    "raan_deg": ("deg", "orbit_01/config.json", "Orientation of ascending node, synthetic inertial frame"),
    "reference_radius_m": ("m", "orbit_01/config.json", "Spherical Earth radius used by this scenario"),
    "hub_mass_kg": ("kg", "orbit_01/config.json", "Artificial hub mass; not a flight spacecraft mass"),
    "rotation_rate_rad_s": ("rad/s", "ground_01/config.json", "Assumed constant Earth angular speed"),
    "initial_sidereal_angle_deg": ("deg", "ground_01/config.json", "Synthetic initial Earth orientation, NOT UTC Greenwich angle"),
    "latitude_deg": ("deg", "ground_01/config.json", "Geocentric latitude of synthetic target"),
    "longitude_deg": ("deg", "ground_01/config.json", "Synthetic target longitude relative to initial planet-fixed meridian"),
    "minimum_elevation_deg": ("deg", "ground_01/config.json", "Geometry-only access cutoff angle"),
    "maximum_range_m": ("m", "ground_01/config.json", "-1 denotes no extra maximum slant-range constraint"),
    "step_s": ("s", "ground_01/config.json or CLI", "Dynamics and access evaluation cadence, NOT Vizard playback speed"),
    "number_of_orbits": ("orbit", "ground_01/config.json or CLI", "Default horizon; CLI hours/days may override"),
    "bytes_per_product": ("bytes", "payload_01/config.json", "Synthetic image product size, NOT measured camera output"),
}


RESULT_FIELDS = {
    "samples": ("count", "Number of saved geometry time stamps; not the number of images"),
    "access_samples": ("count", "Number of time stamps with access=true; multiplying by step is only a sampled approximation"),
    "max_elevation_deg": ("deg", "Highest elevation of spacecraft relative to target, among sampled states"),
    "minimum_slant_range_km": ("km", "Smallest geometric straight-line distance, may be non-visible at other times"),
    "windows": ("s", "Sample-bounded access windows; boundaries uncertain within one dynamics step"),
    "checks_passed": ("boolean", "Internal numerical consistency checks, not validation of real orbit/imagery"),
    "payload": ("bits", "Synthetic data generated (when enabled), not stored or downlinked"),
    "vizard": ("metadata", "Visualization settings; Vizard frames do not define dynamics accuracy"),
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_run_explanation(
    *,
    output: Path,
    plan: dict,
    configs: dict[str, tuple[Path, dict]],
    summary: dict,
    software: dict,
    notes: list[str],
) -> None:
    """Store exact inputs and plain-language interpretation next to results."""
    output.mkdir(parents=True, exist_ok=True)
    data = {
        "format_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": plan,
        "software": {
            **software,
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "inputs": {
            name: {
                "path": str(path),
                "sha256": _digest(path),
                "values": contents,
            }
            for name, (path, contents) in configs.items()
        },
        "input_dictionary": {
            name: {"unit": unit, "origin": origin, "meaning": meaning}
            for name, (unit, origin, meaning) in INPUT_FIELDS.items()
        },
        "result_dictionary": {
            name: {"unit": unit, "meaning": meaning}
            for name, (unit, meaning) in RESULT_FIELDS.items()
        },
        "observed_results": {
            "saved_samples": summary["samples"],
            "last_saved_time_s": summary["last_sample_time_s"],
            "access_samples": summary["access_samples"],
            "windows": summary["windows"],
            "max_elevation_deg": summary["max_elevation_deg"],
            "minimum_slant_range_km": summary["minimum_slant_range_km"],
            "checks_passed": summary["checks_passed"],
            "payload": summary.get("payload"),
        },
        "limitations": notes,
    }
    (output / "run_manifest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    input_lines = "\n".join(
        f"| `{key}` | {unit} | {meaning} | {origin} |"
        for key, (unit, origin, meaning) in INPUT_FIELDS.items()
    )
    result_lines = "\n".join(
        f"| `{key}` | {unit} | {meaning} |"
        for key, (unit, meaning) in RESULT_FIELDS.items()
    )
    limitations = "\n".join(f"- {x}" for x in notes)
    report = f"""# Результаты моделирования — {plan['output_name']}

## Что было задано
- Длительность: **{plan['horizon_s']:.6f} с**; источник: `{plan['duration_source']}`, значение: {plan['duration_value']}.
- Расчётный шаг динамики и видимости: **{plan['step_s']:g} с**.
- Режим Vizard: **{plan['viz_mode']}**; частота кадров: один каждые **{plan['viz_step_s']:g} с модельного времени**.
- Ускорение Live (если применимо): **{plan['live_speed']}×**; не гарантирует такую же частоту кадров на слабом ПК.
- Сохранённых состояний: **{summary['samples']}**, последний момент: **{summary['last_sample_time_s']:g} с**.
- Синтетический сценарий: **ДА**, реальной даты UTC нет. Измеренные параметры настоящего КА: **НЕТ**.

## Что получилось и что означает
- Геометрически доступных отсчётов: **{summary['access_samples']}**. Это количество строк, а не длительность окна.
- Наибольший угол места: **{summary['max_elevation_deg']:.6f}°** — из сообщений Basilisk groundLocation.
- Минимальная наклонная дальность: **{summary['minimum_slant_range_km']:.6f} км** — геометрическое расстояние, даже когда объект за Землёй.
- Окна геометрической доступности: **{len(summary['windows'])}**, границы по соседним отсчётам в `summary.json`.
- Контроль расчёта: **{'PASS' if summary['checks_passed'] else 'FAIL'}**. Контроль НЕ равен внешней валидации.
- Генерация данных: **{json.dumps(summary.get('payload'), ensure_ascii=False)}**. При наличии данные ещё не сохранены и не переданы.

## Где лежат исходные данные и сами результаты
- `run_manifest.json` — точные входные JSON, SHA-256 файлов, версия среды, настройки запуска, словарь параметров.
- `summary.json` — измеренные в модели показатели, окна и независимые внутренние проверки.
- `access.csv` — каждые {plan['step_s']:g} с: координаты КА, цели, угол места, дальность, доступность.
- `elevation.png` — график угла места (порог указан в исходном JSON).
- `slant_range.png` — прямая дистанция до цели; участок видимости отмечен отдельно.
- При `--payload`: `results/payload_01/events.csv`, `summary.json` — **событие формирования**, НЕ снимок.

## Словарь основных параметров
| Параметр | Единица | Значение | Происхождение |
|---|---|---|---|
{input_lines}

## Словарь результатов
| Показатель | Единица | Значение |
|---|---|---|
{result_lines}

## Ограничения интерпретации
{limitations}

Версия Basilisk: {software.get('bsk', 'unknown')}. Конфигурации содержатся в `run_manifest.json`, SHA-256 позволяют установить, изменялись ли исходные файлы.
"""
    (output / "RESULTS_EXPLAINED.md").write_text(report, encoding="utf-8")

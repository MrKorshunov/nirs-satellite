"""Validated time, output and visualization settings for Ground/Payload runs.

Pure Python so input handling can be tested without Basilisk installed.
Units: SI seconds; 'step' is dynamics update, 'viz_step' is rendering cadence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re


@dataclass(frozen=True)
class RunPlan:
    horizon_s: float
    duration_source: str
    duration_value: float
    step_s: float
    expected_samples: int
    viz_mode: str
    viz_step_s: float
    expected_viz_frames: int
    live_speed: float | None
    live_port: int | None
    output_name: str
    large_run_override: bool

    def as_dict(self) -> dict:
        return asdict(self)


def build_plan(
    *,
    default_orbits: float,
    orbit_period_s: float,
    default_step_s: float,
    duration_hours: float | None = None,
    duration_days: float | None = None,
    orbits: float | None = None,
    step_s: float | None = None,
    viz_mode: str = "off",
    legacy_viz: bool = False,
    viz_step_s: float | None = None,
    speed: float | None = None,
    live_port: int = 5556,
    output_name: str = "ground_01",
    allow_large_run: bool = False,
) -> RunPlan:
    for name, value in [
        ("default_orbits", default_orbits),
        ("orbit_period_s", orbit_period_s),
        ("default_step_s", default_step_s),
    ]:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")
    explicit = [(name, value, mul) for name, value, mul in [
        ("hours", duration_hours, 3600.0),
        ("days", duration_days, 86400.0),
        ("orbits", orbits, orbit_period_s),
    ] if value is not None]
    if len(explicit) > 1:
        raise ValueError("Choose only one duration unit: hours, days, or orbits")
    if explicit:
        unit, value, mul = explicit[0]
    else:
        unit, value, mul = "default_config_orbits", default_orbits, orbit_period_s
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Duration must be positive and finite")

    selected_step = default_step_s if step_s is None else step_s
    if not math.isfinite(selected_step) or selected_step <= 0:
        raise ValueError("Dynamics step must be positive and finite")
    horizon = value * mul
    if not math.isfinite(horizon) or horizon < selected_step:
        raise ValueError("Horizon must cover at least one dynamics step")

    if viz_mode not in ("off", "file", "live"):
        raise ValueError("Viz mode must be off, file or live")
    if legacy_viz:
        if viz_mode != "off":
            raise ValueError("Use --viz OR --viz-mode, not both")
        viz_mode = "file"
    visual_step = selected_step if viz_step_s is None else viz_step_s
    if not math.isfinite(visual_step) or visual_step < selected_step:
        raise ValueError("Vizard step must be finite and at least the dynamics step")
    ratio = visual_step / selected_step
    if not math.isfinite(ratio) or not math.isclose(ratio, round(ratio), rel_tol=0, abs_tol=1e-9):
        raise ValueError("Vizard step must be an integer multiple of the dynamics step")
    if viz_mode == "off" and viz_step_s is not None:
        raise ValueError("--viz-step-s requires --viz-mode file/live (or --viz)")
    if speed is not None and viz_mode != "live":
        raise ValueError("--speed controls only live simulation; file playback speed is set inside Vizard")
    if not isinstance(live_port, int) or not (1024 <= live_port <= 65535):
        raise ValueError("Live port must be between 1024 and 65535")
    acceleration = (50.0 if speed is None else speed) if viz_mode == "live" else None
    if acceleration is not None and (not math.isfinite(acceleration) or not (0.1 <= acceleration <= 1000.0)):
        raise ValueError("Live acceleration must be between 0.1 and 1000")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", output_name):
        raise ValueError("Output name must be 1–64 ASCII letters/digits/-/_ and start with a letter")

    # Inclusive t=0 sample. Basilisk may quantize stop time in nanoseconds;
    # the actual number of samples is checked after propagation.
    expected_samples = int(math.floor(horizon / selected_step)) + 1
    expected_viz_frames = int(math.floor(horizon / visual_step)) + 1 if viz_mode != "off" else 0
    if (expected_samples > 100_000 or expected_viz_frames > 100_000) and not allow_large_run:
        raise ValueError(
            f"Run would record approximately {expected_samples} dynamics samples and "
            f"{expected_viz_frames} Vizard frames; rerun with --allow-large-run "
            "only after estimating memory, disk and runtime."
        )

    return RunPlan(
        horizon_s=horizon,
        duration_source=unit,
        duration_value=value,
        step_s=selected_step,
        expected_samples=expected_samples,
        viz_mode=viz_mode,
        viz_step_s=visual_step,
        expected_viz_frames=expected_viz_frames,
        live_speed=acceleration,
        live_port=live_port if viz_mode == "live" else None,
        output_name=output_name,
        large_run_override=allow_large_run,
    )

"""Reproducible run settings for Ground 01.

Standard-library only: unit tests can validate configuration without Basilisk.
The model step, recording cadence and Vizard frame cadence are deliberately
different concepts and must be explicit in each experiment's metadata.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import math
import re


@dataclass(frozen=True)
class RunSettings:
    mode: str
    duration_s: float
    duration_source: str
    physics_step_s: float
    record_step_s: float
    viz_step_s: float | None
    live_speed_factor: float | None
    output_name: str
    estimated_physics_steps: int
    estimated_record_samples: int
    estimated_viz_frames: int

    def to_dict(self) -> dict:
        return asdict(self)


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--hours", type=float, help="Requested simulation duration in hours")
    duration.add_argument("--days", type=float, help="Requested simulation duration in days")
    duration.add_argument("--orbits", type=float, help="Requested duration in Keplerian orbital periods")
    parser.add_argument("--physics-step-s", type=float, default=None,
                        help="Integrator and ground-access task step, seconds")
    parser.add_argument("--record-step-s", type=float, default=None,
                        help="CSV/plots sample period, seconds (integer multiple of physics step)")
    parser.add_argument("--viz-step-s", type=float, default=None,
                        help="Vizard frame period, seconds (integer multiple of physics step)")
    parser.add_argument("--mode", choices=("batch", "playback", "live"), default=None,
                        help="batch=compute only, playback=write .bin, live=stream to Vizard")
    parser.add_argument("--speed", type=float, default=None,
                        help="Live streaming model-time speed factor (e.g. 10 or 50)")
    parser.add_argument("--output-name", type=str, default="ground_01",
                        help="Output folder name under results/, ASCII letters/digits/_/-")


def _positive_finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return value


def _cadence(name: str, seconds: float, physics_step_s: float) -> float:
    seconds = _positive_finite(name, seconds)
    ratio = seconds / physics_step_s
    if seconds + 1e-9 < physics_step_s or not math.isclose(
        ratio, round(ratio), rel_tol=0.0, abs_tol=1e-8
    ):
        raise ValueError(f"{name} must be an integer multiple of the physics step")
    return seconds


def resolve_run(args: argparse.Namespace, scenario: dict, orbit_period_s: float) -> RunSettings:
    period = _positive_finite("orbit_period_s", orbit_period_s)
    default_step = _positive_finite("scenario.step_s", scenario["step_s"])
    physics_step = _positive_finite(
        "physics_step_s", args.physics_step_s if args.physics_step_s is not None else default_step
    )
    record_step = _cadence(
        "record_step_s",
        args.record_step_s if args.record_step_s is not None else physics_step,
        physics_step,
    )
    mode = args.mode if args.mode is not None else ("playback" if args.viz else "batch")
    if args.viz and mode != "playback":
        raise ValueError("--viz is a legacy alias for playback and cannot be combined with another mode")
    if args.speed is not None and mode != "live":
        raise ValueError("--speed applies only to --mode live; playback speed is set inside Vizard")
    live_speed = (
        _positive_finite("speed", args.speed if args.speed is not None else 50.0)
        if mode == "live" else None
    )
    viz_step = None
    if mode in ("playback", "live"):
        viz_step = _cadence(
            "viz_step_s",
            args.viz_step_s if args.viz_step_s is not None else physics_step,
            physics_step,
        )
    elif args.viz_step_s is not None:
        raise ValueError("--viz-step-s is only valid in playback or live modes")

    if args.hours is not None:
        duration = _positive_finite("hours", args.hours) * 3600.0
        source = "command_line_hours"
    elif args.days is not None:
        duration = _positive_finite("days", args.days) * 86400.0
        source = "command_line_days"
    elif args.orbits is not None:
        duration = _positive_finite("orbits", args.orbits) * period
        source = "command_line_orbits"
    else:
        duration = _positive_finite("scenario.number_of_orbits", scenario["number_of_orbits"]) * period
        source = "scenario_config_orbits"
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid simulation duration")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.output_name or ""):
        raise ValueError("--output-name must contain only ASCII letters, digits, underscore or dash")

    # Avoid accidentally generating gigabytes of telemetry, visualizations
    # and multiple-day physical runs on a student's laptop.
    physics_n = math.ceil(duration / physics_step) + 1
    samples_n = math.ceil(duration / record_step) + 1
    viz_n = math.ceil(duration / viz_step) + 1 if viz_step else 0
    if physics_n > 200_000 or samples_n > 150_000 or viz_n > 150_000:
        raise ValueError(
            "Run exceeds safe sample limits. Use a larger physics/record/viz step "
            "or split the simulation into shorter experiments."
        )
    if args.payload and (not math.isclose(duration, period, rel_tol=1e-9)
                         or not math.isclose(record_step, physics_step, rel_tol=1e-9)):
        raise ValueError(
            "Payload 01 is a one-product, one-orbit experiment only; "
            "do not silently interpret it as repeated imaging over days."
        )

    return RunSettings(
        mode=mode,
        duration_s=duration,
        duration_source=source,
        physics_step_s=physics_step,
        record_step_s=record_step,
        viz_step_s=viz_step,
        live_speed_factor=live_speed,
        output_name=args.output_name,
        estimated_physics_steps=physics_n,
        estimated_record_samples=samples_n,
        estimated_viz_frames=viz_n,
    )

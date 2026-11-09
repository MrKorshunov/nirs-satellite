"""Mission 02: bounded, deterministic operations simulator driven by Basilisk states.

Basilisk supplies propagated spacecraft positions.  This stdlib-only layer is
NOT a flight-dynamics, reaction-wheel, battery or radio-hardware simulator.
It implements conservative, declared resource constraints to study scheduling.
All geometry is a rotating SPHERE with a synthetic epoch.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from experiments.ground_01.geometry import elevation_from_inertial

K_B = 1.380649e-23
C_LIGHT = 299792458.0
DEG = math.pi / 180.0


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    length = norm(a)
    if length <= 0:
        raise ValueError("Cannot normalize a zero vector")
    return tuple(x / length for x in a)


def angular_distance(a, b):
    return math.acos(max(-1.0, min(1.0, dot(unit(a), unit(b)))))


def ground_vector(lat_deg, lon_deg, radius_m, t_s, earth_rate):
    lat = lat_deg * DEG
    lon = lon_deg * DEG + t_s * earth_rate
    return (
        radius_m * math.cos(lat) * math.cos(lon),
        radius_m * math.cos(lat) * math.sin(lon),
        radius_m * math.sin(lat),
    )


def line_of_sight(sc, ground):
    return tuple(g - s for g, s in zip(ground, sc))


def off_nadir_deg(sc, ground):
    return angular_distance(line_of_sight(sc, ground), tuple(-x for x in sc)) / DEG


def in_parallel_shadow(sc, earth_radius, sun_direction):
    """Cylindrical shadow of a spherical Earth; deliberately simplified."""
    sun = unit(sun_direction)
    along = dot(sc, sun)
    transverse_sq = max(0.0, dot(sc, sc) - along * along)
    return along < 0 and transverse_sq < earth_radius ** 2


def rate_from_friis(distance_m, link):
    """Idealized Eb/N0 bitrate cap. No actual BER, coding, RF fading or ACK."""
    if distance_m <= 0:
        raise ValueError("Radio distance must be positive")
    wavelength = C_LIGHT / float(link["frequency_hz"])
    receive_w = (float(link["tx_power_w"]) *
                 10 ** (float(link["tx_gain_dbi"]) / 10) *
                 10 ** (float(link["rx_gain_dbi"]) / 10) *
                 (wavelength / (4 * math.pi * distance_m)) ** 2)
    required_ebno = 10 ** (float(link["required_ebno_db"]) / 10)
    margin = 10 ** (float(link["margin_db"]) / 10)
    ideal_rate = receive_w / (K_B * float(link["system_noise_k"]) * required_ebno * margin)
    return max(0.0, min(float(link["nominal_rate_bps"]), ideal_rate))


@dataclass(frozen=True)
class State:
    t_s: float
    pos_m: tuple[float, float, float]


def load_basilisk_track(path: Path) -> list[State]:
    """Read the existing Ground 01 access.csv, which records Basilisk positions."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"time_s", "sc_x_m", "sc_y_m", "sc_z_m"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Track must be Basilisk Ground 01 access.csv")
        states = [
            State(float(r["time_s"]), tuple(float(r[k]) for k in
                   ("sc_x_m", "sc_y_m", "sc_z_m")))
            for r in reader
        ]
    if len(states) < 3:
        raise ValueError("Need at least three Basilisk state samples")
    if not all(math.isfinite(s.t_s) and all(math.isfinite(x) for x in s.pos_m)
               for s in states):
        raise ValueError("Nonfinite orbit state")
    dt = states[1].t_s - states[0].t_s
    if dt <= 0 or any(abs((b.t_s - a.t_s) - dt) > 1e-6
                      for a, b in zip(states, states[1:])):
        raise ValueError("Basilisk states require a uniform positive step")
    if abs(states[0].t_s) > 1e-6:
        raise ValueError("Track must begin at synthetic epoch t=0")
    return states


def validate(config, step_s):
    if not str(config.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("Synthetic provenance must be explicitly declared")
    if not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("Invalid time step")
    if config["earth"]["radius_m"] <= 0:
        raise ValueError("Earth radius invalid")
    sc, power, comm = config["spacecraft"], config["power"], config["radio"]
    if min(sc["max_slew_rate_deg_s"], sc["max_torque_nm"], sc["inertia_kg_m2"],
           sc["rw_momentum_limit_nms"], power["battery_capacity_wh"],
           power["solar_charge_w"], comm["nominal_rate_bps"],
           comm["tx_power_w"], comm["frequency_hz"], comm["system_noise_k"]) <= 0:
        raise ValueError("Resource parameters must be positive")
    if not 0 < power["initial_wh"] <= power["battery_capacity_wh"]:
        raise ValueError("Initial battery outside capacity")
    if not 0 <= power["reserve_wh"] < power["initial_wh"]:
        raise ValueError("Power reserve must be below initial energy")
    if sc["storage_capacity_bytes"] <= 0 or comm["packet_bytes"] <= 0:
        raise ValueError("Invalid memory or packet")
    if not config["stations"] or not config["tasks"]:
        raise ValueError("Provide targets and ground stations")
    ids = [t["id"] for t in config["tasks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate target identifier")
    for item in [*config["tasks"], *config["stations"]]:
        if not -90 <= item["lat_deg"] <= 90 or not -180 <= item["lon_deg"] <= 180:
            raise ValueError("Invalid site coordinates")
    for task in config["tasks"]:
        if not (0 <= task["release_s"] < task["deadline_s"] and
                task["priority"] > 0 and task["exposure_s"] > 0 and
                task["product_bytes"] > 0 and task["product_bytes"] %
                comm["packet_bytes"] == 0):
            raise ValueError("Invalid assignment or packet/product relation")
    for key in ("idle_w", "slew_w", "imaging_w", "transmit_w"):
        if float(power[key]) < 0:
            raise ValueError("Negative electrical load")
    if comm["required_ebno_db"] < 0 or comm["margin_db"] < 0:
        raise ValueError("Invalid radio margin")


def _geo_access(state, site, cfg, min_elevation_deg):
    radius = cfg["earth"]["radius_m"] + float(site.get("altitude_m", 0))
    point = ground_vector(site["lat_deg"], site["lon_deg"], radius,
                          state.t_s, cfg["earth"]["rotation_rate_rad_s"])
    elevation = elevation_from_inertial(state.pos_m, point)
    return elevation >= min_elevation_deg * DEG, point, norm(line_of_sight(state.pos_m, point))


def _slew_seconds(angle_rad, cfg):
    """Symmetric accelerate/coast/decelerate bound, NOT integrated RW dynamics."""
    sc = cfg["spacecraft"]
    accel = sc["max_torque_nm"] / sc["inertia_kg_m2"]
    vmax = min(sc["max_slew_rate_deg_s"] * DEG,
               sc["rw_momentum_limit_nms"] / sc["inertia_kg_m2"])
    if vmax <= 0:
        return math.inf
    switch = vmax * vmax / accel
    return (2 * math.sqrt(angle_rad / accel) if angle_rad <= switch
            else 2 * vmax / accel + (angle_rad - switch) / vmax)


def _choice(tasks, policy):
    if policy == "fifo":
        return min(tasks, key=lambda t: (t["release_s"], t["id"]))
    if policy == "edf":
        return min(tasks, key=lambda t: (t["deadline_s"], -t["priority"], t["id"]))
    if policy == "priority":
        return min(tasks, key=lambda t: (-t["priority"], t["deadline_s"], t["id"]))
    raise ValueError(f"Unknown policy: {policy}")


def simulate(states, cfg, policy):
    """Run exactly one spacecraft with exclusive slew/capture/downlink modes.

    Resource constraints: sampled access, off-nadir, continuous storage bits,
    finite battery reserve, idealized solar eclipse, bounded slew time/momentum,
    full-packet RF with Friis bitrate cap, task release/deadline. No closed-loop
    ADCS for every target; this is an operations-level model.
    """
    if policy not in {"fifo", "edf", "priority"}:
        raise ValueError("Unknown scheduling policy")
    dt = states[1].t_s - states[0].t_s
    validate(cfg, dt)
    tasks = {t["id"]: dict(t) for t in cfg["tasks"]}
    assert len(tasks) == len(cfg["tasks"])
    energy = float(cfg["power"]["initial_wh"])
    cap = float(cfg["power"]["battery_capacity_wh"])
    reserve = float(cfg["power"]["reserve_wh"])
    capacity_bits = int(cfg["spacecraft"]["storage_capacity_bytes"]) * 8
    packet = int(cfg["radio"]["packet_bytes"]) * 8
    stored = 0.0
    created = 0.0
    delivered_bits = 0.0
    max_stored = 0.0
    min_energy = energy
    spent_wh = 0.0
    solar_wh = 0.0
    products = []
    events = []
    trace = []
    completed = set()
    rejected = set()
    captured = set()
    mode = "idle"
    active_id = None
    until = 0.0
    current_pointing = unit(tuple(-x for x in states[0].pos_m))
    eclipse_count = 0
    no_power_steps = 0
    max_off_nadir = float(cfg["spacecraft"]["max_off_nadir_deg"])
    sun = unit(tuple(cfg["power"]["sun_direction_inertial"]))
    for index, state in enumerate(states[:-1]):
        t = state.t_s
        sc = state.pos_m
        shadow = in_parallel_shadow(sc, cfg["earth"]["radius_m"], sun)
        eclipse_count += int(shadow)
        solar = 0.0 if shadow else float(cfg["power"]["solar_charge_w"])
        activity = "idle"
        source = None

        # Complete previous operation at this sample boundary.
        if active_id is not None and t >= until - 1e-7:
            task = tasks[active_id]
            eligible, target, _ = _geo_access(state, task, cfg,
                                              task["min_elevation_deg"])
            eligible &= off_nadir_deg(sc, target) <= max_off_nadir
            if mode == "slew":
                current_pointing = unit(line_of_sight(sc, target))
                if eligible and t + task["exposure_s"] <= task["deadline_s"]:
                    n = math.ceil(task["exposure_s"] / dt)
                    mode, until = "capture", t + max(1, n) * dt
                    events.append({"t_s": t, "event": "exposure_start", "task": active_id})
                else:
                    events.append({"t_s": t, "event": "slew_window_lost", "task": active_id})
                    active_id, mode = None, "idle"
            elif mode == "capture":
                if eligible and stored + 8 * task["product_bytes"] <= capacity_bits:
                    volume = 8 * task["product_bytes"]
                    products.append({"id": active_id, "remaining_bits": float(volume),
                                     "capture_s": t})
                    stored += volume
                    created += volume
                    captured.add(active_id)
                    events.append({"t_s": t, "event": "captured", "task": active_id,
                                   "bits": volume})
                else:
                    rejected.add(active_id)
                    events.append({"t_s": t, "event": "capture_rejected",
                                   "task": active_id, "reason": "access_or_memory"})
                active_id, mode = None, "idle"

        if active_id is None:
            eligible_tasks = []
            for candidate in tasks.values():
                if candidate["id"] in captured or candidate["id"] in rejected:
                    continue
                if not candidate["release_s"] <= t < candidate["deadline_s"]:
                    continue
                if stored + 8 * candidate["product_bytes"] > capacity_bits:
                    continue
                ready, point, _ = _geo_access(state, candidate, cfg,
                                              candidate["min_elevation_deg"])
                if not ready or off_nadir_deg(sc, point) > max_off_nadir:
                    continue
                los = unit(line_of_sight(sc, point))
                slew = _slew_seconds(angular_distance(current_pointing, los), cfg)
                slew_steps = max(1, math.ceil((slew + cfg["spacecraft"]["settle_s"]) / dt))
                exposure_steps = max(1, math.ceil(candidate["exposure_s"] / dt))
                finish_idx = index + slew_steps + exposure_steps
                if finish_idx >= len(states) or states[finish_idx].t_s > candidate["deadline_s"]:
                    continue
                # An already-known sampled window must cover both operation boundaries.
                if not all(_geo_access(states[k], candidate, cfg,
                                       candidate["min_elevation_deg"])[0] and
                           off_nadir_deg(states[k].pos_m,
                               _geo_access(states[k], candidate, cfg,
                                           candidate["min_elevation_deg"])[1]) <= max_off_nadir
                           for k in (index + slew_steps, finish_idx)):
                    continue
                required_wh = (
                    (slew_steps * (cfg["power"]["idle_w"] + cfg["power"]["slew_w"]) +
                     exposure_steps * (cfg["power"]["idle_w"] + cfg["power"]["imaging_w"]))
                    * dt / 3600.0
                )
                if energy - required_wh < reserve:
                    continue
                eligible_tasks.append((candidate, slew_steps))
            if eligible_tasks:
                selected = _choice([x[0] for x in eligible_tasks], policy)
                slew_steps = next(n for task, n in eligible_tasks if task["id"] == selected["id"])
                active_id = selected["id"]
                mode = "slew"
                until = t + slew_steps * dt
                events.append({"t_s": t, "event": "slew_start", "task": active_id,
                               "until_s": until})

        # Transmit only when there is no camera or slew operation.
        if active_id is not None:
            activity = mode
        elif products:
            options = []
            for station in cfg["stations"]:
                visible, point, distance = _geo_access(
                    state, station, cfg, station["min_elevation_deg"])
                if visible:
                    rate = rate_from_friis(distance, cfg["radio"])
                    if rate > 0:
                        options.append((rate, station["id"]))
            if options:
                effective_rate, source = max(options)
                # Link activity is conditional on enough energy to stay above reserve.
                projected = energy + (solar - cfg["power"]["idle_w"] -
                                     cfg["power"]["transmit_w"]) * dt / 3600
                if projected >= reserve:
                    activity = "transmit"
                    available_packets = int((effective_rate * dt) // packet)
                    if available_packets:
                        # Partial last packets are intentionally disabled, as in Basilisk demo.
                        budget = available_packets * packet
                        while products and budget >= packet:
                            chosen = _choice([tasks[p["id"]] for p in products], policy)
                            product = next(p for p in products if p["id"] == chosen["id"])
                            transfer = min(budget, product["remaining_bits"])
                            transfer = math.floor(transfer / packet) * packet
                            if transfer < packet:
                                break
                            product["remaining_bits"] -= transfer
                            budget -= transfer
                            stored -= transfer
                            delivered_bits += transfer
                            if product["remaining_bits"] <= 0:
                                completed.add(product["id"])
                                event = "delivered_on_time" if t + dt <= chosen["deadline_s"] else "delivered_late"
                                events.append({"t_s": t + dt, "event": event,
                                               "task": product["id"],
                                               "latency_s": t + dt - product["capture_s"]})
                                products.remove(product)

        load = cfg["power"]["idle_w"]
        if activity == "slew":
            load += cfg["power"]["slew_w"]
        elif activity == "capture":
            load += cfg["power"]["imaging_w"]
        elif activity == "transmit":
            load += cfg["power"]["transmit_w"]
        if energy + (solar - load) * dt / 3600 < reserve - 1e-9:
            no_power_steps += 1
            # Abort active task if even the reserved load cannot be supplied.
            if activity in ("slew", "capture"):
                events.append({"t_s": t, "event": "power_abort", "task": active_id})
                rejected.add(active_id)
                active_id, mode = None, "idle"
                activity, load = "idle", cfg["power"]["idle_w"]
            if energy + (solar - load) * dt / 3600 < reserve - 1e-9:
                # Safe-mode approximation: zero additional activity, minimum base load.
                load = min(load, max(0.0, solar + (energy - reserve) * 3600 / dt))
        energy = min(cap, max(reserve, energy + (solar - load) * dt / 3600))
        solar_wh += solar * dt / 3600
        spent_wh += load * dt / 3600
        min_energy = min(min_energy, energy)
        max_stored = max(max_stored, stored)
        if stored < -0.1 or stored > capacity_bits + 0.1:
            raise AssertionError("Memory capacity violated")
        if energy < reserve - 1e-7 or energy > cap + 1e-7:
            raise AssertionError("Battery capacity violated")
        trace.append({"time_s": t, "activity": activity, "task": active_id or "",
                      "station": source or "", "storage_bits": int(stored),
                      "battery_wh": round(energy, 7), "sunlit": int(not shadow),
                      "generated_bits": int(created),
                      "transmitted_bits": int(delivered_bits)})
    balance_error = created - stored - delivered_bits
    if abs(balance_error) > 0.1:
        raise AssertionError(f"Mass-memory conservation failed: {balance_error}")
    delivered_on_time = {e["task"] for e in events if e["event"] == "delivered_on_time"}
    total_weight = sum(task["priority"] for task in tasks.values())
    score = sum(tasks[tid]["priority"] for tid in delivered_on_time) / total_weight
    return {
        "summary": {
            "policy": policy, "tasks": len(tasks), "captured": len(captured),
            "fully_delivered": len(completed),
            "delivered_on_time": len(delivered_on_time),
            "weighted_on_time_fraction": round(score, 8),
            "generated_bits": int(created), "transmitted_bits": int(delivered_bits),
            "stored_bits": int(stored), "max_stored_bits": int(max_stored),
            "capacity_bits": capacity_bits, "balance_error_bits": balance_error,
            "final_battery_wh": round(energy, 7),
            "min_battery_wh": round(min_energy, 7),
            "solar_energy_wh": round(solar_wh, 6),
            "consumed_energy_wh": round(spent_wh, 6),
            "eclipse_samples": eclipse_count,
            "power_limited_samples": no_power_steps,
            "sample_step_s": dt,
            "assumptions": [
                "Basilisk spacecraft positions, reduced-order discrete mission operations",
                "Spherical rotating Earth and arbitrary epoch (NOT real UTC)",
                "Off-nadir and sampled access, but no full attitude dynamics per retarget",
                "Conservative minimum-time slew bound; not a Basilisk wheel simulation",
                "Fixed inertial Sun and cylindrical shadow; solar power independent of panel attitude",
                "Ideal battery with no aging, voltage, temperature or charge efficiency losses",
                "Friis Eb/N0 bitrate cap, not a verified link budget or ground-station ACK",
                "Full packets only; no actual RF waveform, BER or coding",
            ],
        },
        "events": events, "trace": trace,
    }

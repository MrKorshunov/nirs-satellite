"""Attach documented Basilisk eclipse + solar-panel + battery models.

Uses fixed synthetic Sun state, actual spacecraft pose and Basilisk Earth state.
Power loads are enabled continuously in mission mode as an upper-bound.
DeviceCmd and DeviceStatus types are incompatible; no unsafe conversion.
No battery-to-device automatic inhibit is claimed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math

from Basilisk.architecture import messaging
from Basilisk.simulation import eclipse, simpleBattery, simplePowerSink, simpleSolarPanel

CONFIG = Path(__file__).with_name("config.json")


@dataclass
class PowerComponents:
    config: dict
    config_sha256: str
    eclipse_rec: object
    panel_rec: object
    base_rec: object
    battery_rec: object
    imaging_rec: object
    transmitter_rec: object


def _valid(cfg):
    if not cfg["provenance"].startswith("SYNTHETIC"):
        raise ValueError("Power-01 reference requires SYNTHETIC provenance")
    for k in ("battery_capacity_wh", "battery_initial_wh", "panel_area_m2",
              "panel_efficiency", "base_load_w", "sun_distance_m"):
        if not math.isfinite(float(cfg[k])) or float(cfg[k]) <= 0:
            raise ValueError(f"Invalid physical power parameter {k}")
    if cfg["battery_initial_wh"] > cfg["battery_capacity_wh"]:
        raise ValueError("Initial battery charge exceeds capacity")
    if not 0 < float(cfg["panel_efficiency"]) <= 1:
        raise ValueError("Invalid panel efficiency")
    for k in ("imaging_load_w", "transmitter_load_w"):
        if float(cfg[k]) < 0:
            raise ValueError(f"Negative power load {k}")
    normal, direction = cfg["panel_normal_body"], cfg["sun_inertial_direction"]
    if len(normal) != 3 or len(direction) != 3 or not all(
            math.isfinite(float(x)) for x in normal + direction):
        raise ValueError("Expected two finite three-component unit vectors")
    if abs(math.sqrt(sum(x*x for x in normal))-1)>1e-8:
        raise ValueError("Panel normal must be unit")
    if abs(math.sqrt(sum(x*x for x in direction))-1)>1e-8:
        raise ValueError("Sun direction must be unit")


def attach(sim, task, spacecraft, earth_planet_msg,
           *, mission_loads_always_on: bool = False):
    cfg_bytes=CONFIG.read_bytes()
    config=json.loads(cfg_bytes)
    _valid(config)
    sun_msg=messaging.SpicePlanetStateMsg().write(
        messaging.SpicePlanetStateMsgPayload(
            PlanetName="sun",
            PositionVector=[float(x)*float(config["sun_distance_m"]) for x in
                            config["sun_inertial_direction"]],
        )
    )
    eclipses=eclipse.Eclipse()
    eclipses.ModelTag="POWER01_BasiliskConicalEclipse"
    eclipses.addSpacecraftToModel(spacecraft.scStateOutMsg)
    eclipses.addPlanetToModel(earth_planet_msg)
    eclipses.sunInMsg.subscribeTo(sun_msg)
    sim.AddModelToTask(task,eclipses,ModelPriority=80)

    panel=simpleSolarPanel.SimpleSolarPanel()
    panel.ModelTag="POWER01_BodyFixedSolarPanel"
    panel.stateInMsg.subscribeTo(spacecraft.scStateOutMsg)
    panel.sunEclipseInMsg.subscribeTo(eclipses.eclipseOutMsgs[0])
    panel.sunInMsg.subscribeTo(sun_msg)
    panel.setPanelParameters(config["panel_normal_body"],
                             float(config["panel_area_m2"]),
                             float(config["panel_efficiency"]))
    sim.AddModelToTask(task,panel,ModelPriority=79)

    base=simplePowerSink.SimplePowerSink()
    base.ModelTag="POWER01_AlwaysOnBusLoad"
    base.nodePowerOut=-float(config["base_load_w"])
    sim.AddModelToTask(task,base,ModelPriority=78)

    instrument=simplePowerSink.SimplePowerSink()
    instrument.ModelTag="POWER01_ImagerPower"
    instrument.nodePowerOut=-float(config["imaging_load_w"])
    # DeviceCmdMsg != DeviceStatusMsg in Basilisk; no unsafe message cast.
    # Conservative mission-level upper-bound: imaging load energized
    # during entire mission run (not the exact instrument on/off timeline).
    instrument.powerStatus = 1 if mission_loads_always_on else 0
    sim.AddModelToTask(task,instrument,ModelPriority=77)

    transmitter=simplePowerSink.SimplePowerSink()
    transmitter.ModelTag="POWER01_TransmitterPower"
    transmitter.nodePowerOut=-float(config["transmitter_load_w"])
    # Conservative mission-level upper-bound radio consumption.
    transmitter.powerStatus = 1 if mission_loads_always_on else 0
    sim.AddModelToTask(task,transmitter,ModelPriority=76)

    battery=simpleBattery.SimpleBattery()
    battery.ModelTag="POWER01_BasiliskSimpleBattery"
    battery.storageCapacity=float(config["battery_capacity_wh"])*3600.0
    battery.storedCharge_Init=float(config["battery_initial_wh"])*3600.0
    for node in (panel,base,instrument,transmitter):
        battery.addPowerNodeToModel(node.nodePowerOutMsg)
    sim.AddModelToTask(task,battery,ModelPriority=75)

    recs=(eclipses.eclipseOutMsgs[0].recorder(),
          panel.nodePowerOutMsg.recorder(),
          base.nodePowerOutMsg.recorder(),
          battery.batPowerOutMsg.recorder(),
          instrument.nodePowerOutMsg.recorder(),
          transmitter.nodePowerOutMsg.recorder())
    for rec in recs:
        sim.AddModelToTask(task,rec,ModelPriority=0)
    return PowerComponents(config,hashlib.sha256(cfg_bytes).hexdigest(),*recs)

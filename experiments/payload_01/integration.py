"""Use Basilisk's instrument and controller with EXPLICIT ideal pointing.

Only first-stage event generation: no camera optics, real ADCS, storage,
transmitter or data delivery. The zero attitude guidance is an assumption,
not a computed pointing result.
"""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path

from Basilisk.architecture import messaging
from Basilisk.fswAlgorithms import simpleInstrumentController
from Basilisk.simulation import simpleInstrument


CONFIG = Path(__file__).with_name("config.json")


def attach(sim, task: str, access_out_msg, step_s: float,
           *, physical_guidance_msg=None, adcs_config: dict | None = None):
    cfg_raw = CONFIG.read_bytes()
    cfg = json.loads(cfg_raw)
    cfg_sha_at_read = hashlib.sha256(cfg_raw).hexdigest()
    if not str(cfg["provenance"]).startswith("SYNTHETIC"):
        raise ValueError("Payload data must be marked SYNTHETIC")
    bits = cfg["bytes_per_product"] * 8
    if (not isinstance(cfg["bytes_per_product"], int)
            or cfg["bytes_per_product"] <= 0
            or cfg["maximum_products_per_pass"] != 1
            or not math.isfinite(step_s) or step_s <= 0):
        raise ValueError("Invalid synthetic instrument configuration")

    controller = simpleInstrumentController.simpleInstrumentController()
    controller.ModelTag = "SyntheticSingleExposureController"
    if physical_guidance_msg is not None:
        if adcs_config is None:
            raise ValueError("ADCS settings needed for physical guidance")
        # Basilisk's simpleInstrumentController tolerance is MRP NORM,
        # NOT degrees. Convert physical-angle tolerance using tan(theta/4).
        # For this 2-axis pointing reference, roll does not constrain optics.
        max_deg = float(adcs_config["readiness_boresight_max_deg"])
        max_rate = float(adcs_config["readiness_tracking_rate_max_rad_s"])
        controller.attErrTolerance = math.tan(math.radians(max_deg) / 4)
        controller.useRateTolerance = 1
        controller.rateErrTolerance = max_rate
        controller.attGuidInMsg.subscribeTo(physical_guidance_msg)
        controller.ModelTag = "PhysicalADCSConstrainedInstrumentController"
    else:
        controller.attErrTolerance = 0.1
        # Original Payload 01: explicitly declared nonphysical zero error.
        ideal_guidance = messaging.AttGuidMsg().write(messaging.AttGuidMsgPayload())
        controller.attGuidInMsg.subscribeTo(ideal_guidance)
    controller.locationAccessInMsg.subscribeTo(access_out_msg)

    sim.AddModelToTask(task, controller, ModelPriority=95)

    instrument = simpleInstrument.SimpleInstrument()
    instrument.ModelTag = "SyntheticOneMegabyteInstrument"
    instrument.nodeDataName = str(cfg["name"])
    # DataNodeUsageMsg baudRate is bits/s; one on-tick produces bits/step.
    instrument.nodeBaudRate = bits / step_s
    instrument.nodeStatusInMsg.subscribeTo(controller.deviceCmdOutMsg)
    sim.AddModelToTask(task, instrument, ModelPriority=90)

    command_record = controller.deviceCmdOutMsg.recorder()
    data_record = instrument.nodeDataOutMsg.recorder()
    sim.AddModelToTask(task, command_record, ModelPriority=0)
    sim.AddModelToTask(task, data_record, ModelPriority=0)
    return cfg, command_record, data_record, cfg_sha_at_read

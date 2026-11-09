"""Connect genuine Basilisk rigid-body ADCS tracking to Ground 01.

Implemented via official Basilisk 2.12.2 modules:
  simpleNav -> locationPointing -> mrpFeedback -> extForceTorque -> Spacecraft.
This first stage assumes perfect navigation and an IDEAL continuous 3-axis
actuator: NO reaction wheels, torque clipping, sensor noise, or real camera.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from Basilisk.architecture import messaging
from Basilisk.fswAlgorithms import locationPointing, mrpFeedback
from Basilisk.simulation import extForceTorque, simpleNav


CONFIG = Path(__file__).with_name("config.json")


@dataclass
class ADCSComponents:
    config: dict
    config_sha256: str
    guidance_recorder: object
    torque_recorder: object
    nav_recorder: object
    guidance_msg: object


def _triplet(name: str, value: object) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name} must be a list of 3 numbers")
    v = [float(x) for x in value]
    if any(not math.isfinite(x) for x in v):
        raise ValueError(f"Non-finite {name}")
    return v


def validate_adcs_config(config: dict, step_s: float) -> None:
    if not str(config.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("ADCS configuration must identify synthetic inputs")
    attitude = _triplet("initial_sigma_BN_mrp", config["initial_sigma_BN_mrp"])
    rate = _triplet("initial_omega_BN_B_rad_s", config["initial_omega_BN_B_rad_s"])
    boresight = _triplet("instrument_boresight_B", config["instrument_boresight_B"])
    norm = math.sqrt(sum(x*x for x in boresight))
    if not math.isclose(norm, 1.0, rel_tol=0, abs_tol=1e-10):
        raise ValueError("instrument_boresight_B must be a unit vector")
    if math.sqrt(sum(x*x for x in attitude)) >= 1.0:
        raise ValueError("Initial MRP should be within the nonsingular principal set")
    if math.sqrt(sum(x*x for x in rate)) > 0.2:
        raise ValueError("Unreasonably large initial body rate for this uncontrolled benchmark")
    if not math.isfinite(step_s) or not (
        float(config["minimum_sample_step_s"]) <= step_s <= float(config["maximum_sample_step_s"])
    ):
        raise ValueError(
            "ADCS 01 requires dynamics step between "
            f"{config['minimum_sample_step_s']} and {config['maximum_sample_step_s']} s; "
            "use --step-s 0.5"
        )
    for key in ("feedback_gain_K_Nm", "rate_gain_P_Nm_s"):
        value = float(config[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be positive and finite")
    if float(config["integral_gain_Ki"]) >= 0:
        raise ValueError("ADCS 01 deliberately disables integral action (Ki < 0)")
    for key in ("readiness_boresight_max_deg", "readiness_tracking_rate_max_rad_s"):
        value = float(config[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be positive and finite")


def attach(
    sim,
    task: str,
    spacecraft,
    target,
    orbit_cfg: dict,
    step_s: float,
) -> ADCSComponents:
    raw = CONFIG.read_bytes()
    config = json.loads(raw)
    validate_adcs_config(config, step_s)
    sha = hashlib.sha256(raw).hexdigest()

    spacecraft.hub.sigma_BNInit = [
        [v] for v in _triplet("initial_sigma_BN_mrp", config["initial_sigma_BN_mrp"])
    ]
    spacecraft.hub.omega_BN_BInit = [
        [v] for v in _triplet("initial_omega_BN_B_rad_s", config["initial_omega_BN_B_rad_s"])
    ]

    torque_effector = extForceTorque.ExtForceTorque()
    torque_effector.ModelTag = "ADCS_IdealExternalTorque"
    spacecraft.addDynamicEffector(torque_effector)
    sim.AddModelToTask(task, torque_effector, ModelPriority=90)

    # A zero-noise NavAtt/NavTrans reading is a declared simplification.
    navigation = simpleNav.SimpleNav()
    navigation.ModelTag = "ADCS_TruthLikeNavigation"
    navigation.scStateInMsg.subscribeTo(spacecraft.scStateOutMsg)
    sim.AddModelToTask(task, navigation, ModelPriority=120)

    guidance = locationPointing.locationPointing()
    guidance.ModelTag = "ADCS_GroundLocationPointing"
    guidance.pHat_B = _triplet("instrument_boresight_B", config["instrument_boresight_B"])
    guidance.useBoresightRateDamping = 1
    guidance.scAttInMsg.subscribeTo(navigation.attOutMsg)
    guidance.scTransInMsg.subscribeTo(navigation.transOutMsg)
    guidance.locationInMsg.subscribeTo(target.currentGroundStateOutMsg)
    sim.AddModelToTask(task, guidance, ModelPriority=99)

    controller = mrpFeedback.mrpFeedback()
    controller.ModelTag = "ADCS_MRP_Feedback"
    controller.K = float(config["feedback_gain_K_Nm"])
    controller.P = float(config["rate_gain_P_Nm_s"])
    controller.Ki = float(config["integral_gain_Ki"])
    controller.guidInMsg.subscribeTo(guidance.attGuidOutMsg)

    diagonal = _triplet("hub_inertia_diag_kg_m2", orbit_cfg["hub_inertia_diag_kg_m2"])
    if any(v <= 0 for v in diagonal):
        raise ValueError("Hub inertia must be positive")
    inertia = [diagonal[0], 0.0, 0.0,
               0.0, diagonal[1], 0.0,
               0.0, 0.0, diagonal[2]]
    vehicle_cfg = messaging.VehicleConfigMsg().write(
        messaging.VehicleConfigMsgPayload(ISCPntB_B=inertia)
    )
    controller.vehConfigInMsg.subscribeTo(vehicle_cfg)
    sim.AddModelToTask(task, controller, ModelPriority=98)

    # Closed loop: control moment affects the integrated physical orientation
    # on the next spacecraft dynamics update. No hardware torque limit yet.
    torque_effector.cmdTorqueInMsg.subscribeTo(controller.cmdTorqueOutMsg)

    guid_rec = guidance.attGuidOutMsg.recorder()
    torque_rec = controller.cmdTorqueOutMsg.recorder()
    nav_rec = navigation.attOutMsg.recorder()
    for recorder in (guid_rec, torque_rec, nav_rec):
        sim.AddModelToTask(task, recorder, ModelPriority=0)

    return ADCSComponents(
        config=config,
        config_sha256=sha,
        guidance_recorder=guid_rec,
        torque_recorder=torque_rec,
        nav_recorder=nav_rec,
        guidance_msg=guidance.attGuidOutMsg,
    )

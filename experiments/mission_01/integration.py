"""Connect synthetic exposure, partitioned storage and geometric downlink.

Official Basilisk 2.12.2 modules:
simpleInstrumentController -> simpleInstrument -> partitionedStorageUnit
                              storageUnit <-> spaceToGroundTransmitter
                                    station GroundLocation access
The controller reads REAL locationPointing guidance of physically rotating
spacecraft. Perfect actuator/nav and fixed-rate link are still assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from Basilisk.fswAlgorithms import simpleInstrumentController
from Basilisk.simulation import (
    groundLocation, simpleInstrument, partitionedStorageUnit,
    spaceToGroundTransmitter,
)


CONFIG = Path(__file__).with_name("config.json")


@dataclass
class MissionComponents:
    config: dict
    sha256: str
    station_access_rec: object
    station_ground_rec: object
    capture_command_rec: object
    instrument_data_rec: object
    storage_rec: object
    transmitter_rec: object


def validate_config(config: dict, step_s: float) -> None:
    if not str(config.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("Mission inputs must identify the synthetic nature of data")
    capture, storage, downlink = (
        config["capture"], config["storage"], config["downlink"]
    )
    def pos_int(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value
    bits = 8 * pos_int(capture["product_bytes"], "product_bytes")
    capacity_bits = 8 * pos_int(storage["capacity_bytes"], "capacity_bytes")
    packet_bits = 8 * pos_int(downlink["packet_bytes"], "packet_bytes")
    if not isinstance(capture["maximum_products_per_run"], int) or capture["maximum_products_per_run"] != 1:
        raise ValueError("Mission 01 currently supports only ONE synthetic product per whole run")
    if storage["initial_bytes"] != 0 or capacity_bits < bits:
        raise ValueError("Mission 01 needs empty storage large enough for its single product")
    if packet_bits > bits or bits % packet_bits:
        raise ValueError("Packet size must divide product size for traceable accounting")
    if not 0 < float(config["capture"]["maximum_attitude_mrp_error"]) < 1:
        raise ValueError("Invalid dimensionless MRP tolerance")
    if not 0 < float(capture["maximum_rate_error_rad_s"]) < 1:
        raise ValueError("Invalid attitude rate tolerance")
    if not math.isclose(float(capture["assumed_exposure_duration_s"]), step_s,
                        rel_tol=0, abs_tol=1e-12):
        raise ValueError("This first-order instrument assumes one product per physical time step")
    if not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("Invalid step_s")
    rate = float(downlink["rate_bits_per_s"])
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Radio rate must be positive and finite")
    station = downlink["ground_station"]
    latitude, longitude, elevation = (
        float(station["latitude_deg"]), float(station["longitude_deg"]),
        float(station["minimum_elevation_deg"])
    )
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180
            and 0 <= elevation < 90 and float(station["altitude_m"]) >= 0):
        raise ValueError("Invalid synthetic station coordinates or mask")
    if not str(storage["partition_name"]) == str(capture["product_name"]):
        raise ValueError("Storage partition must match instrument data name")
    if len(str(capture["product_name"])) >= 100:
        raise ValueError("Short data partition name required")


def attach(sim, task: str, spacecraft, planet_msg, earth_radius_m: float,
           target_access_msg, pointing_guidance_msg, step_s: float) -> MissionComponents:
    raw = CONFIG.read_bytes()
    cfg = json.loads(raw)
    validate_config(cfg, step_s)
    capture, storage_cfg, radio_cfg = cfg["capture"], cfg["storage"], cfg["downlink"]
    station_cfg = radio_cfg["ground_station"]

    station = groundLocation.GroundLocation()
    station.ModelTag = str(station_cfg["name"])
    station.planetRadius = float(earth_radius_m)
    station.minimumElevation = math.radians(float(station_cfg["minimum_elevation_deg"]))
    station.maximumRange = float(station_cfg["maximum_range_m"])
    station.specifyLocation(
        math.radians(float(station_cfg["latitude_deg"])),
        math.radians(float(station_cfg["longitude_deg"])),
        float(station_cfg["altitude_m"]),
    )
    station.addSpacecraftToModel(spacecraft.scStateOutMsg)
    station.planetInMsg.subscribeTo(planet_msg)
    sim.AddModelToTask(task, station, ModelPriority=100)

    controller = simpleInstrumentController.simpleInstrumentController()
    controller.ModelTag = "Mission_RealPointing_ExposureGate"
    controller.attErrTolerance = float(capture["maximum_attitude_mrp_error"])
    controller.useRateTolerance = 1
    controller.rateErrTolerance = float(capture["maximum_rate_error_rad_s"])
    controller.locationAccessInMsg.subscribeTo(target_access_msg)
    controller.attGuidInMsg.subscribeTo(pointing_guidance_msg)
    sim.AddModelToTask(task, controller, ModelPriority=97)

    instrument = simpleInstrument.SimpleInstrument()
    instrument.ModelTag = "Mission_SyntheticInstrument"
    instrument.nodeDataName = str(capture["product_name"])
    instrument.nodeBaudRate = float(capture["product_bytes"])*8/step_s
    instrument.nodeStatusInMsg.subscribeTo(controller.deviceCmdOutMsg)
    sim.AddModelToTask(task, instrument, ModelPriority=90)

    transmitter = spaceToGroundTransmitter.SpaceToGroundTransmitter()
    transmitter.ModelTag = "Mission_FixedRateGroundTransmitter"
    transmitter.nodeBaudRate = -float(radio_cfg["rate_bits_per_s"])
    transmitter.packetSize = -8*float(radio_cfg["packet_bytes"])
    transmitter.numBuffers = 1
    transmitter.addAccessMsgToTransmitter(station.accessOutMsgs[0])
    sim.AddModelToTask(task, transmitter, ModelPriority=96)

    storage = partitionedStorageUnit.PartitionedStorageUnit()
    storage.ModelTag = "Mission_PartitionedOnboardMemory"
    storage.storageCapacity = 8*float(storage_cfg["capacity_bytes"])
    storage.addDataNodeToModel(instrument.nodeDataOutMsg)
    storage.addDataNodeToModel(transmitter.nodeDataOutMsg)
    storage.addPartition(str(storage_cfg["partition_name"]))
    sim.AddModelToTask(task, storage, ModelPriority=89)
    transmitter.addStorageUnitToTransmitter(storage.storageUnitDataOutMsg)

    recorders = (
        station.accessOutMsgs[0].recorder(),
        station.currentGroundStateOutMsg.recorder(),
        controller.deviceCmdOutMsg.recorder(),
        instrument.nodeDataOutMsg.recorder(),
        storage.storageUnitDataOutMsg.recorder(),
        transmitter.nodeDataOutMsg.recorder(),
    )
    for recorder in recorders:
        sim.AddModelToTask(task, recorder, ModelPriority=0)

    return MissionComponents(
        config=cfg,
        sha256=hashlib.sha256(raw).hexdigest(),
        station_access_rec=recorders[0],
        station_ground_rec=recorders[1],
        capture_command_rec=recorders[2],
        instrument_data_rec=recorders[3],
        storage_rec=recorders[4],
        transmitter_rec=recorders[5],
    )

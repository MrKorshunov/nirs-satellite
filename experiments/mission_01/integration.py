"""Connect synthetic exposure, partitioned storage and geometric downlink.

Official Basilisk 2.12.2 modules:
simpleInstrumentController -> simpleInstrument -> partitionedStorageUnit
                              storageUnit <-> spaceToGroundTransmitter
                                    station GroundLocation access
The controller reads REAL locationPointing guidance of physically rotating
spacecraft. Perfect actuator/nav and fixed-rate link are still assumptions.
"""
from __future__ import annotations

from nirs_satellite.input_paths import input_path

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from experiments.mission_01.parameters import validate_config

from Basilisk.fswAlgorithms import simpleInstrumentController
from Basilisk.simulation import (
    groundLocation, simpleInstrument, partitionedStorageUnit,
    spaceToGroundTransmitter,
)


CONFIG = input_path("camera_storage_radio")
CONFIG_SLOW = input_path("camera_storage_radio_slow")
CONFIG_BY_PROFILE = {"nominal": CONFIG, "slow_link": CONFIG_SLOW}


@dataclass
class MissionComponents:
    config: dict
    config_path: Path
    sha256: str
    station_access_rec: object
    station_ground_rec: object
    capture_command_rec: object
    instrument_data_rec: object
    storage_rec: object
    transmitter_rec: object
    capture_command_msg: object
    transmitter_data_msg: object
    storage_status_msg: object
    controller_model: object
    instrument_model: object
    transmitter_model: object
    storage_model: object
    station_model: object


def attach(sim, task: str, spacecraft, planet_msg, earth_radius_m: float,
           target_access_msg, pointing_guidance_msg, step_s: float,
           profile: str = "nominal") -> MissionComponents:
    if profile not in CONFIG_BY_PROFILE:
        raise ValueError("Unknown synthetic radio profile")
    config_path = CONFIG_BY_PROFILE[profile]
    raw = config_path.read_bytes()
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
        config_path=config_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        station_access_rec=recorders[0],
        station_ground_rec=recorders[1],
        capture_command_rec=recorders[2],
        instrument_data_rec=recorders[3],
        storage_rec=recorders[4],
        transmitter_rec=recorders[5],
        capture_command_msg=controller.deviceCmdOutMsg,
        transmitter_data_msg=transmitter.nodeDataOutMsg,
        storage_status_msg=storage.storageUnitDataOutMsg,
        controller_model=controller,
        instrument_model=instrument,
        transmitter_model=transmitter,
        storage_model=storage,
        station_model=station,
    )

"""Attach Basilisk partitionedStorageUnit to the synthetic imager data stream."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from Basilisk.simulation import partitionedStorageUnit

CONFIG = Path(__file__).with_name("config.json")


def attach(sim, task, instrument_data_msg, instrument_data_name):
    raw = CONFIG.read_bytes()
    config = json.loads(raw)
    if not str(config.get("provenance", "")).startswith("SYNTHETIC"):
        raise ValueError("Storage 01 requires synthetic provenance")
    cap = config["storage_capacity_bytes"]
    if not isinstance(cap, int) or cap <= 0:
        raise ValueError("storage_capacity_bytes must be a positive integer")
    if config["initial_occupancy_bytes"] != 0:
        raise ValueError("Storage 01 baseline requires empty initial buffer")
    if str(config["instrument_partition"]) != str(instrument_data_name):
        raise ValueError("Storage partition name must match Basilisk dataName")
    memory = partitionedStorageUnit.PartitionedStorageUnit()
    memory.ModelTag = "NIRS_Basilisk_PartitionedStorage"
    memory.storageCapacity = cap * 8  # bits
    memory.addPartition(instrument_data_name)
    memory.addDataNodeToModel(instrument_data_msg)
    sim.AddModelToTask(task, memory, ModelPriority=85)  # after instrument at 90
    record = memory.storageUnitDataOutMsg.recorder()
    sim.AddModelToTask(task, record, ModelPriority=0)
    return config, hashlib.sha256(raw).hexdigest(), record

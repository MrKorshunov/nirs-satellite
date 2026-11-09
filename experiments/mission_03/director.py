"""Basilisk SysModel: actual on-board task sequencing and battery mode interlock.

Runs INSIDE the same Basilisk dynamics task (at low priority, after sensor,
storage, battery). No repeated ExecuteSimulation, no native Vizard recorder
reset, no separate simulated or guessed spacecraft state.
"""
from __future__ import annotations

from Basilisk.architecture import sysModel
from Basilisk.utilities import macros

from experiments.mission_03.logic import permitted


class PhysicalMissionDirector(sysModel.SysModel):
    def __init__(self, *, cfg, data, target, power, product_bits,
                 nominal_att_tol, nominal_rate_tol, nominal_radio_bps):
        super().__init__()
        self.ModelTag = "NIRS_Mission03_PhysicalDirector"
        self.cfg = cfg
        self.data = data
        self.target = target
        self.power = power
        self.product_bits = float(product_bits)
        self.nominal_att_tol = float(nominal_att_tol)
        self.nominal_rate_tol = float(nominal_rate_tol)
        self.nominal_radio_bps = float(nominal_radio_bps)
        self.phase = 0
        self.switch_t = None
        self.events = [{"t_s": 0., "event": "target_assigned",
                        "task": cfg["tasks"][0]["id"]}]
        self.allowed = True
        self.granted_segments = []
        self._next_control_ns = 0
        self._last_capture_ns = None
        self._old_armed = None
        self._old_tx = None

    def Reset(self, CurrentSimNanos):
        self._next_control_ns = 0
        self._last_capture_ns = None
        return super().Reset(CurrentSimNanos)

    def UpdateState(self, CurrentSimNanos):
        t = float(CurrentSimNanos)*macros.NANO2SEC
        # Read physical instrument output AFTER the camera's Basilisk update.
        # This same message is consumed by PartitionedStorageUnit.
        produced = float(self.data.instrument_model.nodeDataOutMsg.read().baudRate)
        if produced > 0 and CurrentSimNanos != self._last_capture_ns:
            if self.phase >= len(self.cfg["tasks"]):
                raise AssertionError("Unexpected additional camera capture")
            task = self.cfg["tasks"][self.phase]
            self.events.append({"t_s": t, "event": "captured",
                                "task": task["id"], "produced_bits": self.product_bits})
            print(f"MISSION03 PHYSICAL CAPTURE: {task['id']} at t={t:.1f}s", flush=True)
            self._last_capture_ns = CurrentSimNanos
            if self.phase == 0:
                next_target = self.cfg["tasks"][1]
                # Basilisk's documented switch/reset technique. Physical
                # Spacecraft, reaction wheels, battery and memory are untouched.
                self.target.specifyLocation(
                    macros.D2R * float(next_target["lat_deg"]),
                    macros.D2R * float(next_target["lon_deg"]),
                    float(next_target["altitude_m"]),
                )
                self.target.minimumElevation=macros.D2R*float(next_target["minimum_elevation_deg"])
                self.target.maximumRange=float(next_target["maximum_range_m"])
                self.data.instrument_model.nodeDataName=next_target["id"]
                self.data.controller_model.imaged=0
                self.phase=1
                self.switch_t=t
                self.events.append({"t_s":t, "event":"retarget",
                                    "from":task["id"],"to":next_target["id"]})
                print(f"MISSION03 PHYSICAL RETARGET: {task['id']} -> "
                      f"{next_target['id']} at t={t:.1f}s", flush=True)
            elif self.phase == 1:
                self.phase=2

        # Power mode commands operate at a slower controlled cadence while
        # the physical propagator and recorder continue at 0.5 s.
        if CurrentSimNanos < self._next_control_ns:
            return
        self._next_control_ns = CurrentSimNanos + macros.sec2nano(
            float(self.cfg["control_step_s"]))
        energy_wh=float(self.power.battery_model.batPowerOutMsg.read().storageLevel)/3600.
        grant=permitted(
            energy_wh,reserve_wh=float(self.cfg["reserve_wh"]),
            guard_wh=float(self.cfg["reserve_guard_wh"]),
            hysteresis_wh=float(self.cfg["battery_reenable_hysteresis_wh"]),
            previously_permitted=self.allowed)
        if grant != self.allowed:
            self.events.append({"t_s":t, "event":"power_enabled" if grant else "power_safe_mode",
                                "battery_wh":round(energy_wh,6)})
        self.allowed=grant
        self.granted_segments.append(grant)
        camera_on=grant and self.phase<len(self.cfg["tasks"])
        storage_bits=float(self.data.storage_model.storageUnitDataOutMsg.read().storageLevel)
        minimum_bits = abs(float(self.data.transmitter_model.packetSize))
        station_access=bool(self.data.station_model.accessOutMsgs[0].read().hasAccess)
        radio_on=grant and station_access and storage_bits>=minimum_bits
        self.data.controller_model.attErrTolerance=(
            self.nominal_att_tol if camera_on else -1.0)
        self.data.controller_model.rateErrTolerance=(
            self.nominal_rate_tol if camera_on else -1.0)
        self.data.transmitter_model.nodeBaudRate=(
            -self.nominal_radio_bps if radio_on else 0.0)
        self.power.imaging_sink.powerStatus=1 if camera_on else 0
        self.power.transmitter_sink.powerStatus=1 if radio_on else 0
        if camera_on!=self._old_armed:
            self.events.append({"t_s":t,"event":"camera_armed" if camera_on else "camera_off"})
            self._old_armed=camera_on
        if radio_on!=self._old_tx:
            self.events.append({"t_s":t,"event":"radio_on" if radio_on else "radio_off"})
            self._old_tx=radio_on

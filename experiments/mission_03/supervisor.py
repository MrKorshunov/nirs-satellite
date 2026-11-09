"""Mission 03 operational supervisor: no new orbit or wheel physics.

This module only translates observed Basilisk data events and battery energy
into discrete target reconfiguration / camera-radio enable decisions.
"""
from __future__ import annotations
from dataclasses import dataclass,field
import math

@dataclass
class Supervisor:
    target_ids: tuple[str,...]
    energy_reserve_wh: float
    active_index: int = 0
    seen_captures: int = 0
    safe_mode: bool = False
    events: list[dict] = field(default_factory=list)

    def update(self,t_s:float,positive_samples:int,energy_wh:float,guard_wh:float=0.0)->tuple[bool,bool]:
        """Return (switch_to_next_target, allow_hardware).

        Sample counts are from actual Basilisk SimpleInstrument DataNodeUsage
        telemetry, not requested capture commands. No capture is credited before
        the data stream is observed. Safety margin avoids a command issued at
        the exact reserve threshold.
        """
        if not all(math.isfinite(x) for x in (t_s,energy_wh,guard_wh)):
            raise ValueError("Nonfinite control telemetry")
        if positive_samples<self.seen_captures:
            raise ValueError("Capture telemetry counter unexpectedly decreased")
        if positive_samples>len(self.target_ids):
            raise AssertionError("Excess physical products generated")
        if positive_samples-self.seen_captures>1:
            raise AssertionError("More than one image generated between controller decisions")
        switch=False
        if positive_samples>self.seen_captures:
            if self.active_index!=self.seen_captures:
                raise AssertionError("Captured product disagrees with active physical target")
            self.events.append({"t_s":t_s,"event":"captured_physical","target_id":self.target_ids[self.active_index]})
            self.seen_captures=positive_samples
            if self.seen_captures<len(self.target_ids):
                self.active_index+=1
                switch=True
                self.events.append({"t_s":t_s,"event":"retarget_command","target_id":self.target_ids[self.active_index]})
        low=energy_wh<=self.energy_reserve_wh+guard_wh
        if low!=self.safe_mode:
            self.events.append({"t_s":t_s,"event":"power_safe_on" if low else "power_safe_off",
                                "energy_wh":energy_wh})
        self.safe_mode=low
        return switch,not low

    @property
    def finished_capturing(self)->bool:
        return self.seen_captures==len(self.target_ids)

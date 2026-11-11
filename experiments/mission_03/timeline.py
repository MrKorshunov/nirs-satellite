"""Non-optimizing execution-plan contract and plan/actual comparisons.

A schedule is a caller-chosen set of time windows. The executor NEVER
reorders tasks, chooses start times or searches. All model times are elapsed
seconds from epoch_utc if one is supplied.
"""
from __future__ import annotations
import math

def task_window(task:dict)->tuple[float,float]:
    start=float(task.get("planned_start_s",task.get("release_s",0)))
    stop=float(task.get("planned_end_s",task["deadline_s"]))
    return start,stop

def within_task_window(task:dict,t:float)->bool:
    start,stop=task_window(task)
    return max(start,float(task.get("release_s",0)))<=t<=min(stop,float(task["deadline_s"]))

def radio_window_open(cfg:dict,t:float)->bool:
    windows=cfg.get("downlink_windows")
    if windows is None:
        return True  # absent means only physical station/power limits apply
    return any(float(v["start_s"])<=t<float(v["end_s"]) for v in windows)

def validate_windows(cfg:dict,step_s:float)->None:
    for task in cfg["tasks"]:
        start,stop=task_window(task)
        release=float(task.get("release_s",0))
        deadline=float(task["deadline_s"])
        if not all(math.isfinite(v) for v in (start,stop,release,deadline)):
            raise ValueError("Nonfinite planned task window")
        if not 0<=release<=start<stop<=deadline:
            raise ValueError("Planned camera window must fit release/deadline")
        if not math.isclose(start/step_s,round(start/step_s),abs_tol=1e-8):
            raise ValueError("Camera planned start must align physical time step")
        if not math.isclose(stop/step_s,round(stop/step_s),abs_tol=1e-8):
            raise ValueError("Camera planned end must align physical time step")
    windows=cfg.get("downlink_windows")
    if windows is None:
        return
    if not isinstance(windows,list):
        raise ValueError("downlink_windows must be a list")
    previous=-1.0
    for win in windows:
        start=float(win["start_s"])
        end=float(win["end_s"])
        if not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end:
            raise ValueError("Invalid downlink window")
        if start<previous-1e-9:
            raise ValueError("Downlink windows must be nonoverlapping and ordered")
        previous=end
        if not math.isclose(start/step_s,round(start/step_s),abs_tol=1e-8):
            raise ValueError("Downlink start must align physical time step")
        if not math.isclose(end/step_s,round(end/step_s),abs_tol=1e-8):
            raise ValueError("Downlink end must align physical time step")

def schedule_task_record(task:dict,capture_times:list[float],status:str,
                         reason:str|None)->dict:
    start,end=task_window(task)
    first=min(capture_times) if capture_times else None
    last=max(capture_times) if capture_times else None
    return {
        "planned_start_s":start,
        "planned_end_s":end,
        "actual_first_capture_s":first,
        "actual_last_capture_s":last,
        "actual_first_capture_delay_s":None if first is None else first-start,
        "last_capture_vs_planned_end_s":None if last is None else last-end,
        "last_capture_within_plan":last is not None and last<=end+1e-8,
        "status":status,
        "reason":reason,
    }

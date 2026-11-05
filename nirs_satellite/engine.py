"""Discrete-event simulation; no orbital or energy dynamics yet."""
from dataclasses import dataclass
from .model import Scenario, Task, validate


@dataclass
class Product:
    task: Task
    remaining_bytes: int
    captured_at_s: int


@dataclass
class Result:
    policy: str
    completed_on_time: set[str]
    delivered_late: set[str]
    rejected_memory: set[str]
    undelivered: set[str]
    events: list[dict]
    memory_trace: list[dict]
    delivered_bytes: int
    max_memory_bytes: int
    task_count: int
    weighted_completion: float

    def summary(self) -> dict:
        return {
            "policy": self.policy,
            "completed_on_time": sorted(self.completed_on_time),
            "delivered_late": sorted(self.delivered_late),
            "rejected_memory": sorted(self.rejected_memory),
            "undelivered": sorted(self.undelivered),
            "task_count": self.task_count,
            "k_weighted_on_time": round(self.weighted_completion, 6),
            "delivered_bytes": self.delivered_bytes,
            "max_memory_bytes": self.max_memory_bytes,
        }


def simulate(scenario: Scenario, policy: str = "fifo") -> Result:
    """Replay fixed captures and schedule downlink only.

    A product occupies its full stored size until entirely downlinked, even if
    transmission is partial. Capture and downlink cannot operate simultaneously.
    Contacts are windows of opportunity, not obligations to transmit.
    Deadline is inclusive; a finished product after it is delivered late.
    """
    validate(scenario)
    if policy not in {"fifo", "edf"}:
        raise ValueError("Downlink policy must be 'fifo' or 'edf'")

    tasks = scenario.tasks
    boundaries = {0}
    for task in tasks:
        boundaries.update((task.capture_start_s, task.capture_end_s))
    for contact in scenario.contacts:
        boundaries.update((contact.start_s, contact.end_s))
    times = sorted(boundaries)
    queue: list[Product] = []
    completed: set[str] = set()
    late: set[str] = set()
    rejected: set[str] = set()
    events: list[dict] = []
    trace: list[dict] = []
    stored_bytes = 0
    peak = 0
    sent_bytes = 0

    def active_contact(t: int):
        return next((c for c in scenario.contacts if c.start_s <= t < c.end_s), None)

    for k, t in enumerate(times):
        # Image data appear at the *end* of the capture operation.
        for task in sorted((x for x in tasks if x.capture_end_s == t), key=lambda x: x.id):
            if stored_bytes + task.volume_bytes > scenario.memory_capacity_bytes:
                rejected.add(task.id)
                events.append({"time_s": t, "type": "capture_rejected", "task": task.id,
                               "bytes": task.volume_bytes, "reason": "memory_full"})
            else:
                queue.append(Product(task, task.volume_bytes, t))
                stored_bytes += task.volume_bytes
                peak = max(peak, stored_bytes)
                events.append({"time_s": t, "type": "capture_finished", "task": task.id,
                               "bytes": task.volume_bytes, "reason": ""})

        trace.append({"time_s": t, "memory_bytes": stored_bytes})
        if k + 1 == len(times):
            continue
        interval_end = times[k + 1]
        capturing = any(x.capture_start_s <= t < x.capture_end_s for x in tasks)
        contact = active_contact(t)
        if capturing or contact is None:
            continue

        current_time = t
        while queue and current_time < interval_end:
            if policy == "fifo":
                product = min(queue, key=lambda x: (x.captured_at_s, x.task.id))
            else:
                product = min(queue, key=lambda x: (x.task.deadline_s, x.captured_at_s, x.task.id))
            remaining_interval = interval_end - current_time
            capacity = remaining_interval * contact.rate_bytes_per_s
            transferred = min(product.remaining_bytes, capacity)
            if transferred == 0:
                break
            start_time = current_time
            end_time = start_time + transferred / contact.rate_bytes_per_s
            product.remaining_bytes -= transferred
            sent_bytes += transferred
            events.append({"time_s": start_time, "end_s": end_time,
                           "type": "downlink", "task": product.task.id,
                           "bytes": transferred, "reason": ""})
            current_time = end_time
            if product.remaining_bytes == 0:
                queue.remove(product)
                stored_bytes -= product.task.volume_bytes
                if end_time <= product.task.deadline_s:
                    completed.add(product.task.id)
                    result_type = "delivered_on_time"
                else:
                    late.add(product.task.id)
                    result_type = "delivered_late"
                events.append({"time_s": end_time, "type": result_type,
                               "task": product.task.id, "bytes": product.task.volume_bytes,
                               "reason": ""})
                trace.append({"time_s": end_time, "memory_bytes": stored_bytes})

    undelivered = {p.task.id for p in queue}
    # Rejected captures do not produce a stored product.
    total_weight = sum(task.priority for task in tasks)
    success_weight = sum(task.priority for task in tasks if task.id in completed)
    return Result(policy, completed, late, rejected, undelivered, events, trace,
                  sent_bytes, peak, len(tasks),
                  success_weight / total_weight if total_weight else 0.0)

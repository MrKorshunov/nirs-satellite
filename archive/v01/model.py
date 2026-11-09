"""Input data: times are seconds, sizes bytes, link rates bytes per second."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    capture_start_s: int
    capture_end_s: int
    volume_bytes: int
    deadline_s: int
    priority: int = 1


@dataclass(frozen=True)
class Contact:
    start_s: int
    end_s: int
    rate_bytes_per_s: int


@dataclass(frozen=True)
class Scenario:
    memory_capacity_bytes: int
    tasks: tuple[Task, ...]
    contacts: tuple[Contact, ...]


def validate(scenario: Scenario) -> None:
    if scenario.memory_capacity_bytes <= 0:
        raise ValueError("Memory capacity must be positive")
    if len({task.id for task in scenario.tasks}) != len(scenario.tasks):
        raise ValueError("Task ids must be unique")
    for task in scenario.tasks:
        if not task.id.strip() or task.capture_start_s < 0:
            raise ValueError("Invalid task id or start time")
        if not (task.capture_start_s < task.capture_end_s <= task.deadline_s):
            raise ValueError(f"Invalid task times: {task.id}")
        if task.volume_bytes <= 0 or task.priority <= 0:
            raise ValueError(f"Invalid task volume or priority: {task.id}")
    for contact in scenario.contacts:
        if not (0 <= contact.start_s < contact.end_s):
            raise ValueError("Invalid contact times")
        if contact.rate_bytes_per_s <= 0:
            raise ValueError("Contact rate must be positive")
    captures = sorted(scenario.tasks, key=lambda t: t.capture_start_s)
    if any(a.capture_end_s > b.capture_start_s for a, b in zip(captures, captures[1:])):
        raise ValueError("Planned captures cannot overlap for one satellite")
    contacts = sorted(scenario.contacts, key=lambda c: c.start_s)
    if any(a.end_s > b.start_s for a, b in zip(contacts, contacts[1:])):
        raise ValueError("Contact windows cannot overlap for one radio")

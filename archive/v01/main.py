"""Command-line demo: python main.py [input.json] [output-directory]."""
import csv
import json
import sys
from pathlib import Path
from archive.v01.model import Contact, Scenario, Task
from archive.v01.engine import simulate


def load_scenario(path: Path) -> Scenario:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Scenario(
        memory_capacity_bytes=data["memory_capacity_bytes"],
        tasks=tuple(Task(**t) for t in data["tasks"]),
        contacts=tuple(Contact(**c) for c in data["contacts"]),
    )


def export_csv(path: Path, records: list[dict]) -> None:
    if not records:
        return
    cols = list(dict.fromkeys(key for record in records for key in record))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "demo.json"
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[2] / "results" / "legacy_v01"
    output.mkdir(parents=True, exist_ok=True)
    scenario = load_scenario(source)
    summaries = []
    for method in ("fifo", "edf"):
        result = simulate(scenario, method)
        summary = result.summary()
        summaries.append(summary)
        export_csv(output / f"events_{method}.csv", result.events)
        export_csv(output / f"memory_{method}.csv", result.memory_trace)
        print(f"{method.upper()}: K={summary['k_weighted_on_time']:.3f}, "
              f"on time={summary['completed_on_time']}, "
              f"rejected={summary['rejected_memory']}")
    (output / "comparison.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    export_csv(output / "comparison.csv", summaries)
    print(f"Outputs saved in: {output.resolve()}")


if __name__ == "__main__":
    main()

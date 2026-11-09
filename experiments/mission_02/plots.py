"""Optional figures for Mission 02 reproducible simulation outputs."""
from __future__ import annotations

import csv
from pathlib import Path


def render_summary(folder: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    import json
    summaries = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
    policies = [x["policy"] for x in summaries]
    scores = [x["weighted_on_time_fraction"] for x in summaries]
    images = []

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(policies, scores)
    ax.set(xlabel="Scheduling policy", ylabel="Weighted fraction delivered by deadline",
           title="Mission 02: same Basilisk orbit and tasks, different policies",
           ylim=(0, 1))
    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width()/2, score + 0.02,
                f"{score:.3f}", ha="center", va="bottom")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(folder / "policy_comparison.png", dpi=160)
    plt.close(fig)
    images.append("policy_comparison.png")

    for field, y_label, out_name in (
        ("storage_bits", "Stored bits", "memory_over_time.png"),
        ("battery_wh", "Battery energy (Wh)", "battery_over_time.png"),
    ):
        fig, ax = plt.subplots(figsize=(9, 4))
        for policy in policies:
            with (folder / f"{policy}_states.csv").open(
                    newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            ax.plot([float(x["time_s"])/60 for x in rows],
                    [float(x[field]) for x in rows], label=policy)
        ax.set(xlabel="Synthetic elapsed time (min)", ylabel=y_label,
               title=f"Mission 02: {y_label} under alternative schedules")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(folder / out_name, dpi=160)
        plt.close(fig)
        images.append(out_name)
    return images

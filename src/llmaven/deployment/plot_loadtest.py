"""Plot latency comparison from load test results CSV."""

import csv
from pathlib import Path

import matplotlib.pyplot as plt


def plot_latency_comparison(csv_path: str | Path) -> None:
    """Load CSV and plot latency percentiles for different worker counts."""
    csv_path = Path(csv_path)

    # Parse the CSV
    rows = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Group by workers
    data_by_workers = {}
    for row in rows:
        workers = int(row["workers"])
        data_by_workers[workers] = {
            "p50": float(row["latency_p50_ms"]),
            "p95": float(row["latency_p95_ms"]),
            "p99": float(row["latency_p99_ms"]),
            "avg": float(row["latency_avg_ms"]),
        }

    # Plot
    fig, ax = plt.subplots(figsize=(10, 6))

    workers_list = sorted(data_by_workers.keys())
    metrics = ["p50", "p95", "p99", "avg"]
    x = range(len(workers_list))
    width = 0.2

    for i, metric in enumerate(metrics):
        values = [data_by_workers[w][metric] for w in workers_list]
        bars = ax.bar(
            [xi + i * width for xi in x],
            values,
            width,
            label=metric.upper(),
        )
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height,
                f"{height:.0f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax.set_xlabel("Worker Count")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("Load Test Latency Comparison")
    ax.set_xticks([xi + width * 1.5 for xi in x])
    ax.set_xticklabels(workers_list)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    plt.savefig(csv_path.parent / "latency_comparison.png", dpi=150)
    print(f"Plot saved to {csv_path.parent / 'latency_comparison.png'}")


if __name__ == "__main__":
    import sys

    csv_file = sys.argv[1] if len(sys.argv) > 1 else "out.csv"
    plot_latency_comparison(csv_file)

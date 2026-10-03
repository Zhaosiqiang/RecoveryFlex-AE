#!/usr/bin/env python3
"""Build a compact graphical abstract from the frozen v3 results."""
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results/network_recovery_external_2012_2013_strict_v3"
OUT = ROOT / "figures/network_recovery_strict_v3"

def box(ax, xy, width, height, title, body, face, edge="#345"):
    x, y = xy
    patch = FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.012,rounding_size=0.02",
                           facecolor=face, edgecolor=edge, linewidth=1.2)
    ax.add_patch(patch)
    ax.text(x + width/2, y + height - 0.10, title, ha="center", va="top", fontsize=12, weight="bold", color="#17324d")
    ax.text(x + width/2, y + height/2 - 0.01, body, ha="center", va="center", fontsize=10,
            color="#17324d", linespacing=1.35)

def main():
    rows = pd.read_csv(RESULTS / "policy_rows.csv")
    rows = rows[rows.baseline_feasible == 1]
    means = rows.groupby(["site", "method"]).service_kw.mean().unstack()
    fig, ax = plt.subplots(figsize=(12, 5.2), dpi=180)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    box(ax, (0.03, 0.27), 0.23, 0.48, "Public profiles", "Ausgrid 2012–13\n365 raw dates → 219 complete dates\n10 frozen customer groups\n48 half-hour intervals", "#E8F3F8")
    box(ax, (0.385, 0.27), 0.23, 0.48, "AC–SOC benchmark", "OpenDSS IEEE 13-node feeder\n611.3 and 634.1 placements\nTwo 2-hour calls\nFull-horizon recovery + terminal SOC", "#F5EFE1")
    box(ax, (0.74, 0.27), 0.23, 0.48, "What the network changes", "634.1: LP − myopic\n+2.433 kW (95% CI 1.682–3.293)\n611.3: 0.000 kW\nEnergy-only replay: 0%", "#EAF4EA")
    for x1, x2 in ((0.27, 0.385), (0.62, 0.74)):
        ax.add_patch(FancyArrowPatch((x1, 0.51), (x2, 0.51), arrowstyle="-|>", mutation_scale=18,
                                     linewidth=1.8, color="#55758c"))
    ax.text(0.5, 0.10, "Offline screening result: recovery value is placement dependent; copper-plate offers are not deliverable without AC replay.",
            ha="center", va="center", fontsize=12, color="#17324d", weight="bold")
    fig.savefig(OUT / "fig5_graphical_abstract.pdf", bbox_inches="tight")
    fig.savefig(OUT / "fig5_graphical_abstract.png", bbox_inches="tight", dpi=320)
    plt.close(fig)

if __name__ == "__main__":
    main()

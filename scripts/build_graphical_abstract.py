#!/usr/bin/env python3
"""Build a compact graphical abstract from the frozen v4 results."""
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results/network_recovery_external_2012_2013_strict_v4"
OUT = ROOT / "figures/network_recovery_strict_v4"

def box(ax, xy, width, height, title, body, face, edge="#345"):
    x, y = xy
    patch = FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.012,rounding_size=0.02",
                           facecolor=face, edgecolor=edge, linewidth=1.2)
    ax.add_patch(patch)
    ax.text(x + width/2, y + height - 0.10, title, ha="center", va="top", fontsize=12, weight="bold", color="#17324d")
    ax.text(x + width/2, y + height/2 - 0.04, body, ha="center", va="center", fontsize=8.5,
            color="#17324d", linespacing=1.2)

def main():
    rows = pd.read_csv(RESULTS / "policy_rows.csv")
    rows = rows[rows.baseline_feasible == 1]
    means = rows.groupby(["site", "method"]).service_kw.mean().unstack()
    # Keep the journal-facing graphical abstract close to Elsevier's
    # recommended 2.5:1 canvas instead of relying on a tight bounding box,
    # which made the previous export unnecessarily panoramic.
    fig, ax = plt.subplots(figsize=(12, 4.8), dpi=180)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    box(ax, (0.03, 0.27), 0.23, 0.48, "Public profiles", "Ausgrid 2012–13\n365 raw dates →\n219 complete dates\n10 frozen customer groups\n48 half-hour intervals", "#E8F3F8")
    box(ax, (0.385, 0.27), 0.23, 0.48, "AC–SOC + look-ahead", "OpenDSS IEEE 13-node feeder\n611.3 and 634.1 placements\nTwo 2-hour calls\nAudited scalar-bound envelope\n+ H4 / H8 / H12 / H24", "#F5EFE1")
    box(ax, (0.74, 0.27), 0.23, 0.48, "What limits delivery", "634.1, 2 MWh: H4 = 45.0 kW\nH24 = 136.1 vs offline 138.5\n250 → 500 kWh:\n71.1 → 127.0\n95% descriptive threshold:\n83.2 kW", "#EAF4EA")
    for x1, x2 in ((0.27, 0.385), (0.62, 0.74)):
        ax.add_patch(FancyArrowPatch((x1, 0.51), (x2, 0.51), arrowstyle="-|>", mutation_scale=18,
                                     linewidth=1.8, color="#55758c"))
    ax.text(0.5, 0.10, "Offline screening: placement, capacity, and finite contract-information policy\nshape repeated-service delivery.",
            ha="center", va="center", fontsize=10.5, color="#17324d", weight="bold")
    fig.savefig(OUT / "fig5_graphical_abstract.pdf")
    fig.savefig(OUT / "fig5_graphical_abstract.png", dpi=320)
    plt.close(fig)

if __name__ == "__main__":
    main()

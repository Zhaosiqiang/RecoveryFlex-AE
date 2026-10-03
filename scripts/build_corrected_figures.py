#!/usr/bin/env python3
"""Build publication figures from the corrected, frozen experiment outputs."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.profile_bank import load_bank
import run_corrected_experiment as exp

OUT = ROOT / "figures" / "corrected_v1"
RESULTS = ROOT / "results" / "corrected_v1"
OUT.mkdir(parents=True, exist_ok=True)

COLORS = {"full_rearm": "#2166AC", "reserve_limited": "#B2182B", "train": "#5E3C99", "cal": "#E66101", "test": "#1B9E77"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
                     "legend.fontsize": 8, "figure.dpi": 140, "savefig.dpi": 320,
                     "axes.spines.top": False, "axes.spines.right": False})


def save(fig, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / f"{stem}.png", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def workflow() -> None:
    fig, ax = plt.subplots(figsize=(10.0, 2.3))
    ax.axis("off")
    boxes = [
        (0.03, "Measured\n48-point profiles", "#E8F1FB"),
        (0.23, "Train-only\nnormalization", "#F3E5F5"),
        (0.43, "AC snapshot\nreplay", "#E8F5E9"),
        (0.63, "SOC service–\nrecovery map", "#FFF3E0"),
        (0.83, "Held-out\nsequence contract", "#FDECEC"),
    ]
    for x, text, color in boxes:
        ax.text(x, 0.52, text, ha="center", va="center", fontsize=10, weight="bold",
                bbox=dict(boxstyle="round,pad=0.65", facecolor=color, edgecolor="#4D4D4D", linewidth=0.8),
                transform=ax.transAxes)
    for x in [0.13, 0.33, 0.53, 0.73]:
        ax.annotate("", xy=(x + 0.06, 0.52), xytext=(x, 0.52), xycoords=ax.transAxes,
                    arrowprops=dict(arrowstyle="->", lw=1.4, color="#4D4D4D"))
    ax.text(0.5, 0.08, "Every command is checked by terminal-power readback, voltage limits, line/transformer loading, and SOC bounds.",
            ha="center", va="center", fontsize=8.5, color="#404040", transform=ax.transAxes)
    save(fig, "fig1_corrected_workflow")


def sequence_capacity() -> None:
    x = pd.read_csv(RESULTS / "sequence_capacity.csv")
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for mode, label in [("full_rearm", "Full re-arm"), ("reserve_limited", "Reserve-limited recovery")]:
        g = x[x["mode"] == mode].groupby("events")["capacity_kw"]
        m = g.median()
        lo, hi = g.min(), g.max()
        ax.plot(m.index, m.values, marker="o", lw=2.2, color=COLORS[mode], label=label)
        ax.fill_between(m.index, lo.values, hi.values, color=COLORS[mode], alpha=0.16, linewidth=0)
    ax.set_xlabel("Repeated service events, M")
    ax.set_ylabel("Auditable service capacity (kW)")
    ax.set_xticks(range(1, 7))
    ax.set_ylim(0, 155)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.55, 1.03), borderaxespad=0.0)
    ax.text(0.02, 0.06, "Shaded range: test-day min–max", transform=ax.transAxes, fontsize=8, color="#555555")
    save(fig, "fig2_sequence_capacity")


def heldout_audit() -> None:
    rows = pd.read_csv(RESULTS / "corrected_experiment_rows.csv")
    g = rows[rows.phase == "single"].copy()
    fig, axs = plt.subplots(1, 2, figsize=(8.2, 3.5), gridspec_kw={"width_ratios": [1.0, 1.15]})
    order = ["train", "cal", "test"]
    axs[0].bar(order, [g[g.split == s].ok.mean() * 100 for s in order], color=[COLORS[s] for s in order], width=0.62)
    axs[0].axhline(95, color="#333333", lw=1.0, ls="--", label="95% selection threshold")
    axs[0].set_ylim(90, 100.5)
    axs[0].set_ylabel("Successful audited events (%)")
    axs[0].set_title("Frozen 140 kW offer")
    axs[0].legend(frameon=False, loc="lower left")
    axs[0].grid(axis="y", color="#E2E2E2", linewidth=0.6)
    for i, s in enumerate(order):
        axs[0].text(i, g[g.split == s].ok.mean() * 100 + 0.18, f"{g[g.split == s].ok.mean() * 100:.1f}", ha="center", fontsize=8)

    test = g[g.split == "test"]
    axs[1].scatter(test.vmin, test.vmax, c=test.ok.map({0: "#D6604D", 1: "#1B9E77"}), s=22, alpha=0.75, edgecolor="none")
    axs[1].axvline(0.95, color="#555555", lw=0.8, ls="--")
    axs[1].axhline(1.05, color="#555555", lw=0.8, ls="--")
    axs[1].set_xlim(0.992, 1.053)
    axs[1].set_ylim(1.038, 1.052)
    axs[1].set_xlabel("Minimum phase voltage (pu)")
    axs[1].set_ylabel("Maximum phase voltage (pu)")
    axs[1].set_title("Held-out AC audit")
    axs[1].grid(color="#E2E2E2", linewidth=0.6)
    save(fig, "fig3_heldout_ac_audit")


def soc_trace() -> None:
    p = 140.0
    initial = exp.SOC_INITIAL
    service_drop = p * exp.DT_H * exp.SERVICE_INTERVALS / (exp.ETA_DISCHARGE * exp.ENERGY_KWH)
    reserve_gain = exp.RECOVERY_RATIO * p * exp.DT_H * exp.RECOVERY_INTERVALS * exp.ETA_CHARGE / exp.ENERGY_KWH
    rearm_gain = exp._rearm_ratio(p) * p * exp.DT_H * exp.RECOVERY_INTERVALS * exp.ETA_CHARGE / exp.ENERGY_KWH
    reserve = [initial]
    rearm = [initial]
    for _ in range(6):
        reserve += [reserve[-1] - service_drop, min(1.0, reserve[-1] - service_drop + reserve_gain)]
        rearm += [rearm[-1] - service_drop, min(1.0, rearm[-1] - service_drop + rearm_gain)]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    x = np.arange(len(reserve))
    ax.step(x, rearm, where="post", color=COLORS["full_rearm"], lw=2.2, label="Full re-arm")
    ax.step(x, reserve, where="post", color=COLORS["reserve_limited"], lw=2.2, label="Reserve-limited")
    ax.axhline(exp.SOC_RESERVE, color="#555555", lw=1.0, ls="--", label="SOC reserve")
    ax.set_xticks(np.arange(0, 13, 2), ["0", "1", "2", "3", "4", "5", "6"])
    ax.set_xlabel("Event boundary (service → recovery pairs)")
    ax.set_ylabel("State of charge")
    ax.set_ylim(0, 0.86)
    ax.grid(axis="y", color="#E2E2E2", linewidth=0.6)
    ax.legend(frameon=False, ncol=3, loc="lower left")
    save(fig, "fig4_soc_state_trace")


def profile_splits() -> None:
    bank = load_bank(ROOT / "data/processed/ausgrid_profile_bank_v2.npz")
    day = 100
    t = np.arange(48) / 2
    fig, axs = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True)
    axs[0].plot(t, bank.load_kw[day, :, 0], color="#3B6FB6", lw=1.8, label="Load")
    axs[0].plot(t, bank.pv_kw[day, :, 0], color="#E69F00", lw=1.8, label="PV")
    axs[0].set_ylabel("Measured kW")
    axs[0].legend(frameon=False, ncol=2, loc="upper right")
    axs[0].set_title(f"Ausgrid interval trajectory ({bank.dates[day]})")
    counts = pd.Series(bank.split).value_counts().reindex(["train", "cal", "test"])
    axs[1].bar(counts.index, counts.values, color=[COLORS[s] for s in counts.index], width=0.6)
    axs[1].set_ylabel("Dates")
    axs[1].set_xlabel("Chronological split")
    for i, v in enumerate(counts.values): axs[1].text(i, v + 3, str(v), ha="center", fontsize=8)
    save(fig, "fig5_profile_bank_and_splits")


def realized_power_audit() -> None:
    bank = load_bank(ROOT / "data/processed/ausgrid_profile_bank_v2.npz")
    load, pv = exp._embed(bank)
    day = int(np.where(bank.split == "test")[0][0])
    feeder = ACSnapshotFeeder(exp.FEEDER_PATH, battery_sites=(exp.BATTERY_SITE,), pv_sites={"675.1": exp.PV_RATED_KW}, voltage_limits=exp.VOLTAGE_LIMITS)
    commands = [-70.0, 0.0, 70.0, 140.0]
    rows = []
    for p in commands:
        feeder.reset()
        a = feeder.solve(float(load[day, exp.SERVICE_STARTS[0]]), float(pv[day, exp.SERVICE_STARTS[0]]), {exp.BATTERY_SITE: p})
        rows.append({"command_kw": p, "realized_kw": a.battery_realized_kw[exp.BATTERY_SITE], "error_kw": a.battery_realized_kw[exp.BATTERY_SITE] - p, "feasible": a.feasible})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "realized_power_audit.csv", index=False)
    fig, ax = plt.subplots(figsize=(5.3, 4.0))
    ax.scatter(out.command_kw, out.realized_kw, s=44, color="#2166AC", zorder=3)
    lo, hi = min(out.command_kw.min(), out.realized_kw.min()) - 5, max(out.command_kw.max(), out.realized_kw.max()) + 5
    ax.plot([lo, hi], [lo, hi], ls="--", color="#555555", lw=1.0)
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("Commanded battery power (kW; + export)")
    ax.set_ylabel("Measured terminal power (kW; + export)")
    ax.set_title("Constant-PQ readback audit")
    ax.grid(color="#E2E2E2", linewidth=0.6)
    save(fig, "fig6_command_readback")


if __name__ == "__main__":
    workflow(); sequence_capacity(); heldout_audit(); soc_trace(); profile_splits(); realized_power_audit()
    print(f"wrote figures to {OUT}")

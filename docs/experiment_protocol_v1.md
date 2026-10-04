**ARCHIVAL COMPATIBILITY DOCUMENT.** This v1 protocol is retained for provenance and script compatibility. The current v5 evidence boundary is defined by `docs/reproducibility_v5.md` and the result metadata; this file must not be read as a preregistration for the current snapshot.

# Corrected experiment protocol (v1)

This protocol supersedes the archived V0 pilot. All quantities below are fixed before the held-out test is evaluated.

## Research question

Can a distribution-connected BESS be offered a repeated active-power service with an auditable post-service energy contract, and how much of the apparent sequence loss is caused by non-reset energy state versus the feeder's AC operating envelope?

## System and data

- IEEE 13-node OpenDSS snapshot (`data/raw/IEEE13Nodeckt.dss`), one BESS surrogate at `611.3`, and one fixed-P PV surrogate at `675.1` rated at 300 kW.
- OpenDSS is evaluated through `ACSnapshotFeeder`, which uses an isolated `NewContext`, constant-PQ surrogates, explicit command/readback checks, all non-source phase voltages, line and transformer loading ratios, and fixed limits 0.95--1.05 pu and 1.0 loading ratio.
- Ausgrid half-hour customer-day data are converted from kWh/0.5 h to average kW, with GC+CL as load and GG as PV. Ten seeded customer groups retain 48-point trajectories. The date split is made chronologically within each month before any outcome is computed (214 train, 71 calibration, 80 test dates).
- Profile amplitudes are mapped to feeder stress using train-only scales and the fixed embedding `load_scale=clip(0.40+0.30*load_norm, 0.35, 0.85)` and `pv_fraction=clip(0.10+0.60*pv_norm, 0, 1)`. This is a declared stress embedding, not a claim that one household equals the feeder load.

## Service contract

Each event contains four 30-minute export intervals at command `P` and eight 30-minute recovery intervals. The reserve-limited experiment uses import `0.30P`; the full-rearm control uses the fixed ratio `4/(8*0.95*0.95)=0.5540`, which restores the SOC before the next event. The battery has `E=500 kWh`, `SOC_initial=0.80`, `SOC_reserve=0.20`, and `eta_c=eta_d=0.95`; the tested command grid is 0--300 kW in 10 kW increments. Positive battery power means feeder export and negative power means charging.

The service and recovery powers are submitted as constant-PQ OpenDSS load surrogates. `ACSnapshotFeeder` reads terminal power back from `CktElement.Powers()` and records every bus voltage and line/transformer loading. The default terminal-power tolerance is 1% of the command (with a 0.01 kW floor); the direct readback audit is stored with the results.

Two pre-registered state mechanisms are compared:

1. **Full re-arm negative control.** The recovery command restores SOC to 0.80 and the same measured event is repeated. In a deterministic static snapshot, the admissible service set must be invariant across events (`C_M=1` up to the command-grid resolution).
2. **Reserve-limited non-reset sequence.** Recovery is capped at `0.30P` and SOC is carried forward. Sequence capacity is the largest tested `P` that satisfies the SOC reserve and every AC snapshot for M repeated service/recovery cycles. This is the claimed mechanism for genuine sequence contraction.

The sequence table repeats one held-out event for M=1,...,6 and also reports the test-day range. A profile-transition stress test is not used as evidence of SOC-only contraction.

## Selection and audit

Candidate offers are selected from all train dates using a fixed 95% successful-event threshold and the fixed 10 kW command grid. Calibration dates select the largest of the predeclared factors 0.80, 0.90, and 1.00 whose success is at least 95%. The final offer is then frozen before any test date is evaluated. Day is the resampling unit; profile groups within a day are not treated as independent days.

## Required negative controls

- Static profile + full re-arm: `C_M` must equal 1 up to the grid resolution.
- Command/readback audit: realized battery power must change with P and agree with the command.
- Train/test disjointness: no date appears in more than one split.
- No telemetry uplift: telemetry is not part of the main claim.

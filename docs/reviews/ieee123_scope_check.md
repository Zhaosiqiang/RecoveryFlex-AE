# IEEE-123 feeder scope check (2026-10-03)

## Decision

The IEEE-123 feeder should **not** be used as a quantitative transfer feeder in the current manuscript. The present adapter passes a useful software smoke test, but the frozen experiment protocol is not yet valid on this feeder. The static IEEE-123 snapshot has no operating point that satisfies the project's declared limits over the tested loading range: at lower loading the retained capacitor/regulator state creates an upper-voltage violation, while at nominal loading the source line is thermally overloaded. The QSTS input is promising, but it needs a separate time-indexed adapter and a predeclared operating-point protocol before it can support an Applied Energy result.

This decision preserves the evidence boundary. It does not discard the feeder files or modify any previous result. It prevents an infeasible base case from being presented as a policy failure or from being repaired by silently relaxing limits.

## What was checked

The check used the current working tree at commit `1563efa` plus uncommitted adapter repairs. The relevant input manifests are:

- `data/raw/ieee123_snapshot/manifest.json` (static public OEDISI/OpenDSS input);
- `data/raw/ieee123_qsts/manifest.json` (the same feeder with 35,040 quarter-hour load/PV-shape inputs).

The current `ACSnapshotFeeder` was exercised with independent OpenDSSDirect contexts, controls held off, a constant-PQ single-phase battery surrogate, voltage limits 0.95--1.05 pu, and line/transformer loading limits of 1.0. The adapter reports per-winding/per-phase transformer loading and explicit failure reasons. `pytest -q tests/test_ac_snapshot.py` passes all 6 tests, including valid IEEE-123 sites, invalid phase/site rejection, finite transformer telemetry, state-order independence, and failure classification.

The tests establish adapter behavior; they do not establish an IEEE-123 experiment.

## Static snapshot evidence

The following runs use `data/raw/ieee123_snapshot/master.dss`, no PV surrogate, battery command 0 kW at bus 47.1, and the same strict limits planned for the primary study. Values are from `ACSnapshotFeeder.solve(load_scale, pv_fraction=0, p_kw={"47.1": 0})`.

| load scale | converged | feasible | min V (pu) | max V (pu) | max line ratio | max transformer ratio | limiting evidence |
|---:|:---:|:---:|---:|---:|---:|---:|---|
| 0.50 | yes | no | 1.01491 | 1.09245 | 0.75890 | 0.45386 | `voltage_upper:83.1=1.09245>1.05` |
| 0.75 | yes | no | 0.99856 | 1.06979 | 1.16924 | 0.69925 | upper voltage at 83.1 and line loading |
| 1.00 | yes | no | 0.97834 | 1.04885 | 1.59087 | 0.95141 | `line.l115=1.59087`; additional line-loading violations |

A one-context sweep from load scale 0.50 through 1.20 at 0.025 increments produced no feasible base snapshot. The transition is structural: reducing load leaves bus 83.1 above 1.05 pu, while increasing load eventually exceeds the 1.0 line limit (and then the lower-voltage limit). The maximum line ratio at nominal loading is on `line.l115`; the high-voltage low-load condition is at bus 83.1 near the 600-kvar capacitor. Because the base case already fails, an AC-feasible export/charge frontier cannot be interpreted as the effect of the recovery policy without an additional, predeclared feeder-operating-point decision.

The current recovery scripts cannot be reused for IEEE-123 by changing a path. They hard-code the IEEE-13 feeder, PV site 675.1, and battery sites 611.3/634.1. Those sites are invalid on IEEE-123 and the IEEE-13 PV surrogate is not part of the IEEE-123 input.

## QSTS variant: evidence of a possible repair path

The QSTS master is not the same operating model as the static snapshot. A smoke run with `data/raw/ieee123_qsts/master.dss`, no added PV or battery, and the same limits gave:

| load scale | converged | feasible | min V (pu) | max V (pu) | max line ratio | first failure |
|---:|:---:|:---:|---:|---:|---:|---|
| 0.50 | yes | yes | 0.98113 | 1.00255 | 0.52396 | none |
| 0.80 | yes | no | 0.9586 | 1.0000 | 1.01689 | `line.l115`/`line.sw1` loading |
| 0.90 | yes | no | 0.94947 | 1.0000 | 1.18319 | lower V at 114.1 and line loading |
| 1.00 | yes | no | 0.94025 | 1.0000 | 1.35008 | lower V at 114.1 and line loading |

This does not qualify as transfer validation. The QSTS model references individual 35,040-point load shapes and nine PV shapes. The current adapter deliberately calls `InitSnap` and `SolveNoControl`, captures native base loads, and applies an explicit scalar load scale; it does not set a QSTS time index, replay the load-shape multipliers, or coordinate the embedded PV systems with an external profile bank. Treating the QSTS file as a static feeder would therefore change the intended model semantics.

## Minimum gate before IEEE-123 can enter the paper

1. Freeze one IEEE-123 input variant and its hashes. Decide whether the feeder is evaluated as a static snapshot with a justified tap/capacitor operating point or as a QSTS model with explicit time indices. Do not mix the two.
2. Implement a QSTS-aware adapter that sets the interval deterministically (or exports the exact shape multipliers and disables shape references). Define how regulator and capacitor controls are handled and record every control action.
3. Add the same network-aware recovery protocol used on IEEE-13: identical service/recovery windows, battery energy and efficiency, AC replay, and failure taxonomy. Use predeclared near-source, mid-feeder, and remote placements and at least two phase assignments. A three-phase or phase-explicit BESS model is preferable to one arbitrary single-phase surrogate on IEEE-123.
4. Add a fixed converter kVA/PQ capability and ramp bound. The current constant-PQ surrogate has no such capability curve, so a high IEEE-123 frontier would otherwise be an idealized upper bound.
5. Check the zero-battery base case at every evaluated interval first. Report the number and dates of baseline-feasible rows. If the feeder has no feasible operating point under the declared limits, report it as an adapter/feeder diagnostic and exclude it from the quantitative transfer claim; do not relax limits after seeing the result.
6. Run the complete frozen protocol on the QSTS data (including all placement/phase combinations and a deterministic external profile mapping), then rerun editorial, methods, and adversarial reviews. Only after these checks pass should IEEE-123 be promoted from appendix diagnostic to a main-text transfer result.

## Scope for the current manuscript

The current paper should use IEEE-13 as the quantitative AC feeder and retain the IEEE-123 files and smoke tests as development evidence only. The manuscript must not claim IEEE-123 transfer performance, annual IEEE-123 validation, or cross-feeder generality. The superseded `audit/invalid_v0_20261003` IEEE-123 event-tree outputs are not evidence for this redesign and must not be copied into the submission bundle.

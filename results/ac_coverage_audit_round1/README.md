# AC coverage and scope audit (round 1)

This directory reports reproducible diagnostics for the outstanding AC-coupling, baseline-gate, device-cap, synthetic-embedding, and numerical-tolerance questions. It does not change the frozen strict-v4 primary results.

- `unconditional_gate_summary.csv` uses all 2,190 date-group units per placement, including zero-power gate failures.
- `scalar_vs_replay_sample.csv` is a stratified 200-unit sample (10 dates x 10 groups x 2 placements). `replay_endpoint_checked_kw` is at least the scalar endpoint when that endpoint passes all 48 nonlinear snapshots; a failing endpoint receives a lower-power search. It is a sample diagnostic, not a new full-population endpoint.
- `prefix_monotonicity_sample.csv` checks every interval, both signs, and the complete 0--300 kW / 20 kW candidate grid for that same sample. A later feasible point after a failed candidate is counted explicitly.
- `numerical_sensitivity_sample.csv` varies the declared voltage/loading tolerance, command readback floor, and candidate-grid step on a 40-unit sample.
- `device_power_cap_summary.csv` clips frozen scalar charge/export bounds by a symmetric power rating; it is not an AC inverter model.
- `embedding_sensitivity_summary.csv` varies load gain, PV rating, and PV location on six dates and two groups per site using fresh AC snapshot bounds.

The evidence supports bounded model-based screening claims only. It does not establish cross-feeder transferability or a physical inverter capability guarantee.

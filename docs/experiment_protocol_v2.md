# Frozen experiment protocol (development v2)

Status: development evidence; not a preregistration and not a submission-ready result.

## Research question

Can a distribution operator obtain a larger reliable repeated-flexibility contract when recovery charging is optimized over the full chronological horizon with AC-feasible, time-varying feeder headroom?

## Contract and horizon

- Time step: 0.5 h.
- Service windows: intervals 8--11 and 24--27 (two two-hour calls).
- Horizon: 48 intervals (24 h), ending twenty intervals after the second call.
- Initial and terminal SOC: 0.80, with an SOC lower bound of 0.20 and upper bound of 1.00.
- Usable battery energy: 2,000 kWh; charge and discharge efficiencies: 0.95.
- Candidate service-power ceiling: 0--300 kW, refined by a checked monotone bisection to below 0.1 kW for each interval bound.
- Fixed-recovery windows: intervals 12--23 and 28--47. The fixed baseline charges only in these windows.
- Fixed-recovery ratio:

  `8 / (32 * 0.95 * 0.95) = 0.2770083`.

  This supplies the energy for the eight service intervals while leaving the first call supported by the preconditioned initial SOC. The post-call window gives every policy a declared terminal-recovery opportunity within the same 24 h profile.

## Policies

1. `network_lp`: maximizes constant service power subject to the full time-varying AC charge/export bounds, SOC dynamics, service windows, and exact terminal SOC.
2. `fixed_recovery`: uses the frozen ratio above in the two declared recovery windows; it does not adapt charging to network headroom.
3. `myopic_recovery`: at each interval charges only toward the next contiguous service block, then toward the terminal SOC after the final block; it does not optimize the full horizon.
4. `energy_only`: replaces time-varying AC limits with their per-profile maxima. It is an energy-only counterfactual upper bound; its schedule is still replayed through AC and is expected to fail when it exceeds feeder limits.

## AC audit

The IEEE 13-node OpenDSS snapshot is rebuilt for each candidate command. The PV surrogate is 300 kW at bus 675.1. The BESS is tested at single-phase placements 611.3 and 634.1. Voltage limits are 0.95--1.05 pu and line/transformer loading limits are 1.0. A numerical tolerance of 1e-6 pu or loading ratio is applied consistently to OpenDSS readback checks so nonlinear-solver roundoff at a bisection endpoint is not classified as a physical violation. Candidate schedules are replayed interval by interval and marked physically feasible only when every AC solve passes the adapter's convergence, command/readback, voltage, line, and transformer checks under this rule.

The IEEE 123-node snapshot is retained as an adapter diagnostic only. Its strict baseline feasibility gate currently fails under the same limits, so it is not used for quantitative claims.

## Data and leakage control

Development scaling is frozen from the chronological development bank. The external 2012--2013 Ausgrid source contains 365 raw calendar dates; the strict fixed-denominator completeness mask retains 219 dates in three non-contiguous blocks (2012-07-01--2012-10-11, 2013-01-01--2013-01-25, and 2013-04-01--2013-06-30). The remaining dates are excluded rather than imputed. The frozen customer-group mapping and development-year scales are used, and no external-year outcome is used to change constants. Source metadata and SHA-256 hashes are recorded in `data/processed/ausgrid_external_2012_2013_strict.json`. This is a temporal external evaluation under a frozen protocol, not an untouched or continuous full-year holdout.

## Primary outcomes

- Mean feasible service power by placement and policy on the independent year, conditional on baseline AC feasibility.
- Paired `network_lp - baseline` effects at the date × customer-group × placement unit.
- AC replay success and failure rates.

Uncertainty is estimated with a date-cluster bootstrap (5,000 replicates, seed 20261003); date × group bootstrap is a sensitivity analysis. The energy-only schedule is reported as an upper bound and not as a physically deliverable policy.

## Reproduction

```text
python scripts/run_network_recovery_parallel.py --days 219 --groups 10 --workers 4 \
  --source data/processed/ausgrid_external_2012_2013_strict.npz \
  --out-dir results/network_recovery_external_2012_2013_strict_v3
python scripts/build_network_recovery_statistics.py \
  --results-dir results/network_recovery_external_2012_2013_strict_v3 \
  --out-dir results/network_recovery_external_2012_2013_strict_v3/statistics
python scripts/build_network_recovery_figures.py \
  --results-dir results/network_recovery_external_2012_2013_strict_v3 \
  --trace-dir results/network_recovery_external_2012_2013_strict_v3 \
  --out-dir figures/network_recovery_strict_v3
```

The protocol is frozen for this development round. The `strict_v3` directory is the adapter-corrected final result for this protocol; the earlier `strict_v2` directory used a pre-tolerance adapter and is retained as audit-only. Any later change must be recorded as a new protocol version and cannot overwrite the independent-year result directory.

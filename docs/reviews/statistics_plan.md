# Statistical analysis plan for the network-recovery experiment

**Status: development analysis plan; frozen before reading the full 2012–2013 run.**

The unit of comparison is a measured profile identified by `date × group × site`.
All four policies (`network_lp`, `fixed_recovery`, `myopic_recovery`, and
`energy_only`) use exactly the same profile, OpenDSS bound table, service
windows, SOC limits, and terminal condition.  Therefore the primary effects
are paired differences rather than differences between independent policy
samples.

## Estimands

For each battery placement and each baseline (b), the main estimand is

\[
  \Delta_{b} = E[\text{service}_{network\_lp} - \text{service}_{b}],
\]

where service is the planned contract power in kW.  A secondary estimand is
the paired difference in AC replay success (a 0/1 outcome).  The report keeps
two populations separate:

* **All profiles** includes every attempted date×group profile and exposes
  failures of the zero-command operating point.
* **Baseline-feasible profiles** conditions on a feasible zero-command AC
  operating point.  This is the fair comparison of policy decisions after the
  feeder itself has passed the feasibility gate; the number excluded is
  reported, never silently discarded.

The energy-only policy is an energy upper bound and is intentionally replayed
through OpenDSS.  Its replay failure is therefore an interpretable counterfactual,
not evidence that a physical controller can deliver the energy-only value.

## Uncertainty and clustering

`scripts/build_network_recovery_statistics.py` writes absolute method summaries,
paired effects, and a JSON manifest.  It uses a fixed seed (`20261003`) and
percentile bootstrap intervals with 5,000 replicates for the final run.  The
primary interval resamples **dates** and averages all available groups within
each sampled date; this preserves within-day correlation and gives each date
equal weight.  A date-by-group paired bootstrap is written as a sensitivity
analysis.  The paired unit is always date×group×site, so no method is treated
as an independent replicate.

For every estimate the output records the number of paired rows, independent
clusters, point estimate, 95% percentile interval, and the bootstrap
probability that the effect is positive.  A one-date input returns a degenerate
interval rather than manufacturing uncertainty.  Duplicate or incomplete
date×group×site policy rows cause the script to stop, because silently changing
the pairing would invalidate the comparison.

The manuscript should report the date-cluster result as the primary analysis
and show the date×group result as a robustness check.  If the two intervals
lead to different qualitative conclusions, the date-cluster result governs
the claim and the discrepancy is discussed as a dependence sensitivity.

## Files and reproducibility

For a result directory `R`, run:

```text
python scripts/build_network_recovery_statistics.py \
  --results-dir R \
  --out-dir R/statistics \
  --bootstrap 5000 --seed 20261003
```

The script creates:

* `method_summary.csv`: absolute service and replay-success estimates for
  each method, population, and cluster level;
* `statistics.csv`: paired `network_lp − baseline` service and replay effects;
* `paired_effects.csv`: the auditable date×group paired table;
* `statistics.json`: protocol metadata and the same records in machine-readable
  form.

The 12-day external smoke output was used only to validate the schema and
calculation.  It produced 960 policy rows, 120 date-cluster pairs per site,
and reproducible finite intervals.  The smoke output must not be presented as
the final validation sample; the full independent-year output remains the
source for the manuscript once its experiment finishes.

The statistical script does not alter `policy_rows.csv`, rerun OpenDSS, or
read any result while the full experiment is running.  It can therefore be
run after the full result directory is complete without changing the
experimental protocol.

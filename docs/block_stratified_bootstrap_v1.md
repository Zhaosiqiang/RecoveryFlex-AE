# Calendar-block stratified uncertainty audit (v1)

This audit addresses the non-contiguous retained-date design. It does not treat the retained dates as an untouched continuous-year holdout, and it does not claim that resampling can remove dependence between the three calendar blocks.

## Retained blocks

| block | dates | retained dates | baseline-gated pairs per primary site |
|---|---|---:|---:|
| 2012-07--2012-10 | 2012-07-01--2012-10-11 | 103 | 1,029 |
| 2013-01 | 2013-01-01--2013-01-25 | 25 | 249 |
| 2013-04--2013-06 | 2013-04-01--2013-06-30 | 91 | 910 |
| **total** | three retained blocks | **219** | **2,188** |

## Estimand and resampling

For each site, method, and outcome, the script first averages the paired date-by-group rows within each retained date. It reports each block mean separately. The stratified interval resamples retained dates with replacement **within each block** and combines the resampled block means using the observed block-date weights (103/219, 25/219, and 91/219). It uses 5,000 replicates, seed `20261003`, and independent SHA-256 keyed random streams. The population is the independently checked zero-power AC-gated units (`baseline_feasible=1`).

Outputs:

- `results/network_recovery_external_2012_2013_strict_v4/statistics/block_summary.csv`: block means and pair/date counts;
- `results/network_recovery_external_2012_2013_strict_v4/statistics/block_stratified_summary.csv`: weighted point estimates and intervals;
- `results/network_recovery_external_2012_2013_strict_v4/statistics/block_stratified_metadata.json`: protocol and interpretation boundary.

Reproduce with:

```bash
/Users/skzhao/miniconda3/bin/python scripts/build_block_stratified_statistics.py
```

The resulting intervals remain **descriptive retained-sample block-stratified intervals**. They do not estimate a population-level seasonal effect, correct dependence across blocks, or provide a future delivery probability.

## Primary AC-bound scalar-LP block means

The baseline-gated network-LP endpoint (kW) is:

| site | 2012-07--2012-10 (103 d) | 2013-01 (25 d) | 2013-04--2013-06 (91 d) | weighted 219-date mean |
|---|---:|---:|---:|---:|
| 611.3 | 123.795 | 133.683 | 132.464 | 128.526 |
| 634.1 | 130.484 | 141.495 | 146.776 | 138.511 |

The block spread is a retained-calendar diagnostic. It is not interpreted as an independent seasonal causal effect because load/PV embedding, source completeness and block membership are protocol-dependent.

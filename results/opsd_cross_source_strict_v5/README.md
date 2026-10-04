# OPSD cross-source validation (diagnostic)

This directory contains an independent profile-source validation of the frozen
RecoveryFlex v2 fair-window protocol. The feeder and all dispatch constants are
held at the manuscript settings. The input is the public OPSD household bank
(`data/processed/opsd_profile_bank_v2.npz`, SHA-256 recorded in `summary.json`).

OPSD provides 96 15-minute average-power values per day. Adjacent pairs are
averaged to obtain the 48 half-hour values required by the contract. The first
396 chronological OPSD dates (training split) alone determine the load and PV
normalization scales. The 132 dates in the held-out test split are evaluated
continuously from 2016-10-31 through 2017-03-11. The single household profile
is applied to two IEEE-13 placements, 611.3 and 634.1; this is a profile-source
robustness check, not an independent-feeder claim.

`policy_rows.csv` contains one row per date, placement, and method. `ac_bounds.csv`
contains the interval AC limits, and every planned schedule is replayed through
OpenDSS. `date_cluster_summary.csv` gives descriptive percentile intervals after
resampling date-level means. The intervals are not inferential corrections for
serial dependence. `opsd_cross_source_frontier.pdf` is a diagnostic figure.

The script is `scripts/run_opsd_cross_source.py`; the figure script is
`scripts/build_opsd_cross_source_figure.py`. The output is not included in the
journal package unless the authors explicitly elect to add the validation and
its source/licence notice.

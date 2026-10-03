# Editorial and scope review round 2

## Manuscript audited

`paper/main_v2.tex`, compiled locally as `paper/main_v2.pdf`, based only on `results/network_recovery_external_2012_2013_strict_v3/`.

## Desk-rejection checks

1. **Scope:** The paper is framed as an applied distribution-energy screening benchmark. It does not claim a market price, procurement cost, real-time control policy, or universal reliability guarantee.
2. **Title and abstract:** The title uses “benchmark” and “AC--SOC”; the abstract states the hindsight information boundary, the non-contiguous retained dates, the conditional denominator, and the placement-dependent result.
3. **Evidence traceability:** Every numerical value in the abstract and Results is present in `statistics/method_summary.csv`, `statistics/statistics.csv`, `summary.json`, or `baseline_zero_audit.csv`.
4. **Negative result:** The identical 611.3 LP and myopic result is retained. The manuscript does not convert the 634.1 improvement into a universal method claim.
5. **Data transparency:** The fixed-denominator rule, strict date mask, source hash, three retained date blocks, and non-untouched status are explicit.
6. **Reproducibility:** The result directory contains AC bounds, policy rows, independent zero-power audit, failure records, figures, statistics, and protocol metadata.

## Required corrections made

- Replaced the earlier procurement/risk-calibrated framing with an offline benchmark and DSO screening use case.
- Removed 95%-reliability and untouched-holdout language.
- Added the 219-date completeness mask and baseline-gate denominator.
- Added the hindsight oracle limitation and the checked-grid limitation.
- Added the energy-only AC replay result as a counterfactual diagnostic.
- Added explicit AI, funding, competing-interest, CRediT, and data/code declarations.

## Remaining submission metadata

The affiliation, corresponding-author address/e-mail, final release tag, and persistent archive DOI are still missing. These are administrative blockers for a real submission, not scientific claims to be inferred.

## Editorial decision

**Conditionally ready for another internal methods/adversarial pass.** No known title, abstract, scope, or traceability defect remains in this round. Submission remains intentionally paused until the remaining metadata and final archive are supplied.

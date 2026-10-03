# Methods review round 3

## Checks

- `pytest -q`: 20 passed.
- Strict result: 219 dates, 10 groups, 2 sites, 17,520 policy rows and 210,240 AC-bound rows.
- Independent zero-power audit: 4,376/4,380 placement units pass; policy `baseline_feasible` agrees exactly with the audit.
- Primary conditional denominator: 2,188 units per site.
- Date-cluster bootstrap: 5,000 replicates, seed 20261003.
- Adapter readback tolerance: 1e-6 pu/loading ratio, declared in both code and protocol.
- Full-horizon LP and fixed recovery replay: 100% conditional replay at both placements.
- Myopic replay: 100% at 611.3 and 2,187/2,188 at 634.1.
- Energy-only replay: 0% at both placements.

## Findings and disposition

1. The full-horizon LP sees the complete realized day and future AC bounds. The manuscript labels it an offline hindsight benchmark and does not call it real-time, forecast-based, robust, or chance-constrained.
2. The AC prefix search is conservative but does not prove a continuous inner feasible interval. The manuscript states this limitation and identifies command-grid resolution as a sensitivity for a future extension.
3. The 611.3 LP--myopic difference is exactly zero. The manuscript reports this as a valid negative result.
4. The 634.1 LP--myopic difference is 2.433 kW with date-cluster CI 1.682--3.293. The manuscript calls it placement dependent and descriptive.
5. The 2012--2013 retained dates are discontinuous and were inspected during development. The manuscript avoids “untouched” and “full-year holdout.”
6. Failure records are now generated from the final result directory and retain interval, class, reason, and limiting component. The manuscript reports replay rates and only uses failure records for auditability.

## Methods decision

**Pass with bounded claims.** The implementation and estimand are internally consistent. The main residual risks are external validity (one feeder), hindsight information, and the idealized active-power battery surrogate; all are stated as limitations rather than hidden assumptions.

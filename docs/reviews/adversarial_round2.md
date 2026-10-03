# Adversarial review round 2

## Attack 1: hidden data leakage

The external source is not presented as untouched. Customer groups, normalization scales, feeder locations, windows, SOC parameters, and code were frozen before the strict external run. The retained-date mask is deterministic and based on customer completeness, not service outcomes. The source hash and retained blocks are in the manifest.

## Attack 2: denominator manipulation

All retained groups use the fixed 30-customer denominator. Dates with incomplete required channels are excluded. Direct customer-level spot checks reproduced the strict arrays with maximum absolute error 0.0 kW.

## Attack 3: baseline conditioning hides failures

The manuscript reports the attempted denominator (2,190 per site), the four failed placement units, and the conditional denominator (2,188). The independent zero-power audit is preserved. No method is allowed to remove a failed baseline unit silently.

## Attack 4: AC feasibility is only a reduced model

The LP result is always replayed through OpenDSS. The manuscript calls it model-based feasibility, states the active-power/Q=0 surrogate, and avoids field-delivery language. The checked-grid prefix and numerical tolerance are explicit.

## Attack 5: hindsight and weak baseline

The full-horizon LP is labelled a hindsight offline benchmark. The myopic rule is described as a short-horizon baseline, not a competitive online controller. The discussion does not claim causal superiority or deployability.

## Attack 6: post-hoc site selection

The two sites are retained as the frozen quantitative placements selected during development. The manuscript does not call them preregistered or generalizable across feeders. The placement-dependent effect is interpreted as a case result.

## Adversarial decision

No hidden numerical or wording defect was found after the v3 rerun. The paper is suitable for another author-level read, but acceptance cannot be predicted and the package must not be uploaded before affiliation/e-mail and archival-release details are complete.

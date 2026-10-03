# Topic decision

## Selected question

How much battery flexibility can a distribution operator safely offer when each activation must be followed by a feasible recharge window, the delivery and recovery intervals share the same feeder limits, and the operator has incomplete or noisy telemetry?

## Working title

**From single-event headroom to repeatable services: AC-audited recovery envelopes for distributed batteries in active distribution feeders**

## Why this fits Applied Energy

The paper addresses energy flexibility, renewable/storage integration, and operational decisions in active distribution networks. The output is an actionable service contract in MW, MWh, duration, and recovery deadline, conditioned on telemetry coverage and forecast error as an ablation axis, with explicit AC feasibility and operational/economic consequences.

## Novelty boundary

Evans, Tindemans, and Angeli (IEEE TSG, 2022) provide an exact aggregated storage discharge--loss--recovery model, but it is copper-plate and does not enforce feeder-node voltage, line-thermal, phase, PV, or load constraints. Applied Energy security-flexibility work defines one-event or security-duration operating limits, but does not construct a repeated service envelope with a terminal recovery condition. This paper combines network physics and repeatable recovery with a measurement-conditioned state uncertainty margin. Recovery itself, SOC dynamics itself, dynamic operating envelopes themselves, and generic feasible-region aggregation are not claimed as new.

## Falsifiable hypothesis

For the same aggregate battery power and energy ratings, the two-event AC-feasible service capacity is materially smaller and more placement-dependent than the one-event capacity or a copper-plate recovery envelope. The gap grows with feeder stress, longer service duration, shorter recovery deadlines, and poorer telemetry; calibrated uncertainty margins should reduce false-safe offers at a measurable cost in accepted flexibility.

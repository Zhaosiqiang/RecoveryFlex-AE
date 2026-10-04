# DSO / aggregator screening decision chain — v6

This document turns the scalar experiment into an operational screening workflow without treating the result as a delivery guarantee.

1. **Operating-point gate.** For each date × profile-group × candidate bus-phase, solve every zero-battery interval in the isolated OpenDSS snapshot. A failed zero-power gate is an automatic technical rejection/escalation and remains in the unconditional denominator; it is not silently removed from a portfolio rate.
2. **Interval envelope.** For a gate-passing unit, retain the checked-prefix charge and export endpoints, their grid/bisection metadata, limiting components, and source hashes. These are interval audit outputs, not a joint AC feasible region.
3. **Contract endpoint.** Feed the interval bounds into the AC-bound scalar LP with the declared service/recovery windows, SOC limits, efficiencies, and terminal mode. The resulting (P^star) is the maximum constant service power for the scalar contract under the checked-prefix envelope.
4. **Offer rule.** A site-specific technical screen may cap an offer at (P^star). For a common cross-placement offer, calibrate a declared lower-tail quantile only on the calibration block, freeze it, and apply it without site retuning to the evaluation block. Report both planner coverage and conditional nonlinear replay coverage, plus the unconditional gate denominator.
5. **Replay and escalation.** Replay representative or selected schedules interval by interval through OpenDSS. Any replay failure, gate failure, or tolerance-edge readback is recorded with interval, failure class, and limiting component. A DSO may reject the offer, lower it, or send it to a higher-fidelity AC/uncertainty/market model; the present study does not choose among those commercial actions.
6. **Evidence label.** Every delivered number is labelled as one of: scalar-bound endpoint, scalar dispatch sensitivity, selected nonlinear replay, or descriptive retained-sample interval. Only the selected replay cells support model-based AC feasibility statements; none is a future delivery guarantee.

The chain is intentionally a technical filter for bid-limit pre-screening. It does not optimize prices, penalties, activation probabilities, congestion value, or market clearing, and it does not replace inverter capability, forecast-error, or protection studies.

# Final experiment plan before submission

The pilot is a feasibility gate. The submission package must satisfy these checks before the abstract is rewritten around final numbers.

## A. Sequence contraction

For each feeder and battery placement, evaluate `M = 1, 2, 3, 4` calls with `D = 15, 30, 60 min` and `H = 1, 2, 4, 8 h`. Compute `P*_M`, `C_M`, and `NRP_M`. Include the copper-plate DLR upper bound and the delivery-only AC candidate.

## B. AC external feeder audit

Use the IEEE 13-node unbalanced feeder for the primary detailed audit and the IEEE 123-node QSTS feeder for transfer. BESS placements must span near-source, middle and electrically remote buses and at least two phase assignments. Recalibrate regulator/capacitor limits before using a strict 0.95--1.05 pu sensitivity.

## C. Profile split and information axis

Use customer/day or feeder/day splits by date, season and customer. No random row split. Compare full, 50% and sparse state-information margins under 0/5/10/20% held-out load/PV error. Report pass count, Wilson 95% interval, false-safe rate and the service-power frontier.

## D. Negative controls and robustness

- Zero forecast error should collapse information-margin differences.
- A longer deadline should help energy-limited cases but not network-limited cases.
- Moving the same battery to a remote phase should change the AC bottleneck.
- Increasing events should not increase the viable capacity (sequence contraction).
- OpenDSS replay and the reduced-order candidate must use the same battery parameters and hidden scenarios.

## E. Final evidence threshold

The main claim is retained only if (i) sequence contraction is visible in at least two placements/feeder cases, (ii) AC and copper-plate capacities differ materially in at least one stressed case, and (iii) the information axis changes the false-safe/service frontier without being the only source of novelty. Otherwise the paper is narrowed to a methods/benchmark report rather than submitted as a novelty claim.

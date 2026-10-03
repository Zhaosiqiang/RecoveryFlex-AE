# RecoveryFlex-AE

Research package for **From single-event headroom to repeatable services: AC-audited recovery envelopes for distributed batteries in active distribution feeders**.

This is an independent project. It does not reuse the stopped-round topology-identification experiments in `NEXT_PAPER_TOPOSET_2026`. The core object is a network-coupled service--recovery contract: a battery service trajectory is accepted only when the service interval and the recovery interval jointly satisfy battery, three-phase AC voltage, line-thermal, and inverter constraints.

## Reproducibility status

The repository is being built in stages. The first milestone is a small IEEE 13-bus end-to-end pilot, followed by public smart-meter/PV profiles, IEEE 13/123-bus experiments, figure regeneration, and the Applied Energy submission bundle. All numbers in the manuscript will be generated from `results/` by the scripts in this repository; no result from the abandoned stopped-round project is copied into this paper.

## Authors

Siqiang Zhao (conceptualization, methodology, software, validation, formal analysis, investigation, data curation, visualization, original draft) and Fengxiang Zhang (supervision, review and editing).

## License

Code: MIT. Public input data retain their original licenses; provenance is recorded in `data_sources.md`.


## Research object

The method is expressed as a finite service--recovery viability composition. For a candidate service amplitude P, duration D, recovery deadline H, and event count M, the map `(service -> AC-constrained recovery)^M` is applied to SOC and feeder-margin states. The repeatable contract is the subset that remains viable after every re-arm. Telemetry is evaluated as a sensitivity axis that changes the candidate uncertainty margin; it is not the paper title or a communication-planning contribution.

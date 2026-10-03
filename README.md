# RecoveryFlex-AE

Research package for **From single-event headroom to repeatable services: AC-audited recovery envelopes for distributed batteries in active distribution feeders**.

This is an independent project. It does not reuse the stopped-round topology-identification experiments in `NEXT_PAPER_TOPOSET_2026`. The core object is a network-coupled service--recovery contract: a battery service trajectory is accepted only when the service interval and the recovery interval jointly satisfy battery, three-phase AC voltage, line-thermal, and inverter constraints.

## Reproducibility status

The repository now contains a reproducible working submission candidate: an IEEE 13-bus pilot, IEEE 123-bus four-event transfer audit, Ausgrid and OPSD profile processing, figures, tables and an Elsevier-style manuscript. All reported numbers are generated from `results/` by the scripts in this repository; no result from the earlier topology-identification project is copied into this paper.

## Authors

Siqiang Zhao (conceptualization, methodology, software, validation, formal analysis, investigation, data curation, visualization, original draft) and Fengxiang Zhang (supervision, review and editing).

## License

Code: MIT. Public input data retain their original licenses; provenance is recorded in `data_sources.md`.


## Research object

The method is expressed as a finite service--recovery viability composition. For a candidate service amplitude P, duration D, recovery deadline H, and event count M, the map `(service -> AC-constrained recovery)^M` is applied to SOC and feeder-margin states. The repeatable contract is the subset that remains viable after every re-arm. Telemetry is evaluated as a sensitivity axis that changes the candidate uncertainty margin; it is not the paper title or a communication-planning contribution.

# Literature boundary for the Applied Energy paper

The central claim is sequence-level deliverability of distributed-battery services under feeder physics. The following works define the boundary that the manuscript must acknowledge.

| Work | Main object | Difference from this project |
|---|---|---|
| Evans, Tindemans & Angeli (2022), DOI 10.1109/TSG.2022.3173900 | Aggregated storage discharge/loss/recovery framework | No internal feeder AC physics, phase/branch constraints, or repeated DSO contract audit |
| Bolfek & Capuder (2022), DOI 10.1016/j.epsr.2022.108262 | Flexibility provision in an unobservable distribution network | Static nodal range; no BESS terminal SOC re-arm sequence |
| Giraldo et al. (2023), DOI 10.35833/MPCE.2022.000452 | Risk-aware EV flexibility areas via AC stochastic OPF | EV pool and one planning/activation setting; not a distributed-BESS repeated contract |
| Xiao et al. (2025), DOI 10.1016/j.apenergy.2024.125253 | Security regulating capability and safe duration | No cross-event terminal SOC recovery contract |
| Lankeshwara et al. (2025), DOI 10.1016/j.apenergy.2024.125150 | Dynamic operating-envelope demand response | No sequence-level battery re-arm viability object |
| AE 2026, DOI 10.1016/j.apenergy.2026.128444 | Dynamic feasible-region aggregation for storage-like resources | Full-information deterministic FOR aggregation; no hidden-scenario repeated-service failure frontier |
| AE 2026, DOI 10.1016/j.apenergy.2026.127562 | Multiple demand-response activations and recovery periods | Energy-hub scheduling without internal unbalanced feeder AC audit |
| AE 2026, DOI 10.1016/j.apenergy.2026.128736 | Communication quality mapped to dynamic SOC reservation | Communication/planning problem; not an AC-audited service contract |
| Energies 2026, DOI 10.3390/en19194671 | Partial-observation duration/dependability matrix | Historical trajectory matching; no explicit BESS re-arm composition with terminal deadline |
| arXiv:2603.27161 | Scenario-robust service and post-service rebound | One service-window interface; no repeated calls and sequence contraction |
| SSRN 7356679 | AC-validated local battery procurement and cost recovery | Single-day procurement/cashflow audit; no cross-event viability contract |

Applied Energy scope: energy storage, grid integration, demand response/flexibility, power-system operation, optimization and data analytics are explicitly relevant. The paper avoids presenting telemetry as the headline contribution; it is an information-quality sensitivity in a network-recovery contract.

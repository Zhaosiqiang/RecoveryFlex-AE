# Experimental protocol (version 0.1)

1. Compile an IEEE 13-bus unbalanced OpenDSS feeder and record baseline voltage, line loading, and phase imbalance.
2. Place one to three inverter batteries at electrically distinct buses/phases with fixed power/energy ratings.
3. Create telemetry masks and forecast-error levels, then sample a service event of duration `D` followed by a recovery window `H`; event signs cover export and import services.
4. Build candidate offers using four baselines and the proposed network-coupled recovery envelope.
5. Replay every selected trajectory in OpenDSS at 15-minute steps. Each offer must pass voltage, thermal, inverter, SOC, and terminal-SOC checks.
6. Report one-event capacity, two-event repeatable capacity, repeatability ratio, network-loss fraction, recovery failures, PV curtailment, grid import, throughput, and runtime.
7. Split Ausgrid days by date/season, never by random rows. Hold out customers and days for final AC audit.

Baselines: B0 network-only instantaneous envelope; B1 copper-plate aggregate recovery; B2 summed power/energy heuristic; B3 deterministic multi-period model with terminal SOC but no scenario uncertainty; B4 proposed measurement-aware network-coupled recovery envelope; B5 full multi-period AC oracle on a small subset.

The principal information experiment compares full telemetry, 50% phase/bus telemetry, and 20% telemetry under 0/5/10/20% held-out load/PV forecast error. The proposed margin is calibrated on training days and evaluated on held-out customers and dates.

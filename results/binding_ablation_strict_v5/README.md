# Strict-v5 binding ablation

This directory is a read-only audit of the existing Ausgrid strict-v4 and OPSD strict-v5 CSV outputs. It does not run OpenDSS or modify the manuscript.

`two_mwh_binding_by_unit.csv` compares each 2-MWh `network_lp` endpoint with the minimum `export_limit_kw` across the eight service intervals (8--11 and 24--27). `two_mwh_binding_summary.csv` reports exact and tolerance-based equality for all rows and for the manuscript's `baseline_feasible` population.

`capacity_binding_by_unit.csv` and `capacity_binding_summary.csv` perform the same comparison for the Ausgrid network-LP capacity rows at 250, 500, 1000, and 2000 kWh. `date_mean_delta_kw` first averages groups within each date and then averages dates equally, matching the manuscript's primary estimator within each placement. `AUDIT.txt` gives a compact deterministic report; `summary.json` records inputs and checks.

A negative delta is `network frontier - minimum service-window export bound`. It shows that the dispatch endpoint is below the tightest service-window export bound. Equality is a binding check, not proof that no other network or SOC constraint is active elsewhere in the schedule.

> **NOT READY FOR SUBMISSION.** The first v1 draft and its numerical claims were superseded by independent editorial, methods, and adversarial reviews on 3 October 2026. They remain only as audit records under `audit/superseded_v1_review_20261003/` and must not be quoted as current findings.

# RecoveryFlex

This repository is the development codebase for a new Applied Energy study on **network-feasible recovery scheduling for repeated distribution-flexibility services**. OpenDSS produces time-indexed battery-side export and charge limits; a chronological LP then schedules recovery across multiple service windows and is replayed through the AC model.

The current evidence includes: a corrected and tested OpenDSS adapter with per-winding/per-phase transformer loading, numerical readback tolerance, and failure diagnostics; a strict fixed-denominator 2012–2013 external-date bank; a dispatch core with network-aware, fixed-recovery, myopic, and copper-plate baselines; a 48-interval strict external run; an independent zero-power audit; failure records; and an 8-page manuscript draft with reviewed figures. Run `pytest -q` for the 20 software checks. The current result is an offline AC–SOC benchmark on one feeder, not a real-time policy or an economic procurement model.

Authors: Siqiang Zhao and Fengxiang Zhang. Code license: MIT. Third-party sources retain their original licenses. Public repository: https://github.com/Zhaosiqiang/RecoveryFlex-AE.

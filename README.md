# RecoveryFlex

This repository contains the corrected v1 research package for the Applied Energy submission candidate “Auditable repeated-service contracts for distribution-connected batteries”. The former V0 pilot was independently invalidated and is preserved under `audit/invalid_v0_20261003/` for provenance only; its numerical claims are withdrawn.

The corrected pipeline uses an isolated OpenDSS constant-PQ adapter, a chronological Ausgrid interval profile bank, train/calibration/test offer selection, a full-rearm negative control, and a reserve-limited SOC sequence experiment. Reproduce the experiment with `python scripts/run_corrected_experiment.py`, regenerate figures with `python scripts/build_corrected_figures.py`, and run `pytest -q`.

Authors: Siqiang Zhao and Fengxiang Zhang. Code license: MIT. Third-party sources retain their original licenses. Public repository: https://github.com/Zhaosiqiang/RecoveryFlex-AE.

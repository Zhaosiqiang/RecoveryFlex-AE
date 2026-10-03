# Raw-input provenance

`IEEE13Nodeckt.dss`, `IEEELineCodes.dss`, and `IEEE13Node_BusXY.csv` are the public IEEE 13-node OpenDSS test case copied from the OpenDSS mirror. `ieee123_snapshot/` and `ieee123_qsts/` are the public IEEE 123-node OpenDSS model files used for transfer audits. The original source license/commit is recorded in `feeder_manifest.json` and in the project data manifest.

The QSTS master references the public OEDISI profile directory at `../profiles`. The profiles are intentionally excluded from Git because they are third-party bulk files; the local working copy is created from the source project before running `run_ieee123_sequence.py`. The experiment scripts report a missing-profile error rather than silently substituting another profile.

Third-party household files are also excluded from Git. Download URLs and SHA-256 hashes are recorded in `data/processed/ausgrid_manifest.json` and `data/processed/opsd_manifest.json`.

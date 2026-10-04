# Reproducibility and computational provenance (v5)

The release bundle contains the manuscript source, deterministic scripts, processed profile banks, OpenDSS input fixtures, result CSV/JSON files, figures, SHA-256 manifests, and the runtime snapshot in `docs/runtime_environment_v5.txt`. The repository code is MIT-licensed; third-party input notices are in `data/raw/THIRD_PARTY_LICENSES.txt` and `data/raw/ausgrid/README.md`.

## Frozen data and licence provenance

- Ausgrid Solar Home Electricity Data: the public catalog record is [data.gov.au dataset 5ab48b70-5e99-47d3-9193-5c34a2676d93](https://data.gov.au/data/dataset/5ab48b70-5e99-47d3-9193-5c34a2676d93), originally released under Creative Commons Attribution 3.0 Australia. The exact local archive and processed 2012--2013 file are identified by SHA-256 in `data/raw/ausgrid/README.md` and `data/processed/ausgrid_external_2012_2013_strict.json`.
- Open Power System Data Household Data: version `2020-04-15`, landing page [household data package](https://data.open-power-system-data.org/household_data/2020-04-15/), data-license metadata retained with the downloaded source manifest. The local processed file hash is in `data/processed/opsd_profile_bank_v2_manifest.json`.
- IEEE-13 OpenDSS fixture: EPRI OpenDSS test-case files and licence notice are in `data/raw/feeder_manifest.json` and `data/raw/THIRD_PARTY_LICENSES.txt`. The repository MIT licence does not relicense these third-party fixtures.

## Reproduction entry points

Run from the repository root. The commands below write into the declared result directories and do not download private data. In an extracted public snapshot, use the snapshot root as the repository root; absolute paths in this development note are examples from the author workstation and should be replaced with the local Python executable.

```bash
# Unit tests
python -m pytest -q

# Primary 2012--2013 strict audit (parallel chunks; writes a fresh output directory)
python scripts/run_network_recovery_parallel.py \
  --source data/processed/ausgrid_external_2012_2013_strict.npz \
  --out-dir results/repro_primary_rerun_v5 \
  --days 219 --groups 10 --workers 4 --sites 611.3,634.1 \
  --cached-bounds results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv \
  --cached-audit results/network_recovery_external_2012_2013_strict_v4/baseline_zero_audit.csv \
  --normalizer-bank data/processed/ausgrid_profile_bank_v2.npz

# Clustered primary/date-group summaries
python scripts/build_network_recovery_statistics.py

# Calendar-block stratified sensitivity
python scripts/build_block_stratified_statistics.py

# Three-call scalar grid and selected nonlinear replay
python scripts/run_three_call_grid_v1.py \
  --bounds results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv \
  --policy results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv \
  --out-dir results/three_call_grid_recomputed
python scripts/run_three_call_replay_v1.py \
  --rows results/three_call_grid_recomputed/three_call_rows.csv \
  --bounds results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv \
  --source data/processed/ausgrid_external_2012_2013_strict.npz \
  --out-dir results/three_call_replay_recomputed

# Package consistency check
python scripts/verify_final_package.py --version v5 --bundle-dir submission_bundle_v5 --require-metadata

# Public snapshot hash and path audit (after extracting the public ZIP)
python scripts/verify_public_snapshot.py --snapshot .
```

## Timing record

The v5 numerical chunk metadata records inputs, hashes, worker count and output rows but does **not** retain one aggregate wall-clock timing for the historical full AC run. The v6 execution record reports the observed three-call-grid rerun (261.57 s), 40 unit tests (8.24 s) and manuscript build (28 pages); no unsupported total AC runtime is reconstructed. A fresh full rerun should still be wrapped with the host's POSIX timer and its output committed to the bundle, for example:

```bash
/usr/bin/time -p /Users/skzhao/miniconda3/bin/python scripts/run_network_recovery_parallel.py --help 2> results/runtime_help.time
```

Replace `--help` with the frozen full-run arguments only after the run is intentionally repeated. The same timing wrapper should be used for the three-call grid, nonlinear replay, certificate audit and statistics/figure stages. This limitation is disclosed rather than filled with reconstructed timing values.

## Evidence tiers

The two-call and selected three-call schedules are replayed through nonlinear OpenDSS. Capacity, H4--H24, headroom and unselected three-call cells are scalar-dispatch sensitivities under frozen AC bounds. The package metadata and manuscript use these evidence labels consistently.

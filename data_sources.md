# Data sources and provenance

## Feeder models

The pilot uses the IEEE 13-node unbalanced feeder distributed in the OpenDSS mirror. The source file is copied from the public OpenDSS repository with its original license and commit recorded in `data/raw/feeder_manifest.json`. The paper uses new time-series scenarios, new battery placements, and new service/recovery trajectories; no old result arrays are imported.

## Load and PV profiles

The pilot and scale-up use the Ausgrid Solar Home Electricity Data (300 customers, half-hour demand and rooftop PV, 2010--2013). The official Data.gov.au record identifies the dataset and its Creative Commons Attribution 3.0 Australia license. Because the original Ausgrid download page is currently unavailable, the working archive is the May 2026 self-hosted copy documented in `data/raw/ausgrid/README.md`; its SHA-256 is recorded in `data/processed/ausgrid_manifest.json`. A held-out cross-region sanity check from the Open Power System Data household dataset will be added before submission. Because customer meters do not contain feeder topology, the mapping to feeder phases and buses is declared synthetic and stress-tested over multiple placements.

## Data policy

Raw third-party data remain under their source licenses. Derived scenario manifests, deterministic seeds, code, and aggregate results are released under MIT-compatible terms where permitted. A public GitHub/Zenodo record will be added after the authors provide or create an account; no DOI is invented in advance.

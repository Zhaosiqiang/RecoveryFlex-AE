# Raw-input provenance

The bundle includes the small static fixtures used by the reproducibility
tests: `IEEE13Nodeckt.dss`, `IEEELineCodes.dss`, and
`IEEE13Node_BusXY.csv` for the public IEEE 13-node OpenDSS test case, plus
the five files needed by `ieee123_snapshot/`.  Their source URLs, hashes, and
third-party licence notices are recorded in `feeder_manifest.json` and
`THIRD_PARTY_LICENSES.txt`.  These files are input fixtures, not original
project code; the repository MIT licence does not relicense them.

The QSTS master and its OEDISI profile directory are intentionally excluded
from the package because they are not used for the quantitative IEEE-13
results.  The acquisition notes and hashes remain in `ieee123_qsts/manifest.json`.

Third-party household archives are excluded.  The frozen processed profile
banks and their two small chronological index CSVs are included; source
download URLs and SHA-256 hashes remain in
`data/processed/ausgrid_profile_bank_v2_manifest.json`,
`data/processed/opsd_profile_bank_v2_manifest.json`, and the accompanying
`ausgrid/README.md` attribution note.

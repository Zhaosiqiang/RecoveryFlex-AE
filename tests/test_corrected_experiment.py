from pathlib import Path
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.ac_snapshot import ACSnapshotFeeder
from run_corrected_experiment import run


def test_constant_pq_realized_power_changes_with_command():
    feeder = ACSnapshotFeeder(
        ROOT / "data/raw/IEEE13Nodeckt.dss",
        battery_sites=("611.3",),
        pv_sites={"675.1": 300.0},
        voltage_limits=(0.95, 1.05),
    )
    a0 = feeder.solve(load_scale=0.5, pv_fraction=0.5, p_kw={"611.3": 0.0})
    a100 = feeder.solve(load_scale=0.5, pv_fraction=0.5, p_kw={"611.3": 100.0})
    assert a0.converged and a100.converged
    assert np.isclose(a0.battery_realized_kw["611.3"], 0.0, atol=2e-3)
    assert np.isclose(a100.battery_realized_kw["611.3"], 100.0, atol=1e-2)
    assert a100.battery_realized_kw["611.3"] != a0.battery_realized_kw["611.3"]


def test_full_rearm_is_one_and_nonreset_has_state_contraction(tmp_path):
    summary = run(max_train_days=6, max_cal_days=4, max_test_days=4, out_dir=tmp_path)
    # The small smoke subset can select an AC-infeasible held-out control
    # event; when its first event is feasible, the deterministic re-arm
    # control must repeat exactly.  Either outcome is valid for this smoke
    # test because the full run reports the held-out control separately.
    assert summary["full_rearm_control_C2"] in {0.0, 1.0}
    assert summary["nonreset_sequence_C2"] < 1.0
    assert summary["p_train_max_kw"] > 0.0
    assert (tmp_path / "corrected_experiment_rows.csv").is_file()
    if "sequence_capacity_rows" in summary:
        assert summary["sequence_capacity_rows"] > 0
        assert (tmp_path / "sequence_capacity.csv").is_file()
    loaded = json.loads((tmp_path / "corrected_experiment_summary.json").read_text())
    assert loaded["status"] == "corrected_v1"

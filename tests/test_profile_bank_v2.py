from pathlib import Path
import json
import numpy as np
import pandas as pd
import sys
ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
sys.path.insert(0, str(ROOT / "src"))
from recoveryflex.profile_bank import load_bank


def _load(name):
    return np.load(PROCESSED / name, allow_pickle=False)


def test_ausgrid_interval_bank_is_resolved_and_split_disjoint():
    x = _load("ausgrid_profile_bank_v2.npz")
    assert x["load_kw"].ndim == 3 and x["load_kw"].shape[-2:] == (10, 48)
    assert x["pv_kw"].shape == x["load_kw"].shape
    assert np.isfinite(x["load_kw"]).all() and np.isfinite(x["pv_kw"]).all()
    dates, split = x["dates"].astype(str), x["split"].astype(str)
    assert len(set(dates[split == "train"]) & set(dates[split == "test"])) == 0
    assert set(split) == {"train", "cal", "test"}
    assert (x["load_kw"] >= 0).all() and (x["pv_kw"] >= 0).all()


def test_opsd_bank_is_first_difference_kw_and_selected_flags_only():
    x = _load("opsd_profile_bank_v2.npz")
    assert x["load_kw"].shape[1] == 96
    assert x["pv_kw"].shape == x["load_kw"].shape
    assert np.isfinite(x["load_kw"]).all() and np.isfinite(x["pv_kw"]).all()
    assert (x["load_kw"] >= 0).all() and (x["pv_kw"] >= 0).all()
    assert set(x["split"].astype(str)) == {"train", "cal", "test"}
    m = json.loads((PROCESSED / "opsd_profile_bank_v2_manifest.json").read_text())
    assert "cumulative kWh first-differenced" in m["units"]


def test_monthly_test_coverage():
    idx = pd.read_csv(PROCESSED / "ausgrid_profile_bank_v2_index.csv", parse_dates=["date"])
    months = idx.loc[idx.split == "test", "date"].dt.month
    assert set(months.unique()) == set(range(1, 13))


def test_loader_uses_train_only_scales_and_returns_day_interval_group():
    bank = load_bank(PROCESSED / "ausgrid_profile_bank_v2.npz")
    assert bank.load_kw.shape[1:] == (48, 10)
    assert bank.pv_kw.shape == bank.load_kw.shape
    train = bank.split == "train"
    assert np.allclose(bank.load_norm[train].max(axis=(0, 1)), 1.0)
    assert np.allclose(bank.pv_norm[train].max(axis=(0, 1)), 1.0)
    assert np.isfinite(bank.load_norm).all() and np.isfinite(bank.pv_norm).all()

from pathlib import Path

import numpy as np

from recoveryflex.profile_bank import load_bank


ROOT = Path(__file__).resolve().parents[1]


def test_loader_reorders_groups_and_uses_train_only_scales():
    bank = load_bank(ROOT / "data/processed/ausgrid_profile_bank_v2.npz")
    assert bank.load_kw.shape == (365, 48, 10)
    assert bank.pv_kw.shape == bank.load_kw.shape
    train = bank.split == "train"
    assert np.allclose(bank.train_load_scale_kw, bank.load_kw[train].max(axis=(0, 1)))
    assert np.all(bank.load_norm[~train] >= 0)
    assert np.allclose(bank.load_norm[train].max(axis=(0, 1)), 1.0)


def test_loader_adds_single_group_for_opsd():
    bank = load_bank(ROOT / "data/processed/opsd_profile_bank_v2.npz")
    assert bank.load_kw.ndim == 3 and bank.load_kw.shape[2] == 1
    assert bank.interpolation_fraction is not None

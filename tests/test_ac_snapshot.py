from pathlib import Path

import numpy as np
import pytest

from recoveryflex.ac_snapshot import ACSnapshotFeeder


ROOT = Path(__file__).resolve().parents[1]
VOLTAGE = (0.95, 1.05)


def test_ieee13_constant_pq_command_is_measured_and_isolated():
    feeder = ACSnapshotFeeder(
        ROOT / "data/raw/IEEE13Nodeckt.dss",
        battery_sites=("634.1",),
        pv_sites={"675.1": 50.0},
        voltage_limits=VOLTAGE,
        line_loading_limit=1.0,
    )
    a0 = feeder.solve(load_scale=0.5, pv_fraction=0.5, p_kw={"634.1": 0.0})
    a25 = feeder.solve(load_scale=0.5, pv_fraction=0.5, p_kw={"634.1": 25.0})
    a100 = feeder.solve(load_scale=0.5, pv_fraction=0.5, p_kw={"634.1": 100.0})
    assert a0.converged and a25.converged and a100.converged
    assert a25.battery_realized_kw["634.1"] == pytest.approx(25.0, abs=2e-3)
    assert a100.battery_realized_kw["634.1"] == pytest.approx(100.0, abs=1e-2)
    assert a100.battery_realized_kw["634.1"] != pytest.approx(a25.battery_realized_kw["634.1"], abs=1e-2)
    assert a100.voltages_pu and all(v > 0 for v in a100.voltages_pu.values())
    assert all(np.isfinite(v) for v in a100.line_current_ratios.values())


def test_ieee123_valid_sites_and_transformer_ratings():
    feeder = ACSnapshotFeeder(
        ROOT / "data/raw/ieee123_snapshot/master.dss",
        battery_sites=("47.1", "65.2", "79.3"),
        pv_sites={"68.1": 25.0},
        voltage_limits=VOLTAGE,
        line_loading_limit=1.0,
    )
    a = feeder.solve(load_scale=0.5, pv_fraction=0.8, p_kw={"47.1": 20.0, "65.2": -10.0})
    assert a.converged, a.error
    assert all(v > 0 for v in a.voltages_pu.values())
    assert any(k.startswith("transformer.") for k in a.line_current_ratios)
    assert a.battery_realized_kw["47.1"] == pytest.approx(20.0, abs=2e-3)
    assert a.battery_realized_kw["65.2"] == pytest.approx(-10.0, abs=2e-3)


def test_invalid_phase_and_isolated_site_are_rejected():
    with pytest.raises(ValueError, match="not a modeled phase"):
        ACSnapshotFeeder(ROOT / "data/raw/ieee123_snapshot/master.dss", battery_sites=("84.2",))
    # 675 is not an IEEE-123 bus; this catches the old adapter's invalid site.
    with pytest.raises(ValueError, match="unknown bus"):
        ACSnapshotFeeder(ROOT / "data/raw/ieee123_snapshot/master.dss", battery_sites=("675.1",))

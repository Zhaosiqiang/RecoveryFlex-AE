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
    transformer = {k: v for k, v in a100.line_current_ratios.items() if k.startswith("transformer.")}
    assert transformer and max(transformer.values()) > 0.05


def test_command_match_tolerances_are_explicit_and_validated():
    kwargs = dict(
        master_path=ROOT / "data/raw/IEEE13Nodeckt.dss",
        battery_sites=("634.1",),
        pv_sites={"675.1": 50.0},
        voltage_limits=VOLTAGE,
        line_loading_limit=1.0,
        command_tolerance_kw=0.0,
        relative_command_tolerance=0.005,
    )
    feeder = ACSnapshotFeeder(**kwargs)
    assert feeder.relative_command_tolerance == pytest.approx(0.005)
    with pytest.raises(ValueError, match="relative_command_tolerance"):
        ACSnapshotFeeder(**{**kwargs, "relative_command_tolerance": -1.0})
    with pytest.raises(ValueError, match="command_tolerance_kw"):
        ACSnapshotFeeder(**{**kwargs, "command_tolerance_kw": -1.0})


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


def test_surrogates_are_excluded_case_insensitively_and_transformers_are_per_phase():
    feeder = ACSnapshotFeeder(
        ROOT / "data/raw/IEEE13Nodeckt.dss",
        battery_sites=("634.1",),
        pv_sites={"675.1": 50.0},
        voltage_limits=(0.90, 1.10),
        line_loading_limit=100.0,
        transformer_loading_limit=100.0,
    )
    native_names = {name.casefold() for name in feeder._native_load_base}
    assert not any(name.startswith(("batrf", "pvrf")) for name in native_names)
    audit = feeder.solve(load_scale=0.5, pv_fraction=0.5, p_kw={"634.1": 100.0})
    assert audit.converged, audit.error
    phase_keys = [
        key for key in audit.line_current_ratios
        if key.startswith("transformer.") and ".wdg" in key and ".phase" in key
    ]
    assert phase_keys
    assert all(np.isfinite(audit.line_current_ratios[key]) for key in phase_keys)
    aggregate = max(audit.line_current_ratios[key] for key in phase_keys)
    assert audit.max_transformer_loading == pytest.approx(aggregate)
    assert audit.line_current_ratios["transformer.xfm1"] == pytest.approx(
        max(v for k, v in audit.line_current_ratios.items() if k.startswith("transformer.xfm1.wdg"))
    )


def test_snapshot_is_order_independent_with_controls_disabled():
    kwargs = dict(
        master_path=ROOT / "data/raw/IEEE13Nodeckt.dss",
        battery_sites=("634.1",),
        pv_sites={"675.1": 50.0},
        voltage_limits=(0.90, 1.10),
        line_loading_limit=100.0,
        transformer_loading_limit=100.0,
    )
    first = ACSnapshotFeeder(**kwargs)
    low_first = first.solve(0.5, 0.5, {"634.1": 0.0})
    high_after = first.solve(0.5, 0.5, {"634.1": 100.0})
    second = ACSnapshotFeeder(**kwargs)
    high_first = second.solve(0.5, 0.5, {"634.1": 100.0})
    low_after = second.solve(0.5, 0.5, {"634.1": 0.0})
    for left, right in ((low_first, low_after), (high_after, high_first)):
        assert left.converged and right.converged
        # Newton tolerances differ by a few ulps across independent engine
        # contexts; the operating point must still agree well below reporting
        # precision.
        assert left.vmin == pytest.approx(right.vmin, abs=1e-7)
        assert left.vmax == pytest.approx(right.vmax, abs=1e-7)
        assert left.max_line_loading == pytest.approx(right.max_line_loading, abs=1e-7)


def test_failure_classification_names_limiting_line_or_transformer_phase():
    line_limited = ACSnapshotFeeder(
        ROOT / "data/raw/IEEE13Nodeckt.dss",
        battery_sites=("634.1",),
        voltage_limits=(0.90, 1.10),
        line_loading_limit=0.01,
        transformer_loading_limit=100.0,
    ).solve(0.5, 0.0, {"634.1": 0.0})
    assert not line_limited.feasible
    assert any(reason.startswith("line_loading:") for reason in line_limited.failure_reasons)
    assert line_limited.limiting_component.startswith("line.") or line_limited.limiting_component.startswith("transformer.")

    transformer_limited = ACSnapshotFeeder(
        ROOT / "data/raw/IEEE13Nodeckt.dss",
        battery_sites=("634.1",),
        voltage_limits=(0.90, 1.10),
        line_loading_limit=100.0,
        transformer_loading_limit=0.5,
    ).solve(0.5, 0.0, {"634.1": 0.0})
    assert not transformer_limited.feasible
    assert any(
        reason.startswith("transformer_loading:transformer.") and ".wdg" in reason and ".phase" in reason
        for reason in transformer_limited.failure_reasons
    )

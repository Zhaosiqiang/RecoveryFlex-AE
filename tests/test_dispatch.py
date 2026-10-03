from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recoveryflex.dispatch import DispatchInputError, plan_service


def _base_case():
    # Two one-interval calls at t=1 and t=5.  The only useful network
    # charging opportunity before the second call is t=2; t=6 is after the
    # final call and has no charging headroom in the network case.
    return dict(
        charge_limit_kw=[0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        export_limit_kw=[10.0] * 8,
        load_kw=[0.0] * 8,
        service_windows=[(1, 2), (5, 6)],
        energy_kwh=10.0,
        initial_soc=0.5,
        terminal_soc_target=0.5,
        soc_min=0.1,
        soc_max=0.9,
        eta_charge=1.0,
        eta_discharge=1.0,
        dt_h=0.5,
    )


def test_network_lp_couples_multiple_calls_to_time_varying_recovery():
    result = plan_service(**_base_case(), mode="network_lp", terminal_mode="exact")
    assert result.feasible
    # One kWh is available at t=2 (2 kW for 0.5 h), so two calls can each
    # deliver 1 kW while returning to the target.  A static energy-only model
    # can use the same 2 kW charging limit after the second call and offers 2.
    assert result.service_kw == pytest.approx(1.0, abs=1e-7)
    assert result.charge_kw[2] == pytest.approx(2.0)
    assert result.terminal_soc == pytest.approx(0.5)
    assert np.max(result.grid_import_kw) <= 2.0 + 1e-9

    energy_only = plan_service(**_base_case(), mode="energy_only", terminal_mode="exact")
    assert energy_only.feasible
    assert energy_only.service_kw == pytest.approx(6.0, abs=1e-7)
    assert energy_only.service_kw > result.service_kw


def test_fixed_recovery_profile_is_enforced():
    kwargs = dict(
        charge_limit_kw=[2.0] * 6,
        export_limit_kw=[10.0] * 6,
        load_kw=[0.0] * 6,
        service_windows=[(1, 2), (4, 5)],
        energy_kwh=20.0,
        initial_soc=0.5,
        terminal_soc_target=0.5,
        soc_min=0.1,
        soc_max=0.9,
        eta_charge=1.0,
        eta_discharge=1.0,
        dt_h=0.5,
    )
    fixed = plan_service(
        **kwargs,
        mode="fixed_recovery",
        fixed_recovery_kw=[1.0, 0.0, 1.0, 1.0, 0.0, 1.0],
        terminal_mode="exact",
    )
    assert fixed.feasible
    assert fixed.service_kw == pytest.approx(2.0)
    assert np.allclose(fixed.charge_kw, [1.0, 0.0, 1.0, 1.0, 0.0, 1.0])
    assert fixed.terminal_soc == pytest.approx(0.5)


def test_fixed_recovery_ratio_tracks_service_power_and_efficiency():
    kwargs = dict(
        charge_limit_kw=[2.0] * 6,
        export_limit_kw=[10.0] * 6,
        load_kw=[0.0] * 6,
        service_windows=[(1, 2), (4, 5)],
        energy_kwh=20.0,
        initial_soc=0.5,
        terminal_soc_target=0.5,
        soc_min=0.1,
        soc_max=0.9,
        eta_charge=0.9,
        eta_discharge=0.9,
        dt_h=0.5,
    )
    result = plan_service(
        **kwargs,
        mode="fixed_recovery",
        # Four recovery intervals (2 h) must restore one hour of service at
        # eta_c=eta_d=0.9: ratio = 1/(2*eta_c*eta_d).
        fixed_recovery_ratio=1.0 / (2.0 * 0.9 * 0.9),
        terminal_mode="exact",
    )
    assert result.feasible
    # The 2-kW AC recovery limit is binding, giving P=2/ratio=3.24 kW.
    assert result.service_kw == pytest.approx(3.24, rel=1e-6)
    assert np.all(result.charge_kw[[0, 2, 3, 5]] == pytest.approx(2.0))


def test_peak_import_cap_is_enforced_in_service_and_recovery_periods():
    result = plan_service(
        charge_limit_kw=[2.0] * 4,
        export_limit_kw=[10.0] * 4,
        load_kw=[4.0, 8.0, 8.0, 4.0],
        service_windows=[(1, 3)],
        energy_kwh=10.0,
        initial_soc=0.5,
        terminal_soc_target=0.5,
        soc_min=0.1,
        soc_max=0.9,
        peak_import_cap=6.0,
        terminal_mode="exact",
    )
    assert result.feasible
    assert result.service_kw == pytest.approx(2.0)
    assert np.max(result.grid_import_kw) <= 6.0 + 1e-8


def test_myopic_recovery_is_a_declared_short_sighted_baseline():
    kwargs = _base_case()
    lp = plan_service(**kwargs, mode="network_lp", terminal_mode="exact")
    myopic = plan_service(**kwargs, mode="myopic_recovery", terminal_mode="exact")
    assert lp.feasible and myopic.feasible
    # The policy only fills to the next service block and does not anticipate
    # the terminal target before the last call; it therefore cannot use t=2 to
    # reserve energy for the final target when t=6 has no charging opportunity.
    assert myopic.service_kw <= 1e-6
    assert myopic.service_kw < lp.service_kw


def test_validation_rejects_bad_windows_and_missing_fixed_policy():
    kwargs = _base_case()
    bad = dict(kwargs)
    bad["service_windows"] = [(1, 3), (2, 4)]
    with pytest.raises(DispatchInputError):
        plan_service(**bad)
    with pytest.raises(DispatchInputError):
        plan_service(**kwargs, mode="fixed_recovery")
    invalid_efficiency = dict(kwargs)
    invalid_efficiency["eta_charge"] = 0.0
    with pytest.raises(DispatchInputError):
        plan_service(**invalid_efficiency)

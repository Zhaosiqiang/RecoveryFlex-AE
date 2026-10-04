from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recoveryflex.capacity_certificate import capacity_certificate
from recoveryflex.dispatch import plan_service


def _lp(cert, E, *, cbar, exp, service, recovery, p, st=0.5, mode="exact"):
    return plan_service(
        charge_limit_kw=cbar,
        export_limit_kw=exp,
        load_kw=np.zeros(len(cbar)),
        service_windows=service,
        recovery_windows=recovery,
        energy_kwh=E,
        initial_soc=0.5,
        terminal_soc_target=st,
        soc_min=0.1,
        soc_max=1.0,
        eta_charge=1.0,
        eta_discharge=1.0,
        dt_h=0.5,
        mode="network_lp",
        service_power_kw=p,
        terminal_mode=mode,
    )


def test_exact_terminal_capacity_interval_has_both_bounds():
    cert = capacity_certificate(
        1.0, [0.0], [10.0], [(0, 1)], [],
        dt_h=1.0, initial_soc=0.9, terminal_soc_target=0.1,
        soc_min=0.0, soc_max=1.0,
    )
    assert cert.feasible
    assert cert.e_min_kwh == pytest.approx(1.25)
    assert cert.e_max_kwh == pytest.approx(1.25)
    assert cert.lower_witness is not None
    assert cert.upper_witness is not None


def test_at_least_terminal_uses_terminal_lower_soc_only():
    cert = capacity_certificate(
        1.0, [0.0], [10.0], [(0, 1)], [],
        dt_h=1.0, initial_soc=0.9, terminal_soc_target=0.1,
        soc_min=0.0, soc_max=1.0, terminal_mode="at_least",
    )
    assert cert.feasible
    assert cert.e_min_kwh == pytest.approx(1.25)
    assert np.isinf(cert.e_max_kwh)


def test_terminal_charge_requirement_can_create_capacity_upper_bound():
    cert = capacity_certificate(
        0.0, [0.0, 1.0], [10.0, 10.0], [(0, 1)], [(1, 2)],
        dt_h=1.0, initial_soc=0.2, terminal_soc_target=0.8,
        soc_min=0.0, soc_max=1.0,
    )
    assert cert.feasible
    assert cert.e_min_kwh == pytest.approx(0.0)
    assert cert.e_max_kwh == pytest.approx(1.0 / 0.6)
    assert cert.upper_witness is not None
    assert cert.upper_witness.kind == "reachability_upper"


def test_middle_window_cut_beats_prefix_only_bound():
    # Early charge is capped by the SOC ceiling and cannot be carried into the
    # later two-interval demand block.
    cert = capacity_certificate(
        10.0, [100.0, 0.0, 0.0], [100.0] * 3,
        [(1, 3)], [(0, 1)], dt_h=1.0,
        initial_soc=0.0, terminal_soc_target=0.0,
        soc_min=0.0, soc_max=1.0,
    )
    assert cert.feasible
    assert cert.e_min_kwh == pytest.approx(20.0)
    assert cert.lower_witness is not None
    assert (cert.lower_witness.start, cert.lower_witness.end) == (1, 3)


def test_spill_is_allowed_when_charge_headroom_is_surplus():
    cert = capacity_certificate(
        0.0, [100.0], [100.0], [(0, 1)], [],
        dt_h=1.0, initial_soc=0.5, terminal_soc_target=0.5,
        soc_min=0.0, soc_max=1.0,
    )
    assert cert.feasible
    assert cert.e_min_kwh == pytest.approx(0.0)
    assert np.isinf(cert.e_max_kwh)


def test_certificate_matches_plan_service_around_actual_boundary():
    cbar = np.array([0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    exp = np.full(8, 10.0)
    service = [(1, 2), (5, 6)]
    recovery = [(2, 5), (6, 8)]
    p = 1.0
    cert = capacity_certificate(
        p, cbar, exp, service, recovery,
        dt_h=0.5, initial_soc=0.5, terminal_soc_target=0.5,
        soc_min=0.1, soc_max=0.9, energy_efficiency_charge=1.0,
        energy_efficiency_discharge=1.0,
    )
    assert cert.feasible
    below = _lp(cert, cert.e_min_kwh * (1.0 - 1e-5), cbar=cbar, exp=exp,
                service=service, recovery=recovery, p=p)
    at = _lp(cert, cert.e_min_kwh * (1.0 + 1e-5), cbar=cbar, exp=exp,
             service=service, recovery=recovery, p=p)
    assert not below.feasible
    assert at.feasible


def test_export_bound_returns_auditable_witness():
    cert = capacity_certificate(
        5.0, [0.0, 0.0], [4.0, 4.0], [(0, 1)], [], dt_h=1.0,
        initial_soc=0.5, terminal_soc_target=0.5,
    )
    assert not cert.feasible
    assert cert.infeasible_witness is not None
    assert cert.infeasible_witness.kind == "export_bound"


def test_worked_example_has_closed_capacity_interval_and_boundary_labels():
    cert = capacity_certificate(
        1.0,
        [2.0, 2.0],
        [10.0, 10.0],
        [(0, 1)],
        [(1, 2)],
        dt_h=1.0,
        initial_soc=0.8,
        terminal_soc_target=0.9,
        soc_min=0.2,
        soc_max=1.0,
        energy_efficiency_charge=0.9,
        energy_efficiency_discharge=0.8,
    )
    assert cert.feasible
    assert cert.e_min_kwh == pytest.approx(2.0833333333)
    assert cert.e_max_kwh == pytest.approx(5.5)
    assert cert.lower_witness is not None
    assert cert.upper_witness is not None
    assert cert.lower_witness.kind == "reachability_lower"
    assert cert.upper_witness.kind == "reachability_upper"

    # The capacity bounds are constructive: the midpoint is feasible, while
    # either side violates the corresponding cumulative witness in the LP.
    def lp_feasible(E):
        result = plan_service(
            charge_limit_kw=[2.0, 2.0], export_limit_kw=[10.0, 10.0],
            load_kw=[0.0, 0.0], service_windows=[(0, 1)],
            recovery_windows=[(1, 2)], energy_kwh=E,
            initial_soc=0.8, terminal_soc_target=0.9, soc_min=0.2,
            soc_max=1.0, eta_charge=0.9, eta_discharge=0.8, dt_h=1.0,
            mode="network_lp", service_power_kw=1.0, terminal_mode="exact",
        )
        return result.feasible

    assert not lp_feasible(2.0)
    assert lp_feasible(4.0)
    assert not lp_feasible(5.6)


def test_half_open_boundary_and_overlapping_windows_are_explicit():
    cert = capacity_certificate(
        0.0, [0.0, 1.0], [10.0, 10.0], [(0, 1)], [(1, 2)],
        dt_h=1.0, initial_soc=0.5, terminal_soc_target=0.5,
        soc_min=0.0, soc_max=1.0,
    )
    assert cert.feasible
    with pytest.raises(ValueError, match="may not overlap"):
        capacity_certificate(
            0.0, [1.0, 1.0], [10.0, 10.0], [(0, 1)], [(0, 2)],
        )


def test_certificate_matches_fixed_power_lp_on_deterministic_random_instances():
    """Cross-check Eq. (8) against HiGHS beyond the hand-worked examples.

    The test samples the fixed contract and its scalar limits, then compares
    the certificate's closed capacity interval with the independent LP at a
    capacity chosen away from the numerical boundary.  This guards the
    theorem implementation against sign changes in the cumulative cuts while
    keeping the run deterministic and inexpensive.
    """
    rng = np.random.default_rng(1729)
    service = [(1, 2), (4, 5)]
    recovery = [(0, 1), (2, 4), (5, 8)]
    for _ in range(250):
        n = 8
        charge = rng.uniform(0.0, 5.0, n)
        export = rng.uniform(5.0, 12.0, n)
        p = float(rng.uniform(0.0, min(export[1], export[4])))
        energy = float(10.0 ** rng.uniform(0.0, 1.5))
        for terminal_mode in ("exact", "at_least"):
            cert = capacity_certificate(
                p, charge, export, service, recovery,
                dt_h=0.5, initial_soc=0.6, terminal_soc_target=0.6,
                soc_min=0.2, soc_max=1.0,
                energy_efficiency_charge=0.9,
                energy_efficiency_discharge=0.9,
                terminal_mode=terminal_mode,
            )
            lp = plan_service(
                charge, export, np.zeros(n), service,
                recovery_windows=recovery, energy_kwh=energy,
                initial_soc=0.6, terminal_soc_target=0.6,
                soc_min=0.2, soc_max=1.0,
                eta_charge=0.9, eta_discharge=0.9, dt_h=0.5,
                terminal_mode=terminal_mode, mode="network_lp", service_power_kw=p,
            )
            certified = bool(
                cert.feasible
                and cert.e_min_kwh - 1e-7 <= energy <= cert.e_max_kwh + 1e-7
            )
            assert certified == lp.feasible, {
                "iteration": _, "terminal_mode": terminal_mode,
                "capacity": energy, "power": p,
                "certificate": cert.to_dict(), "lp_message": lp.message,
            }

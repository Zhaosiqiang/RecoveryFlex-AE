"""Exact cumulative-window capacity certificates for the scalar SOC model.

For a fixed service power, the dispatch model is a one-dimensional inventory
system.  Service intervals consume ``b_t`` kWh from the state and eligible
recovery intervals can add at most ``a_t`` kWh.  Charging is optional, so
surplus charge headroom may be curtailed at the SOC ceiling.  This module
eliminates the SOC trajectory and returns the exact interval cuts that are
necessary and sufficient for a capacity ``E``.

The certificate deliberately does not run OpenDSS.  It applies to the scalar
dispatch layer after AC bounds have been audited; callers should separately
check the fixed service power against the service export bounds.  The horizon
uses interval indices ``t=0, ..., T-1`` and state nodes ``t=0, ..., T``;
all windows are half-open, so a cumulative cut ``(i, j)`` includes intervals
``i, ..., j-1``.  The implementation checks two inequalities for every
``0 <= i < j <= T`` and therefore has ``O(T^2)`` time and ``O(T)`` working
memory (the cumulative sums are linear; no AC solve is performed here).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from numbers import Integral
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class CapacityCut:
    """One cumulative-window inequality and its residual at a capacity."""

    kind: str
    start: int
    end: int
    left_coefficient: float
    right_constant: float
    capacity: float
    residual: float
    charge_kwh: float
    discharge_kwh: float
    description: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CapacityCertificate:
    """Closed capacity interval and active cumulative-window witnesses."""

    feasible: bool
    e_min_kwh: float
    e_max_kwh: float
    service_power_kw: float
    terminal_mode: str
    lower_witness: CapacityCut | None
    upper_witness: CapacityCut | None
    infeasible_witness: CapacityCut | None
    cuts_checked: int
    message: str

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["lower_witness"] = self.lower_witness.to_dict() if self.lower_witness else None
        result["upper_witness"] = self.upper_witness.to_dict() if self.upper_witness else None
        result["infeasible_witness"] = (
            self.infeasible_witness.to_dict() if self.infeasible_witness else None
        )
        return result


def _mask(windows: Sequence[tuple[int, int]], n: int, name: str) -> np.ndarray:
    if not windows:
        raise ValueError(f"{name} must contain at least one window")
    out = np.zeros(n, dtype=bool)
    for window in windows:
        if len(window) != 2:
            raise ValueError(f"{name} entries must be (start, end)")
        start, end = window
        if not isinstance(start, Integral) or not isinstance(end, Integral):
            raise ValueError(f"{name} endpoints must be integers")
        start, end = int(start), int(end)
        if start < 0 or end > n or start >= end:
            raise ValueError(f"invalid {name} interval {(start, end)} for horizon {n}")
        if np.any(out[start:end]):
            raise ValueError(f"{name} intervals may not overlap")
        out[start:end] = True
    return out


def _series(name: str, values: Sequence[float], n: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or arr.size != n or not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain {n} finite values")
    if np.any(arr < -1e-12):
        raise ValueError(f"{name} must be non-negative")
    return np.maximum(arr, 0.0)


def _cut(
    kind: str,
    i: int,
    j: int,
    coefficient: float,
    constant: float,
    capacity: float,
    charge: float,
    discharge: float,
    description: str,
) -> CapacityCut:
    return CapacityCut(
        kind=kind,
        start=i,
        end=j,
        left_coefficient=float(coefficient),
        right_constant=float(constant),
        capacity=float(capacity),
        residual=float(coefficient * capacity - constant),
        charge_kwh=float(charge),
        discharge_kwh=float(discharge),
        description=description,
    )


def capacity_certificate(
    service_power_kw: float,
    charge_limit_kw: Sequence[float],
    export_limit_kw: Sequence[float],
    service_windows: Sequence[tuple[int, int]],
    recovery_windows: Sequence[tuple[int, int]] | None,
    *,
    energy_efficiency_charge: float = 1.0,
    energy_efficiency_discharge: float = 1.0,
    dt_h: float = 0.5,
    initial_soc: float = 0.8,
    terminal_soc_target: float = 0.8,
    soc_min: float = 0.0,
    soc_max: float = 1.0,
    terminal_mode: str = "exact",
    load_kw: Sequence[float] | None = None,
    peak_import_cap_kw: Sequence[float] | float | None = None,
) -> CapacityCertificate:
    """Return the exact feasible capacity interval for a fixed service power.

    ``a_t`` is ``eta_charge * charge_limit_kw[t] * dt_h`` on recovery
    intervals and zero elsewhere.  ``b_t`` is ``P * dt_h / eta_discharge``
    on service intervals and zero elsewhere.  The returned interval is exact
    for the scalar inventory LP in :func:`recoveryflex.dispatch.plan_service`
    when the same masks and parameters are used.  ``terminal_mode='at_least'``
    uses the lower terminal SOC requirement while retaining the SOC ceiling.
    Endpoint indices are state nodes: ``p_0=q_0=initial_soc`` and, for an
    exact target, ``p_T=q_T=terminal_soc_target``.  The certificate is a
    scalar dispatch result only; it is not a certificate of joint nonlinear
    AC feasibility.

    A non-null PCC cap is supported for a fixed service power by tightening
    eligible charging headroom to ``min(charge_limit, cap-load)`` and checking
    idle/service cap violations.  The strict v5 experiment has no PCC cap and
    should leave this argument unset.
    """
    try:
        p = float(service_power_kw)
        eta_c = float(energy_efficiency_charge)
        eta_d = float(energy_efficiency_discharge)
        dt = float(dt_h)
        s0 = float(initial_soc)
        st = float(terminal_soc_target)
        lo = float(soc_min)
        hi = float(soc_max)
    except (TypeError, ValueError) as exc:
        raise ValueError("capacity certificate parameters must be numeric") from exc
    if not np.isfinite(p) or p < 0:
        raise ValueError("service_power_kw must be finite and non-negative")
    if not (0 < eta_c <= 1 and 0 < eta_d <= 1 and np.isfinite(dt) and dt > 0):
        raise ValueError("efficiencies must lie in (0,1] and dt_h must be positive")
    if not (0 <= lo <= s0 <= hi <= 1 and lo <= st <= hi):
        raise ValueError("SOC values must satisfy the dispatch bounds")
    if terminal_mode not in {"exact", "at_least"}:
        raise ValueError("terminal_mode must be 'exact' or 'at_least'")

    charge = np.asarray(charge_limit_kw, dtype=float)
    export = np.asarray(export_limit_kw, dtype=float)
    if charge.ndim != 1 or charge.size == 0:
        raise ValueError("charge_limit_kw must be a non-empty one-dimensional series")
    n = int(charge.size)
    charge = _series("charge_limit_kw", charge, n)
    export = _series("export_limit_kw", export, n)
    service = _mask(service_windows, n, "service_windows")
    if recovery_windows is None:
        recovery = ~service
    elif not recovery_windows:
        # An explicit empty recovery set is useful for one-call edge cases.
        recovery = np.zeros(n, dtype=bool)
    else:
        recovery = _mask(recovery_windows, n, "recovery_windows")
    if np.any(service & recovery):
        raise ValueError("service and recovery windows may not overlap")
    if not np.any(service):
        raise ValueError("service_windows must contain at least one interval")

    load = np.zeros(n, dtype=float) if load_kw is None else _series("load_kw", load_kw, n)
    cap = None
    if peak_import_cap_kw is not None:
        if np.isscalar(peak_import_cap_kw):
            cap = np.full(n, float(peak_import_cap_kw), dtype=float)
        else:
            cap = _series("peak_import_cap_kw", peak_import_cap_kw, n)
        if not np.all(np.isfinite(cap)):
            raise ValueError("peak_import_cap_kw must be finite")
        service_violation = service & (load - p > cap + 1e-10)
        idle_violation = (~service & ~recovery) & (load > cap + 1e-10)
        if np.any(service_violation | idle_violation):
            t = int(np.flatnonzero(service_violation | idle_violation)[0])
            witness = _cut(
                "pcc_cap",
                t,
                t + 1,
                0.0,
                1.0,
                0.0,
                0.0,
                p * dt if service[t] else 0.0,
                f"PCC/import cap is violated at interval {t}",
            )
            return CapacityCertificate(
                False, np.inf, -np.inf, p, terminal_mode, None, None,
                witness, 0, witness.description,
            )

    if p > float(np.min(export[service])) + 1e-9:
        t = int(np.flatnonzero(service & (export < p - 1e-9))[0])
        witness = _cut(
            "export_bound",
            t,
            t + 1,
            0.0,
            1.0,
            0.0,
            0.0,
            p * dt / eta_d,
            f"service power exceeds audited export limit at interval {t}",
        )
        return CapacityCertificate(
            False, np.inf, -np.inf, p, terminal_mode, None, None,
            witness, 0, witness.description,
        )

    if cap is not None:
        available_charge = np.minimum(charge, np.maximum(0.0, cap - load))
    else:
        available_charge = charge
    a = np.where(recovery, eta_c * available_charge * dt, 0.0)
    b = np.where(service, p * dt / eta_d, 0.0)
    A = np.concatenate(([0.0], np.cumsum(a)))
    B = np.concatenate(([0.0], np.cumsum(b)))

    p_coeff = np.full(n + 1, lo, dtype=float)
    q_coeff = np.full(n + 1, hi, dtype=float)
    p_coeff[0] = q_coeff[0] = s0
    if terminal_mode == "exact":
        p_coeff[n] = q_coeff[n] = st
    else:
        p_coeff[n] = max(lo, st)

    e_min = 0.0
    e_max = np.inf
    lower_witness: CapacityCut | None = None
    upper_witness: CapacityCut | None = None
    infeasible_witness: CapacityCut | None = None
    cuts_checked = 0
    tol = 1e-10
    for i in range(n):
        for j in range(i + 1, n + 1):
            cuts_checked += 2
            Aij = float(A[j] - A[i])
            Bij = float(B[j] - B[i])
            # Monotonicity: L_i <= U_j, or (p_i-q_j)E <= B_ij.
            mcoef = float(p_coeff[i] - q_coeff[j])
            if mcoef > tol:
                bound = Bij / mcoef
                candidate = _cut(
                    "monotonicity_upper", i, j, mcoef, Bij, bound, Aij, Bij,
                    "earlier SOC lower bound must be reachable below the later SOC ceiling",
                )
                if bound < e_max:
                    e_max, upper_witness = bound, candidate
                if bound < -tol and infeasible_witness is None:
                    infeasible_witness = candidate

            # Reachability: L_j <= U_i + A_ij, or
            # (p_j-q_i)E <= A_ij-B_ij.
            rcoef = float(p_coeff[j] - q_coeff[i])
            rhs = Aij - Bij
            if rcoef < -tol:
                bound = (Bij - Aij) / (-rcoef)
                if bound > e_min:
                    candidate = _cut(
                        "reachability_lower", i, j, rcoef, rhs, bound, Aij, Bij,
                        "interval discharge deficit exceeds usable SOC bandwidth",
                    )
                    e_min, lower_witness = bound, candidate
            elif rcoef > tol:
                bound = rhs / rcoef
                candidate = _cut(
                    "reachability_upper", i, j, rcoef, rhs, bound, Aij, Bij,
                    "finite charging headroom must reach the later terminal/SOC lower bound",
                )
                if rhs < -tol and infeasible_witness is None:
                    infeasible_witness = candidate
                if bound < e_max:
                    e_max, upper_witness = bound, candidate
            elif rhs < -tol and infeasible_witness is None:
                infeasible_witness = _cut(
                    "reachability_infeasible", i, j, rcoef, rhs, 0.0, Aij, Bij,
                    "zero SOC bandwidth cannot cover the interval discharge deficit",
                )

    if infeasible_witness is not None or e_min > e_max + 1e-8:
        if infeasible_witness is None:
            infeasible_witness = _cut(
                "capacity_interval_empty", 0, n, 0.0, e_max - e_min, e_min, A[-1], B[-1],
                "lower and upper capacity bounds do not overlap",
            )
        return CapacityCertificate(False, float(e_min), float(e_max), p, terminal_mode,
                                   lower_witness, upper_witness, infeasible_witness,
                                   cuts_checked, infeasible_witness.description)

    return CapacityCertificate(True, float(e_min), float(e_max), p, terminal_mode,
                               lower_witness, upper_witness, None, cuts_checked,
                               "all cumulative-window cuts are feasible")


__all__ = ["CapacityCut", "CapacityCertificate", "capacity_certificate"]

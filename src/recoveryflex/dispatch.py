"""Chronological BESS service and recovery planning.

The planner in this module is deliberately independent of the legacy pilot
scripts.  It works with a time series of *already audited* battery-side
charging and export limits.  A service contract is represented by a constant
export ``P`` in one or more half-open windows.  Outside those windows the
planner may charge, but it does not invent additional discharge or market
arbitrage.  This keeps the experiment focused on whether a DSO can recover
energy before the next guaranteed service call.

``network_lp`` maximizes ``P`` with a linear program.  ``fixed_recovery``
keeps a prescribed recovery profile or recovery ratio.  ``myopic_recovery``
uses a deliberately short-sighted policy (charge only toward the next service
block, and toward the terminal target after the last block).  ``energy_only``
replaces time-varying network limits with constant nameplate limits and is a
counterfactual, not a network-feasible offer.

Sign convention: load and PCC import are positive; battery export is positive;
charging is represented by a non-negative ``charge_kw`` variable.  The battery
energy recurrence is

    e[t+1] = e[t] + eta_charge * charge[t] * dt
                     - discharge[t] * dt / eta_discharge.

The source values should be AC-feasible limits for the same operating point;
this module does not run a power-flow solver.

Index convention: a horizon with ``n`` intervals has intervals ``0`` through
``n-1`` and state nodes ``0`` through ``n``.  All service and recovery windows
are half-open ``(start, end)`` index intervals.  The recurrence therefore
uses the bound at interval ``t`` to map state node ``t`` to node ``t+1``.
The ``network_lp`` endpoint is obtained from one linear programme with
``O(n)`` variables and constraints (numerical complexity is delegated to the
HiGHS LP solver); the cumulative-window certificate in
``capacity_certificate`` is the independent ``O(n^2)`` scalar audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal, Sequence

import numpy as np
from scipy.optimize import linprog


Mode = Literal["network_lp", "lp", "fixed_recovery", "myopic_recovery", "energy_only"]
TerminalMode = Literal["at_least", "exact"]


@dataclass(frozen=True)
class DispatchResult:
    """A service frontier and one corresponding chronological dispatch."""

    mode: str
    feasible: bool
    service_kw: float
    charge_kw: np.ndarray
    discharge_kw: np.ndarray
    energy_kwh: np.ndarray
    soc: np.ndarray
    grid_import_kw: np.ndarray
    status: int | None
    message: str

    @property
    def terminal_soc(self) -> float:
        """Terminal state of charge, or NaN when the LP was infeasible."""
        if self.energy_kwh.size == 0 or not np.isfinite(self.energy_kwh[-1]):
            return float("nan")
        return float(self.soc[-1])


class DispatchInputError(ValueError):
    """Raised when a dispatch contract is internally inconsistent."""


def _vector(name: str, values: Sequence[float], n: int, *, nonnegative: bool) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or arr.size != n:
        raise DispatchInputError(f"{name} must contain exactly {n} values")
    if not np.all(np.isfinite(arr)):
        raise DispatchInputError(f"{name} must be finite")
    if nonnegative and np.any(arr < -1e-12):
        raise DispatchInputError(f"{name} must be non-negative")
    return arr.copy()


def _optional_cap(name: str, value: float | Sequence[float] | None, n: int) -> np.ndarray | None:
    if value is None:
        return None
    if np.isscalar(value):
        x = float(value)
        if not np.isfinite(x):
            raise DispatchInputError(f"{name} must be finite")
        return np.full(n, x, dtype=float)
    return _vector(name, value, n, nonnegative=True)


def _service_mask(service_windows: Sequence[tuple[int, int]], n: int) -> np.ndarray:
    """Convert half-open ``(start, end)`` windows into a non-overlapping mask."""
    if not service_windows:
        raise DispatchInputError("service_windows must contain at least one window")
    mask = np.zeros(n, dtype=bool)
    for window in service_windows:
        if len(window) != 2:
            raise DispatchInputError("each service window must be (start, end)")
        start, end = window
        if not isinstance(start, Integral) or not isinstance(end, Integral):
            raise DispatchInputError("service window endpoints must be integers")
        start, end = int(start), int(end)
        if start < 0 or end > n or start >= end:
            raise DispatchInputError(f"invalid service window {(start, end)} for horizon {n}")
        if np.any(mask[start:end]):
            raise DispatchInputError("service windows may not overlap")
        mask[start:end] = True
    return mask


def _empty_result(mode: str, n: int, load: np.ndarray, message: str, status: int | None = None) -> DispatchResult:
    nan_energy = np.full(n + 1, np.nan, dtype=float)
    return DispatchResult(
        mode=mode,
        feasible=False,
        service_kw=0.0,
        charge_kw=np.zeros(n, dtype=float),
        discharge_kw=np.zeros(n, dtype=float),
        energy_kwh=nan_energy,
        soc=np.full(n + 1, np.nan, dtype=float),
        grid_import_kw=np.asarray(load, dtype=float).copy(),
        status=status,
        message=message,
    )


def _result_from_solution(
    mode: str,
    x: np.ndarray,
    n: int,
    service_mask: np.ndarray,
    load: np.ndarray,
    energy_kwh: float,
) -> DispatchResult:
    p = max(0.0, float(x[0]))
    charge = np.maximum(0.0, np.asarray(x[1 : 1 + n], dtype=float))
    energy = np.asarray(x[1 + n : 1 + n + n + 1], dtype=float)
    discharge = np.where(service_mask, p, 0.0)
    grid = load + charge - discharge
    soc = energy / energy_kwh
    return DispatchResult(
        mode=mode,
        feasible=True,
        service_kw=p,
        charge_kw=charge,
        discharge_kw=discharge,
        energy_kwh=energy,
        soc=soc,
        grid_import_kw=grid,
        status=0,
        message="Optimization terminated successfully",
    )


def _solve_lp(
    *,
    mode: str,
    charge_limit: np.ndarray,
    export_limit: np.ndarray,
    load: np.ndarray,
    service_mask: np.ndarray,
    energy_kwh: float,
    initial_soc: float,
    terminal_soc_target: float,
    terminal_mode: TerminalMode,
    soc_min: float,
    soc_max: float,
    eta_charge: float,
    eta_discharge: float,
    dt_h: float,
    peak_cap: np.ndarray | None,
    recovery_mask: np.ndarray | None = None,
    fixed_profile: np.ndarray | None = None,
    fixed_ratio: float | None = None,
    fixed_recovery_mask: np.ndarray | None = None,
    service_power_kw: float | None = None,
) -> DispatchResult:
    n = load.size
    p_upper = float(np.min(export_limit[service_mask]))
    if p_upper < -1e-12:
        return _empty_result(mode, n, load, "negative service export limit")

    # x = [P, charge[0:n], energy[0:n+1]].
    p_idx = 0
    c_idx = 1
    e_idx = 1 + n
    nvar = e_idx + n + 1
    objective = np.zeros(nvar, dtype=float)
    if service_power_kw is None:
        objective[p_idx] = -1.0  # linprog minimizes, so maximize P.
    lower_energy = energy_kwh * soc_min
    upper_energy = energy_kwh * soc_max
    if service_power_kw is None:
        p_bounds = (0.0, p_upper)
    else:
        p_fixed = float(service_power_kw)
        if not np.isfinite(p_fixed) or p_fixed < -1e-12:
            return _empty_result(mode, n, load, "service_power_kw must be finite and non-negative")
        if p_fixed > p_upper + 1e-9:
            return _empty_result(mode, n, load, "fixed service power exceeds an audited export limit")
        p_bounds = (max(0.0, p_fixed), max(0.0, p_fixed))
    bounds: list[tuple[float | None, float | None]] = [p_bounds]
    for t in range(n):
        if service_mask[t]:
            bounds.append((0.0, 0.0))
        elif recovery_mask is not None and not recovery_mask[t]:
            # A declared recovery mask makes the contract's action window
            # explicit. Intervals before the first call are then idle rather
            # than an unreported pre-charge opportunity.
            bounds.append((0.0, 0.0))
        elif fixed_profile is not None:
            bounds.append((float(fixed_profile[t]), float(fixed_profile[t])))
        elif fixed_ratio is not None and (fixed_recovery_mask is None or fixed_recovery_mask[t]):
            bounds.append((0.0, float(charge_limit[t])))
        else:
            bounds.append((0.0, float(charge_limit[t])))
    bounds.extend([(lower_energy, upper_energy)] * (n + 1))

    a_eq: list[np.ndarray] = []
    b_eq: list[float] = []
    initial = np.zeros(nvar, dtype=float)
    initial[e_idx] = 1.0
    a_eq.append(initial)
    b_eq.append(energy_kwh * initial_soc)
    for t in range(n):
        row = np.zeros(nvar, dtype=float)
        row[e_idx + t + 1] = 1.0
        row[e_idx + t] = -1.0
        row[c_idx + t] = -eta_charge * dt_h
        row[p_idx] = (dt_h / eta_discharge) if service_mask[t] else 0.0
        a_eq.append(row)
        b_eq.append(0.0)

    if terminal_mode == "exact":
        row = np.zeros(nvar, dtype=float)
        row[e_idx + n] = 1.0
        a_eq.append(row)
        b_eq.append(energy_kwh * terminal_soc_target)

    # A prescribed fixed ratio means c[t] = fixed_ratio * P in every
    # recovery period.  It is linear because P is a decision variable.
    if fixed_ratio is not None:
        for t in range(n):
            if service_mask[t] or (fixed_recovery_mask is not None and not fixed_recovery_mask[t]):
                # Outside declared recovery windows, charging is fixed at
                # zero; the contract does not silently pre-charge elsewhere.
                row = np.zeros(nvar, dtype=float)
                row[c_idx + t] = 1.0
                a_eq.append(row)
                b_eq.append(0.0)
                continue
            row = np.zeros(nvar, dtype=float)
            row[c_idx + t] = 1.0
            row[p_idx] = -float(fixed_ratio)
            a_eq.append(row)
            b_eq.append(0.0)

    a_ub: list[np.ndarray] = []
    b_ub: list[float] = []
    if terminal_mode == "at_least":
        row = np.zeros(nvar, dtype=float)
        row[e_idx + n] = -1.0
        a_ub.append(row)
        b_ub.append(-energy_kwh * terminal_soc_target)

    if peak_cap is not None:
        for t in range(n):
            # load[t] + charge[t] - service_mask[t]*P <= peak_cap[t].
            row = np.zeros(nvar, dtype=float)
            row[c_idx + t] = 1.0
            if service_mask[t]:
                row[p_idx] = -1.0
            a_ub.append(row)
            b_ub.append(float(peak_cap[t] - load[t]))

    result = linprog(
        objective,
        A_ub=np.asarray(a_ub) if a_ub else None,
        b_ub=np.asarray(b_ub) if b_ub else None,
        A_eq=np.asarray(a_eq),
        b_eq=np.asarray(b_eq),
        bounds=bounds,
        method="highs",
    )
    if not result.success or result.x is None:
        return _empty_result(mode, n, load, str(result.message), int(result.status))
    return _result_from_solution(mode, result.x, n, service_mask, load, energy_kwh)


def _myopic_rollout(
    p: float,
    *,
    charge_limit: np.ndarray,
    export_limit: np.ndarray,
    load: np.ndarray,
    service_mask: np.ndarray,
    energy_kwh: float,
    initial_soc: float,
    terminal_soc_target: float,
    soc_min: float,
    soc_max: float,
    eta_charge: float,
    eta_discharge: float,
    dt_h: float,
    peak_cap: np.ndarray | None,
    recovery_mask: np.ndarray | None,
    terminal_mode: TerminalMode,
) -> tuple[bool, np.ndarray, np.ndarray, np.ndarray, str]:
    """Roll out the declared short-sighted recovery policy for one P."""
    n = load.size
    # A failed rollout can return before all intervals have been propagated.
    # Initialise the tail explicitly so the exact-terminal binary search never
    # branches on uninitialised memory when it inspects ``energy[-1]``.
    energy = np.full(n + 1, np.nan, dtype=float)
    charge = np.zeros(n, dtype=float)
    discharge = np.where(service_mask, p, 0.0)
    energy[0] = energy_kwh * initial_soc
    lo = energy_kwh * soc_min
    hi = energy_kwh * soc_max
    for t in range(n):
        if service_mask[t]:
            if p > export_limit[t] + 1e-8:
                return False, charge, discharge, energy, f"service export limit at t={t}"
            if peak_cap is not None and load[t] - p > peak_cap[t] + 1e-8:
                return False, charge, discharge, energy, f"peak import cap at t={t}"
            energy[t + 1] = energy[t] - p * dt_h / eta_discharge
        else:
            if recovery_mask is not None and not recovery_mask[t]:
                # No recovery action is permitted outside the declared
                # windows. This is especially important before the first
                # service call, which is supported by the initial SOC.
                if peak_cap is not None and load[t] > peak_cap[t] + 1e-8:
                    return False, charge, discharge, energy, f"peak import cap at idle t={t}"
                energy[t + 1] = energy[t]
                continue
            # The policy looks only at the next contiguous service block.  It
            # does not reserve energy for a later terminal target until there
            # is no future service block; this is intentionally a baseline.
            future = np.flatnonzero(service_mask[t + 1 :])
            if future.size:
                first = t + 1 + int(future[0])
                block = 0
                while first + block < n and service_mask[first + block]:
                    block += 1
                target = lo + p * block * dt_h / eta_discharge
            else:
                target = energy_kwh * terminal_soc_target
            available = float(charge_limit[t])
            if peak_cap is not None:
                available = min(available, float(peak_cap[t] - load[t]))
            if available < -1e-8:
                return False, charge, discharge, energy, f"PCC cap already violated at t={t}"
            available = max(0.0, available)
            available = min(available, max(0.0, (hi - energy[t]) / (eta_charge * dt_h)))
            desired = max(0.0, (target - energy[t]) / (eta_charge * dt_h))
            charge[t] = min(available, desired)
            energy[t + 1] = energy[t] + eta_charge * charge[t] * dt_h
        if energy[t + 1] < lo - 1e-7 or energy[t + 1] > hi + 1e-7:
            return False, charge, discharge, energy, f"SOC bound at t={t}"
    target_energy = energy_kwh * terminal_soc_target
    if terminal_mode == "exact":
        if abs(energy[-1] - target_energy) > 1e-7:
            return False, charge, discharge, energy, "exact terminal SOC target"
    elif energy[-1] < target_energy - 1e-7:
        return False, charge, discharge, energy, "terminal SOC target"
    return True, charge, discharge, energy, "myopic rollout feasible"


def _solve_myopic(
    *,
    charge_limit: np.ndarray,
    export_limit: np.ndarray,
    load: np.ndarray,
    service_mask: np.ndarray,
    energy_kwh: float,
    initial_soc: float,
    terminal_soc_target: float,
    soc_min: float,
    soc_max: float,
    eta_charge: float,
    eta_discharge: float,
    dt_h: float,
    peak_cap: np.ndarray | None,
    recovery_mask: np.ndarray | None,
    terminal_mode: TerminalMode,
) -> DispatchResult:
    n = load.size
    upper = float(np.min(export_limit[service_mask]))
    rollout_terminal_mode = "at_least" if terminal_mode == "exact" else terminal_mode
    good, _, _, _, message = _myopic_rollout(
        0.0,
        charge_limit=charge_limit,
        export_limit=export_limit,
        load=load,
        service_mask=service_mask,
        energy_kwh=energy_kwh,
        initial_soc=initial_soc,
        terminal_soc_target=terminal_soc_target,
        soc_min=soc_min,
        soc_max=soc_max,
        eta_charge=eta_charge,
        eta_discharge=eta_discharge,
        dt_h=dt_h,
        peak_cap=peak_cap,
        recovery_mask=recovery_mask,
        terminal_mode=rollout_terminal_mode,
    )
    if not good:
        return _empty_result("myopic_recovery", n, load, message)
    lo, hi = 0.0, upper
    if terminal_mode == "exact":
        # Exact terminal SOC defines a root rather than a monotone feasible
        # interval. Locate the largest service power whose greedy rollout
        # returns to the target, while retaining all SOC/network checks.
        target = energy_kwh * terminal_soc_target
        for _ in range(70):
            mid = 0.5 * (lo + hi)
            good, _, _, energy, _ = _myopic_rollout(
                mid, charge_limit=charge_limit, export_limit=export_limit,
                load=load, service_mask=service_mask, energy_kwh=energy_kwh,
                initial_soc=initial_soc, terminal_soc_target=terminal_soc_target,
                soc_min=soc_min, soc_max=soc_max, eta_charge=eta_charge,
                eta_discharge=eta_discharge, dt_h=dt_h, peak_cap=peak_cap,
                recovery_mask=recovery_mask, terminal_mode="at_least",
            )
            if not good:
                # A failed rollout is an infeasible upper bracket.  Its
                # unpropagated tail is intentionally NaN and must not be used
                # to choose the bracket direction.
                hi = mid
                continue
            residual = energy[-1] - target
            if abs(residual) <= 1e-8:
                lo = mid
                continue
            if residual > 0:
                lo = mid
            else:
                hi = mid
        good, charge, discharge, energy, message = _myopic_rollout(
            lo, charge_limit=charge_limit, export_limit=export_limit,
            load=load, service_mask=service_mask, energy_kwh=energy_kwh,
            initial_soc=initial_soc, terminal_soc_target=terminal_soc_target,
            soc_min=soc_min, soc_max=soc_max, eta_charge=eta_charge,
            eta_discharge=eta_discharge, dt_h=dt_h, peak_cap=peak_cap,
            recovery_mask=recovery_mask, terminal_mode="exact",
        )
        if not good:
            return _empty_result("myopic_recovery", n, load, message)
        return DispatchResult(mode="myopic_recovery", feasible=True,
                              service_kw=float(lo), charge_kw=charge,
                              discharge_kw=discharge, energy_kwh=energy,
                              soc=energy / energy_kwh, grid_import_kw=load + charge - discharge,
                              status=0, message=message)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        good, *_ = _myopic_rollout(
            mid,
            charge_limit=charge_limit,
            export_limit=export_limit,
            load=load,
            service_mask=service_mask,
            energy_kwh=energy_kwh,
            initial_soc=initial_soc,
            terminal_soc_target=terminal_soc_target,
            soc_min=soc_min,
            soc_max=soc_max,
            eta_charge=eta_charge,
            eta_discharge=eta_discharge,
            dt_h=dt_h,
            peak_cap=peak_cap,
            recovery_mask=recovery_mask,
            terminal_mode=rollout_terminal_mode,
        )
        if good:
            lo = mid
        else:
            hi = mid
    good, charge, discharge, energy, message = _myopic_rollout(
        lo,
        charge_limit=charge_limit,
        export_limit=export_limit,
        load=load,
        service_mask=service_mask,
        energy_kwh=energy_kwh,
        initial_soc=initial_soc,
        terminal_soc_target=terminal_soc_target,
        soc_min=soc_min,
        soc_max=soc_max,
        eta_charge=eta_charge,
        eta_discharge=eta_discharge,
        dt_h=dt_h,
        peak_cap=peak_cap,
        recovery_mask=recovery_mask,
        terminal_mode=terminal_mode,
    )
    if not good:
        return _empty_result("myopic_recovery", n, load, message)
    return DispatchResult(
        mode="myopic_recovery",
        feasible=True,
        service_kw=float(lo),
        charge_kw=charge,
        discharge_kw=discharge,
        energy_kwh=energy,
        soc=energy / energy_kwh,
        grid_import_kw=load + charge - discharge,
        status=0,
        message=message,
    )


def plan_service(
    charge_limit_kw: Sequence[float],
    export_limit_kw: Sequence[float],
    load_kw: Sequence[float],
    service_windows: Sequence[tuple[int, int]],
    *,
    energy_kwh: float,
    initial_soc: float,
    terminal_soc_target: float,
    soc_min: float = 0.0,
    soc_max: float = 1.0,
    eta_charge: float = 1.0,
    eta_discharge: float = 1.0,
    dt_h: float = 0.5,
    peak_import_cap: float | Sequence[float] | None = None,
    mode: Mode = "network_lp",
    fixed_recovery_kw: float | Sequence[float] | None = None,
    fixed_recovery_ratio: float | None = None,
    recovery_windows: Sequence[tuple[int, int]] | None = None,
    service_power_kw: float | None = None,
    nominal_charge_kw: float | None = None,
    nominal_export_kw: float | None = None,
    terminal_mode: TerminalMode = "at_least",
) -> DispatchResult:
    """Maximize a constant export service across chronological windows.

    Parameters use kW, kWh, hours, and fractional SOC.  ``service_windows``
    are half-open index intervals, e.g. ``[(4, 8), (20, 24)]``. Charging is
    forbidden during service windows. When ``recovery_windows`` is supplied,
    charging is also forbidden outside those declared recovery intervals; this
    is the contract used by the strict external experiment.

    ``network_lp`` (or ``lp``) optimizes recovery against the supplied
    time-varying AC limits. ``fixed_recovery`` requires either a full
    ``fixed_recovery_kw`` profile or ``fixed_recovery_ratio`` (charge power as
    a multiple of ``P`` in every recovery interval). If no explicit
    ``recovery_windows`` mask is supplied, every non-service interval is
    recovery-eligible; the strict experiment supplies the half-open mask
    explicitly. ``myopic_recovery`` performs a binary search around the
    short-sighted rollout described in the module docstring. ``energy_only``
    uses constant nominal limits, defaulting to the maxima of the supplied
    arrays, and removes the PCC cap.
    """
    mode = str(mode)
    if mode not in {"network_lp", "lp", "fixed_recovery", "myopic_recovery", "energy_only"}:
        raise DispatchInputError(f"unknown mode {mode!r}")
    try:
        e = float(energy_kwh)
        s0 = float(initial_soc)
        st = float(terminal_soc_target)
        smin = float(soc_min)
        smax = float(soc_max)
        ec = float(eta_charge)
        ed = float(eta_discharge)
        dt = float(dt_h)
    except (TypeError, ValueError) as exc:
        raise DispatchInputError("energy and efficiency parameters must be numeric") from exc
    if not np.isfinite(e) or e <= 0:
        raise DispatchInputError("energy_kwh must be positive")
    if not (0 < ec <= 1 and 0 < ed <= 1):
        raise DispatchInputError("efficiencies must lie in (0, 1]")
    if not np.isfinite(dt) or dt <= 0:
        raise DispatchInputError("dt_h must be positive")
    if not (0 <= smin <= s0 <= smax <= 1):
        raise DispatchInputError("SOC values must satisfy soc_min <= initial <= soc_max")
    if not (smin <= st <= smax):
        raise DispatchInputError("terminal_soc_target must lie within SOC bounds")
    load = np.asarray(load_kw, dtype=float)
    if load.ndim != 1 or load.size == 0:
        raise DispatchInputError("load_kw must be a non-empty one-dimensional series")
    if not np.all(np.isfinite(load)):
        raise DispatchInputError("load_kw must be finite")
    n = int(load.size)
    charge = _vector("charge_limit_kw", charge_limit_kw, n, nonnegative=True)
    export = _vector("export_limit_kw", export_limit_kw, n, nonnegative=True)
    mask = _service_mask(service_windows, n)
    peak = _optional_cap("peak_import_cap", peak_import_cap, n)
    if terminal_mode not in {"at_least", "exact"}:
        raise DispatchInputError(f"unknown terminal_mode {terminal_mode!r}")
    if service_power_kw is not None:
        try:
            service_power_kw = float(service_power_kw)
        except (TypeError, ValueError) as exc:
            raise DispatchInputError("service_power_kw must be numeric") from exc
        if not np.isfinite(service_power_kw) or service_power_kw < 0:
            raise DispatchInputError("service_power_kw must be finite and non-negative")
        if mode == "myopic_recovery" or mode == "energy_only":
            raise DispatchInputError("service_power_kw is supported only for LP modes")
    if fixed_recovery_kw is not None and fixed_recovery_ratio is not None:
        raise DispatchInputError("provide fixed_recovery_kw or fixed_recovery_ratio, not both")
    if fixed_recovery_ratio is not None:
        fixed_recovery_ratio = float(fixed_recovery_ratio)
        if not np.isfinite(fixed_recovery_ratio) or fixed_recovery_ratio < 0:
            raise DispatchInputError("fixed_recovery_ratio must be finite and non-negative")
    fixed_recovery_mask = None
    if recovery_windows is not None:
        fixed_recovery_mask = _service_mask(recovery_windows, n)
        if np.any(fixed_recovery_mask & mask):
            raise DispatchInputError("recovery windows may not overlap service windows")
    fixed_profile: np.ndarray | None = None
    if fixed_recovery_kw is not None:
        if np.isscalar(fixed_recovery_kw):
            x = float(fixed_recovery_kw)
            if not np.isfinite(x) or x < 0:
                raise DispatchInputError("fixed_recovery_kw must be non-negative")
            active = ~mask if fixed_recovery_mask is None else fixed_recovery_mask
            fixed_profile = np.where(active, x, 0.0)
        else:
            fixed_profile = _vector("fixed_recovery_kw", fixed_recovery_kw, n, nonnegative=True)
        if np.any(fixed_profile[mask] > 1e-12):
            raise DispatchInputError("fixed recovery charging must be zero during service windows")
        if fixed_recovery_mask is not None and np.any(fixed_profile[~(fixed_recovery_mask | mask)] > 1e-12):
            raise DispatchInputError("fixed recovery profile must be zero outside declared recovery windows")
        if np.any(fixed_profile > charge + 1e-9):
            # This is an input error, rather than an optimization failure: the
            # fixed policy is physically impossible under the supplied AC cap.
            raise DispatchInputError("fixed recovery profile exceeds a charging limit")
    if mode == "fixed_recovery" and fixed_profile is None and fixed_recovery_ratio is None:
        raise DispatchInputError("fixed_recovery requires a profile or ratio")
    if mode != "fixed_recovery" and (fixed_profile is not None or fixed_recovery_ratio is not None):
        raise DispatchInputError("fixed recovery settings require mode='fixed_recovery'")
    if mode == "energy_only":
        c_nom = float(np.max(charge) if nominal_charge_kw is None else nominal_charge_kw)
        p_nom = float(np.max(export) if nominal_export_kw is None else nominal_export_kw)
        if not np.isfinite(c_nom) or c_nom < 0 or not np.isfinite(p_nom) or p_nom < 0:
            raise DispatchInputError("nominal energy-only limits must be finite and non-negative")
        return _solve_lp(
            mode="energy_only",
            charge_limit=np.full(n, c_nom),
            export_limit=np.full(n, p_nom),
            load=load,
            service_mask=mask,
            energy_kwh=e,
            initial_soc=s0,
            terminal_soc_target=st,
            terminal_mode=terminal_mode,
            soc_min=smin,
            soc_max=smax,
            eta_charge=ec,
            eta_discharge=ed,
            dt_h=dt,
            peak_cap=None,
            recovery_mask=fixed_recovery_mask,
        )
    if mode == "myopic_recovery":
        return _solve_myopic(
            charge_limit=charge,
            export_limit=export,
            load=load,
            service_mask=mask,
            energy_kwh=e,
            initial_soc=s0,
            terminal_soc_target=st,
            soc_min=smin,
            soc_max=smax,
            eta_charge=ec,
            eta_discharge=ed,
            dt_h=dt,
            peak_cap=peak,
            recovery_mask=fixed_recovery_mask,
            terminal_mode=terminal_mode,
        )
    return _solve_lp(
        mode="fixed_recovery" if mode == "fixed_recovery" else "network_lp",
        charge_limit=charge,
        export_limit=export,
        load=load,
        service_mask=mask,
        energy_kwh=e,
        initial_soc=s0,
        terminal_soc_target=st,
        terminal_mode=terminal_mode,
        soc_min=smin,
        soc_max=smax,
        eta_charge=ec,
        eta_discharge=ed,
        dt_h=dt,
        peak_cap=peak,
        recovery_mask=fixed_recovery_mask,
        fixed_profile=fixed_profile,
        fixed_ratio=fixed_recovery_ratio if mode == "fixed_recovery" else None,
        fixed_recovery_mask=fixed_recovery_mask if mode == "fixed_recovery" else None,
        service_power_kw=service_power_kw,
    )


__all__ = ["DispatchInputError", "DispatchResult", "plan_service"]

"""Candidate service--recovery envelopes and telemetry-conditioned margins."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass
class BatterySpec:
    power_kw: float = 150.0
    energy_kwh: float = 300.0
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    soc_min: float = 0.05
    soc_max: float = 0.95
    soc_initial: float = 0.70
    soc_target: float = 0.70

@dataclass
class Offer:
    site: str
    service_kw: float
    duration_h: float
    recovery_h: float
    load_scale: float
    pv_fraction: float
    telemetry: float
    forecast_error: float
    trajectory_kw: list[float]
    soc_path: list[float]
    candidate_feasible: bool
    reason: str = ""


def robust_margin(telemetry: float, forecast_error: float, base: float = 0.004) -> float:
    """Voltage margin used by the reduced-order candidate model.

    More telemetry shrinks the posterior uncertainty term. The AC audit remains
    the final test, so this function is deliberately transparent and tunable.
    """
    return float(base + forecast_error * (1.0 - 0.75 * telemetry))


def soc_rollout(service_kw: float, duration_h: float, recovery_h: float, dt_h: float,
                spec: BatterySpec) -> tuple[list[float], bool]:
    n_service = max(1, int(round(duration_h / dt_h)))
    n_recovery = max(1, int(round(recovery_h / dt_h)))
    # export/discharge during service, then charge at the inverter limit.
    p_recovery = min(spec.power_kw, service_kw * duration_h / max(recovery_h, dt_h) / (spec.eta_charge * spec.eta_discharge))
    p = [service_kw] * n_service + [-p_recovery] * n_recovery
    soc = [spec.soc_initial]
    for power in p:
        if power >= 0:
            nxt = soc[-1] - power * dt_h / spec.eta_discharge / spec.energy_kwh
        else:
            nxt = soc[-1] + (-power) * dt_h * spec.eta_charge / spec.energy_kwh
        soc.append(float(nxt))
    ok = all(spec.soc_min - 1e-9 <= x <= spec.soc_max + 1e-9 for x in soc) and soc[-1] >= spec.soc_target - 1e-9
    return soc, ok


def candidate_offer(site: str, service_kw: float, duration_h: float, recovery_h: float,
                    load_scale: float, pv_fraction: float, telemetry: float,
                    forecast_error: float, dt_h: float = 0.25, spec: BatterySpec | None = None) -> Offer:
    spec = spec or BatterySpec()
    margin = robust_margin(telemetry, forecast_error)
    # Conservative candidate power derating represents the estimated-state
    # network margin. It is later checked by the full AC adapter.
    derate = max(0.0, 1.0 - 3.0 * margin)
    effective_kw = min(spec.power_kw * derate, service_kw)
    soc, soc_ok = soc_rollout(effective_kw, duration_h, recovery_h, dt_h, spec)
    return Offer(site, effective_kw, duration_h, recovery_h, load_scale, pv_fraction,
                 telemetry, forecast_error, [effective_kw] * max(1, int(round(duration_h / dt_h))) +
                 [-min(spec.power_kw, effective_kw * duration_h / max(recovery_h, dt_h) / (spec.eta_charge * spec.eta_discharge))] * max(1, int(round(recovery_h / dt_h))), soc, bool(soc_ok),
                 "SOC/recovery infeasible" if not soc_ok else "")

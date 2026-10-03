"""Finite-grid service--recovery viability kernel.

The state is intentionally small for the pilot: SOC and an AC feasibility
margin observed after each replay. The composition is the research object,
not a universal guarantee: the candidate states are AC-audited over held-out
scenarios.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import numpy as np
from .envelope import BatterySpec

@dataclass(frozen=True)
class KernelState:
    soc: float
    voltage_margin: float = 0.0
    current_margin: float = 0.0

@dataclass
class KernelResult:
    events: int
    service_kw: float
    recovery_h: float
    states: list[KernelState]
    viable: bool


def service_recovery_map(state: KernelState, service_kw: float, duration_h: float,
                          recovery_h: float, spec: BatterySpec) -> KernelState | None:
    """Apply one service and its re-arm operation in the reduced SOC state."""
    soc_after = state.soc - service_kw * duration_h / spec.eta_discharge / spec.energy_kwh
    if soc_after < spec.soc_min - 1e-9:
        return None
    p_charge = min(spec.power_kw, service_kw * duration_h / max(recovery_h, 1e-9) /
                   (spec.eta_charge * spec.eta_discharge))
    soc_rearmed = soc_after + p_charge * recovery_h * spec.eta_charge / spec.energy_kwh
    if soc_rearmed < spec.soc_target - 1e-9 or soc_rearmed > spec.soc_max + 1e-9:
        return None
    return KernelState(float(soc_rearmed), state.voltage_margin, state.current_margin)


def compose_kernel(initial: KernelState, service_kw: float, duration_h: float,
                   recovery_h: float, events: int, spec: BatterySpec | None = None) -> KernelResult:
    spec = spec or BatterySpec()
    states=[initial]; current=initial
    for _ in range(events):
        nxt=service_recovery_map(current, service_kw, duration_h, recovery_h, spec)
        if nxt is None:
            return KernelResult(events, service_kw, recovery_h, states, False)
        current=nxt; states.append(current)
    return KernelResult(events, service_kw, recovery_h, states, True)


def sequence_contraction(capacities: Iterable[float]) -> np.ndarray:
    """C_m=P*_m/P*_(m-1), with C_1 defined relative to itself."""
    c=np.asarray(list(capacities),dtype=float)
    if c.size==0: return c
    out=np.ones_like(c); out[1:]=np.divide(c[1:],c[:-1],out=np.zeros_like(c[1:]),where=c[:-1]>0)
    return out

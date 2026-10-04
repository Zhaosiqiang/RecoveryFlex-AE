"""Independent, state-reset AC snapshots for RecoveryFlex experiments.

This module is intentionally separate from :mod:`opendss_adapter`.  The old
adapter was written for a quick pilot and used OpenDSS storage elements and a
process-global engine.  The experiment path uses a dedicated OpenDSS context,
constant-PQ load surrogates for the batteries, and records the realized AC
injection at every snapshot.  Battery energy/SOC is managed by the caller.

The input feeders are static snapshot models (``ieee123_snapshot`` and
``IEEE13Nodeckt.dss``).  Controls are disabled so a repeated snapshot is
reproducible; line and transformer ratings are still reported and included in
the feasibility test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Iterable
import math
import os

import numpy as np
import opendssdirect as odd


@dataclass(frozen=True)
class SnapshotAudit:
    """Complete AC evidence for one commanded operating point."""

    feasible: bool
    converged: bool
    vmin: float
    vmax: float
    max_line_loading: float
    total_loss_kw: float
    voltages_pu: Mapping[str, float] = field(default_factory=dict)
    line_current_ratios: Mapping[str, float] = field(default_factory=dict)
    battery_command_kw: Mapping[str, float] = field(default_factory=dict)
    battery_realized_kw: Mapping[str, float] = field(default_factory=dict)
    battery_realized_kvar: Mapping[str, float] = field(default_factory=dict)
    error: str = ""
    # Explicit diagnostics retained for auditability.  These fields are
    # appended so existing positional consumers remain compatible.
    max_transformer_loading: float = float("nan")
    failure_reasons: tuple[str, ...] = field(default_factory=tuple)
    limiting_component: str = ""


def _site_parts(site: str) -> tuple[str, int]:
    """Return a DSS bus name and one phase from a ``bus.phase`` site."""
    bits = str(site).strip().split(".")
    if len(bits) != 2 or not bits[0] or bits[1] not in {"1", "2", "3"}:
        raise ValueError(f"Battery/PV site must be a single phase bus.phase, got {site!r}")
    return bits[0], int(bits[1])


class ACSnapshotFeeder:
    """OpenDSS snapshot feeder with an isolated engine context.

    Parameters
    ----------
    master_path:
        Static OpenDSS master file.  QSTS files with ``yearly`` or ``daily``
        load shapes are deliberately rejected by the experiment manifest; use
        ``data/raw/ieee123_snapshot/master.dss`` for the IEEE-123 case.
    battery_sites:
        Single-phase sites in ``bus.phase`` notation.  Batteries are ideal
        constant-PQ inverter surrogates.  A positive command means export to
        the feeder; a negative command means charging from the feeder.
    pv_sites:
        Optional mapping from ``bus.phase`` to rated kW.  PV is represented by
        constant-P real-power injections and is scaled with ``pv_fraction``.
    """

    def __init__(
        self,
        master_path: str | os.PathLike,
        battery_sites: Iterable[str] = (),
        battery_kv: float | None = None,
        pv_sites: Mapping[str, float] | None = None,
        voltage_limits: tuple[float, float] = (0.95, 1.05),
        line_loading_limit: float = 1.0,
        transformer_loading_limit: float | None = None,
        source_buses: Iterable[str] = ("sourcebus", "150", "rg60"),
        command_tolerance_kw: float = 1e-2,
        relative_command_tolerance: float = 1e-2,
        constraint_tolerance: float = 1e-6,
    ) -> None:
        self.master_path = str(Path(master_path).resolve())
        if not Path(self.master_path).is_file():
            raise FileNotFoundError(self.master_path)
        self.battery_sites = tuple(str(s) for s in battery_sites)
        self._battery_kv = None if battery_kv is None else float(battery_kv)
        self.pv_sites = {str(k): float(v) for k, v in (pv_sites or {}).items()}
        self.voltage_limits = tuple(float(x) for x in voltage_limits)
        self.line_loading_limit = float(line_loading_limit)
        # OpenDSS exposes transformer winding kVA/current ratings separately
        # from line NormAmps.  Keep an explicit limit so transformer overload
        # is never hidden by the line limit or by terminal kVA aggregation.
        self.transformer_loading_limit = (
            float(line_loading_limit)
            if transformer_loading_limit is None
            else float(transformer_loading_limit)
        )
        self.source_buses = {str(x).lower() for x in source_buses}
        self.command_tolerance_kw = float(command_tolerance_kw)
        self.relative_command_tolerance = float(relative_command_tolerance)
        if self.command_tolerance_kw < 0:
            raise ValueError("command_tolerance_kw must be non-negative")
        if self.relative_command_tolerance < 0:
            raise ValueError("relative_command_tolerance must be non-negative")
        # OpenDSS readback can exceed a hard limit by a few 1e-9 due to
        # nonlinear-solve roundoff at a bisection endpoint.  Apply one
        # explicit, documented numerical tolerance to constraint checks so
        # the reduced bounds and their replay use the same decision rule.
        self.constraint_tolerance = float(constraint_tolerance)
        if self.constraint_tolerance < 0:
            raise ValueError("constraint_tolerance must be non-negative")
        self.dss = odd.NewContext()
        self._native_load_base: dict[str, tuple[float, float]] = {}
        self._pv_base: dict[str, float] = {}
        self._battery_element: dict[str, str] = {}
        self._pv_element: dict[str, str] = {}
        self._compile()

    def _command(self, text: str) -> None:
        self.dss.Text.Command(text)
        err = str(self.dss.Error.Description() or "")
        if err:
            raise RuntimeError(f"OpenDSS command failed: {text!r}: {err}")

    def _available_phases(self, site: str) -> tuple[str, int, float]:
        bus, phase = _site_parts(site)
        names = {str(x).lower(): str(x) for x in self.dss.Circuit.AllBusNames()}
        if bus.lower() not in names:
            raise ValueError(f"Site {site!r} refers to unknown bus; available bus count={len(names)}")
        canonical = names[bus.lower()]
        self.dss.Circuit.SetActiveBus(canonical)
        nodes = {int(x) for x in self.dss.Bus.Nodes()}
        if phase not in nodes:
            raise ValueError(f"Site {site!r} is not a modeled phase; bus nodes={sorted(nodes)}")
        kv = float(self.dss.Bus.kVBase())
        if not math.isfinite(kv) or kv <= 0:
            # IEEE test feeders use 2.4 kV phase-to-neutral on their 4.16 kV
            # primary.  This fallback only applies when a source omitted bases.
            kv = 2.4
        return canonical, phase, kv

    def _compile(self) -> None:
        d = self.dss
        d.Basic.ClearAll()
        self._native_load_base.clear()
        self._pv_base.clear()
        self._battery_element.clear()
        self._pv_element.clear()
        # The static master files define all lines/loads.  Controls remain at
        # their initial settings by design; the experiment disables automatic
        # regulator/capacitor actions to make each snapshot reproducible.
        self._command(f'redirect "{self.master_path}"')
        self._command("set controlmode=off")
        # A master file may contain its own Solve command.  We cannot undo
        # that initial parse-time solve, but every solve issued by this
        # adapter is explicitly SolveNoControl so taps/caps never move as a
        # side effect of a snapshot.
        self._solve_no_control()

        # Validate all requested phase sites before adding any surrogate.
        site_info = {s: self._available_phases(s) for s in (*self.battery_sites, *self.pv_sites)}

        # Add constant-PQ battery surrogates.  OpenDSS positive load kW is
        # consumption, so the experiment's positive export command is negated.
        for i, site in enumerate(self.battery_sites):
            bus, _phase, kv_base = site_info[site]
            kv = float(self._battery_kv or kv_base)
            name = f"BatRF{i}"
            self._command(
                f"new load.{name} phases=1 bus1={bus}.{_site_parts(site)[1]} "
                f"conn=wye kV={kv:.9g} kW=0 kvar=0 model=1"
            )
            self._battery_element[site] = name

        for i, (site, rated_kw) in enumerate(self.pv_sites.items()):
            bus, phase, kv_base = site_info[site]
            kv = float(kv_base)
            name = f"PVRF{i}"
            # A constant-P PV surrogate avoids hidden inverter controls while
            # retaining the requested phase and rated real-power injection.
            self._command(
                f"new load.{name} phases=1 bus1={bus}.{phase} conn=wye "
                f"kV={kv:.9g} kW={-abs(rated_kw):.9g} kvar=0 model=1"
            )
            self._pv_element[site] = name

        # Capture native fixed-PQ loads after adding surrogates.  The names are
        # explicit so future edits cannot accidentally scale batteries/PV.
        surrogate = set(self._battery_element.values()) | set(self._pv_element.values())
        surrogate_folded = {str(x).casefold() for x in surrogate}
        for name in d.Loads.AllNames():
            # OpenDSS versions differ in whether AllNames returns the case
            # used in the declaration.  Case-insensitive exclusion prevents
            # a surrogate from being scaled as a native load.
            if str(name).casefold() in surrogate_folded:
                continue
            d.Loads.Name(name)
            self._native_load_base[str(name)] = (float(d.Loads.kW()), float(d.Loads.kvar()))
        self._pv_base = {site: abs(float(rated)) for site, rated in self.pv_sites.items()}
        self._solve_no_control()

    def reset(self) -> None:
        """Rebuild the context and all static components."""
        self._compile()

    def _solve_no_control(self) -> None:
        """Solve a snapshot without OpenDSS control actions.

        ``InitSnap`` clears the previous solution state before each solve;
        this makes results independent of whether a high-load event was
        solved before a low-load event.  ``SolveNoControl`` is the explicit
        OpenDSS API for a snapshot solve with regulators/capacitors held.
        """
        self._command("set controlmode=off")
        self.dss.Solution.InitSnap()
        # OpenDSS can report Converged after the first Newton pass while a
        # second call still updates currents after a large load jump.  Three
        # no-control passes remove that warm-start dependence (differences are
        # below 1e-8 pu on IEEE13/123) without changing the operating point.
        for _ in range(3):
            self.dss.Solution.SolveNoControl()

    def _set_native_load_scale(self, scale: float) -> None:
        d = self.dss
        for name, (kw, kvar) in self._native_load_base.items():
            d.Loads.Name(name)
            d.Loads.kW(kw * float(scale))
            d.Loads.kvar(kvar * float(scale))

    def _set_batteries(self, p_kw: Mapping[str, float]) -> None:
        d = self.dss
        for site, name in self._battery_element.items():
            command = float(p_kw.get(site, 0.0))
            d.Loads.Name(name)
            d.Loads.kW(-command)
            d.Loads.kvar(0.0)

    def _set_pv(self, pv_fraction: float) -> None:
        d = self.dss
        fraction = max(0.0, float(pv_fraction))
        for site, name in self._pv_element.items():
            d.Loads.Name(name)
            d.Loads.kW(-self._pv_base[site] * fraction)
            d.Loads.kvar(0.0)

    def _all_voltages(self) -> dict[str, float]:
        d = self.dss
        out: dict[str, float] = {}
        for raw_name in d.Circuit.AllBusNames():
            name = str(raw_name)
            if name.lower() in self.source_buses:
                continue
            d.Circuit.SetActiveBus(name)
            nodes = [int(x) for x in d.Bus.Nodes()]
            values = np.asarray(d.Bus.puVmagAngle(), dtype=float)
            if len(values) != 2 * len(nodes):
                raise RuntimeError(f"Unexpected voltage vector at bus {name}: {values.tolist()}")
            for i, phase in enumerate(nodes):
                out[f"{name}.{phase}"] = float(values[2 * i])
        return out

    def _line_ratios(self) -> dict[str, float]:
        d = self.dss
        out: dict[str, float] = {}
        for raw in d.Lines.AllNames():
            name = str(raw)
            d.Lines.Name(name)
            d.Circuit.SetActiveElement(f"line.{name}")
            limit = float(d.Lines.NormAmps())
            currents = np.asarray(d.CktElement.CurrentsMagAng(), dtype=float)[::2]
            if limit <= 0 or not currents.size:
                out[f"line.{name}"] = float("nan")
            else:
                out[f"line.{name}"] = float(np.nanmax(np.abs(currents)) / limit)
        for raw in d.Transformers.AllNames():
            name = str(raw)
            d.Transformers.Name(name)
            # WdgCurrents is ordered phase-by-phase, with one complex current
            # for every winding.  Terminal kVA can conceal a single-phase
            # overload, and Transformers.kVA() reports only the active
            # winding, so use every winding/phase current against its own
            # declared winding kVA rating.
            d.Circuit.SetActiveElement(f"transformer.{name}")
            nph = int(d.CktElement.NumPhases())
            nwdg = int(d.Transformers.NumWindings())
            raw_curr = np.asarray(d.Transformers.WdgCurrents())
            if np.iscomplexobj(raw_curr):
                currents = np.asarray(raw_curr, dtype=complex).ravel()
                if currents.size == nph * nwdg:
                    # Some OpenDSSDirect builds expose one terminal as a
                    # complex vector; duplicate it for the two-terminal
                    # normalization below.
                    currents = np.repeat(currents, 2)
            else:
                raw_curr = np.asarray(raw_curr, dtype=float).ravel()
                if raw_curr.size == 4 * nph * nwdg:
                    currents = raw_curr[0::2] + 1j * raw_curr[1::2]
                elif raw_curr.size == 2 * nph * nwdg:
                    currents = raw_curr[0::2] + 1j * raw_curr[1::2]
                    currents = np.repeat(currents, 2)
                else:
                    currents = raw_curr.astype(complex)
            # WdgCurrents includes both terminal currents of every winding.
            # The two terminal values have opposite signs; use the larger
            # magnitude for a winding/phase loading ratio.
            if nph <= 0 or nwdg <= 0 or currents.size != 2 * nph * nwdg:
                out[f"transformer.{name}"] = float("nan")
                continue
            phase_ratios: list[float] = []
            for winding in range(1, nwdg + 1):
                d.Transformers.Wdg(winding)
                kva = float(d.Transformers.kVA())
                kv = float(d.Transformers.kV())
                is_delta = bool(d.Transformers.IsDelta())
                # kV is phase-phase for a 2/3-phase winding.  A wye winding
                # sees kV/sqrt(3), while a delta winding sees kV directly.
                winding_kv = kv if nph == 1 or is_delta else kv / math.sqrt(3.0)
                rating_amp = (kva / nph) / winding_kv if kva > 0 and winding_kv > 0 else float("nan")
                for phase in range(1, nph + 1):
                    base = 2 * ((phase - 1) * nwdg + (winding - 1))
                    current = max(abs(complex(currents[base])), abs(complex(currents[base + 1])))
                    ratio = current / rating_amp if rating_amp > 0 else float("nan")
                    key = f"transformer.{name}.wdg{winding}.phase{phase}"
                    out[key] = float(ratio)
                    phase_ratios.append(float(ratio))
            out[f"transformer.{name}"] = float(np.nanmax(phase_ratios)) if phase_ratios else float("nan")
            d.Transformers.Wdg(1)
        return out

    def _battery_measurements(self, commands: Mapping[str, float]) -> tuple[dict[str, float], dict[str, float], str]:
        d = self.dss
        p_out: dict[str, float] = {}
        q_out: dict[str, float] = {}
        errors: list[str] = []
        for site, name in self._battery_element.items():
            d.Circuit.SetActiveElement(f"load.{name}")
            powers = np.asarray(d.CktElement.Powers(), dtype=float)
            if powers.size < 2:
                errors.append(f"no battery terminal power for {site}")
                continue
            # Positive experiment command is export, hence minus load P.
            realized_p = float(-np.nansum(powers[0::2]))
            realized_q = float(-np.nansum(powers[1::2]))
            p_out[site] = realized_p
            q_out[site] = realized_q
            target = float(commands.get(site, 0.0))
            # OpenDSS reports terminal real power after the nonlinear solve;
            # a small voltage-dependent discrepancy is expected for the
            # constant-P surrogate.  Require a documented 1% readback match
            # while retaining a tight absolute floor for small commands.
            tolerance = max(self.command_tolerance_kw, self.relative_command_tolerance * abs(target))
            if not math.isfinite(realized_p) or abs(realized_p - target) > tolerance:
                errors.append(f"battery {site}: command={target:.6g} realized={realized_p:.6g}")
        return p_out, q_out, "; ".join(errors)

    def solve(
        self,
        load_scale: float = 1.0,
        pv_fraction: float = 0.0,
        p_kw: Mapping[str, float] | None = None,
    ) -> SnapshotAudit:
        """Solve one independent snapshot and return complete telemetry.

        ``p_kw`` uses positive feeder export.  No result cache is used: all
        native loads and surrogate injections are reset from their immutable
        base values before every solve, preventing hidden state between QSTS
        events.
        """
        commands = {str(k): float(v) for k, v in (p_kw or {}).items()}
        try:
            self._set_native_load_scale(float(load_scale))
            self._set_pv(float(pv_fraction))
            self._set_batteries(commands)
            self._solve_no_control()
            d = self.dss
            converged = bool(d.Solution.Converged())
            if not converged:
                return SnapshotAudit(
                    False, False, float("nan"), float("nan"), float("inf"), float("nan"),
                    error="nonconverged", failure_reasons=("nonconverged",),
                )
            voltages = self._all_voltages()
            voltage_values = np.asarray(list(voltages.values()), dtype=float)
            finite_v = voltage_values[np.isfinite(voltage_values)]
            if finite_v.size == 0:
                return SnapshotAudit(
                    False, True, float("nan"), float("nan"), float("inf"), float("nan"),
                    voltages_pu=voltages, error="nonfinite_voltage", failure_reasons=("nonfinite_voltage",),
                )
            vmin, vmax = float(np.min(finite_v)), float(np.max(finite_v))
            ratios = self._line_ratios()
            finite_ratios = np.asarray([x for x in ratios.values() if math.isfinite(x)], dtype=float)
            max_loading = float(np.max(finite_ratios)) if finite_ratios.size else float("nan")
            transformer_ratios = [
                x for key, x in ratios.items()
                if key.startswith("transformer.") and ".wdg" not in key and math.isfinite(x)
            ]
            max_transformer = float(np.max(transformer_ratios)) if transformer_ratios else float("nan")
            losses = np.asarray(d.Circuit.Losses(), dtype=float)
            loss_kw = float(losses[0] / 1000.0) if losses.size else float("nan")
            realized, realized_q, battery_error = self._battery_measurements(commands)
            reasons: list[str] = []
            if not np.all(np.isfinite(voltage_values)):
                reasons.append("nonfinite_voltage")
            if np.any(voltage_values <= 0):
                reasons.append("nonpositive_voltage")
            # Include the bus-phase label in voltage violations so an
            # infeasible event can be traced without rerunning OpenDSS.
            lower = [(k, v) for k, v in voltages.items() if math.isfinite(v) and v < self.voltage_limits[0]]
            upper = [(k, v) for k, v in voltages.items() if math.isfinite(v) and v > self.voltage_limits[1]]
            lower_limit = self.voltage_limits[0] - self.constraint_tolerance
            upper_limit = self.voltage_limits[1] + self.constraint_tolerance
            if lower:
                k, v = min(lower, key=lambda kv: kv[1])
                if v < lower_limit:
                    reasons.append(f"voltage_lower:{k}={v:.6g}<{self.voltage_limits[0]:.6g}")
            if upper:
                k, v = max(upper, key=lambda kv: kv[1])
                if v > upper_limit:
                    reasons.append(f"voltage_upper:{k}={v:.6g}>{self.voltage_limits[1]:.6g}")
            if not ratios:
                reasons.append("no_loading_measurements")
            for key, value in ratios.items():
                if not math.isfinite(value):
                    reasons.append(f"nonfinite_loading:{key}")
                elif key.startswith("transformer."):
                    # Per-winding/per-phase keys and the aggregate key all
                    # use the same explicit transformer limit.
                    if value > self.transformer_loading_limit + self.constraint_tolerance:
                        reasons.append(
                            f"transformer_loading:{key}={value:.6g}>{self.transformer_loading_limit:.6g}"
                        )
                elif value > self.line_loading_limit + self.constraint_tolerance:
                    reasons.append(f"line_loading:{key}={value:.6g}>{self.line_loading_limit:.6g}")
            if battery_error:
                reasons.append(f"battery_readback:{battery_error}")
            unknown = sorted(set(commands) - set(self._battery_element))
            if unknown:
                reasons.append("unknown_battery_site:" + ",".join(unknown))
            limiting = ""
            if finite_ratios.size:
                limiting = max((k for k, v in ratios.items() if math.isfinite(v)), key=lambda k: ratios[k])
            feasible = not reasons and converged
            error = "; ".join(reasons)
            return SnapshotAudit(
                feasible, True, vmin, vmax, max_loading, loss_kw,
                voltages, ratios, commands, realized, realized_q, error,
                max_transformer, tuple(reasons), limiting,
            )
        except Exception as exc:
            reason = f"adapter_exception:{type(exc).__name__}:{exc}"
            return SnapshotAudit(
                False, False, float("nan"), float("nan"), float("inf"), float("nan"),
                error=reason, failure_reasons=(reason,),
            )


__all__ = ["ACSnapshotFeeder", "SnapshotAudit"]

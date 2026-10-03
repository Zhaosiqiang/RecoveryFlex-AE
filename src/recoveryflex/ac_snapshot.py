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
        source_buses: Iterable[str] = ("sourcebus", "150", "rg60"),
        command_tolerance_kw: float = 1e-2,
    ) -> None:
        self.master_path = str(Path(master_path).resolve())
        if not Path(self.master_path).is_file():
            raise FileNotFoundError(self.master_path)
        self.battery_sites = tuple(str(s) for s in battery_sites)
        self._battery_kv = None if battery_kv is None else float(battery_kv)
        self.pv_sites = {str(k): float(v) for k, v in (pv_sites or {}).items()}
        self.voltage_limits = tuple(float(x) for x in voltage_limits)
        self.line_loading_limit = float(line_loading_limit)
        self.source_buses = {str(x).lower() for x in source_buses}
        self.command_tolerance_kw = float(command_tolerance_kw)
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
        # The static master files define all lines/loads.  Controls remain at
        # their initial settings by design; the experiment disables automatic
        # regulator/capacitor actions to make each snapshot reproducible.
        self._command(f'redirect "{self.master_path}"')
        self._command("set controlmode=off")
        self._command("solve")

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
        self._native_load_base.clear()
        for name in d.Loads.AllNames():
            if name in surrogate:
                continue
            d.Loads.Name(name)
            self._native_load_base[str(name)] = (float(d.Loads.kW()), float(d.Loads.kvar()))
        self._pv_base = {site: abs(float(rated)) for site, rated in self.pv_sites.items()}
        self._command("solve")

    def reset(self) -> None:
        """Rebuild the context and all static components."""
        self._compile()

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
            d.Circuit.SetActiveElement(f"transformer.{name}")
            kva = float(d.Transformers.kVA())
            powers = np.asarray(d.CktElement.Powers(), dtype=float)
            p, q = powers[::2], powers[1::2]
            apparent = float(np.nansum(np.hypot(p, q)) / 1000.0)
            out[f"transformer.{name}"] = float(apparent / kva) if kva > 0 else float("nan")
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
            tolerance = max(self.command_tolerance_kw, 0.01 * abs(target))
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
            self._command("solve")
            d = self.dss
            converged = bool(d.Solution.Converged())
            if not converged:
                return SnapshotAudit(False, False, float("nan"), float("nan"), float("inf"), float("nan"), error="OpenDSS did not converge")
            voltages = self._all_voltages()
            finite_v = np.asarray(list(voltages.values()), dtype=float)
            if finite_v.size == 0 or not np.all(np.isfinite(finite_v)) or np.any(finite_v <= 0):
                return SnapshotAudit(False, True, float("nan"), float("nan"), float("inf"), float("nan"), voltages_pu=voltages, error="non-positive or non-finite non-source voltage (possible island)")
            ratios = self._line_ratios()
            finite_ratios = np.asarray([x for x in ratios.values() if math.isfinite(x)], dtype=float)
            max_loading = float(np.max(finite_ratios)) if finite_ratios.size else float("nan")
            losses = np.asarray(d.Circuit.Losses(), dtype=float)
            loss_kw = float(losses[0] / 1000.0) if losses.size else float("nan")
            realized, realized_q, battery_error = self._battery_measurements(commands)
            vmin, vmax = float(np.min(finite_v)), float(np.max(finite_v))
            finite_ok = bool(np.all(np.isfinite(list(ratios.values()))))
            feasible = bool(
                finite_ok
                and self.voltage_limits[0] <= vmin <= vmax <= self.voltage_limits[1]
                and max_loading <= self.line_loading_limit
                and not battery_error
            )
            return SnapshotAudit(feasible, True, vmin, vmax, max_loading, loss_kw,
                                 voltages, ratios, commands, realized, realized_q,
                                 battery_error)
        except Exception as exc:
            return SnapshotAudit(False, False, float("nan"), float("nan"), float("inf"), float("nan"), error=repr(exc))


__all__ = ["ACSnapshotFeeder", "SnapshotAudit"]

"""Small OpenDSS adapter for the RecoveryFlex pilot.

The adapter deliberately keeps the nonlinear AC solver at the audit boundary. The
candidate envelope may use reduced-order margins, but every reported trajectory
is replayed through this class.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping
import numpy as np
import opendssdirect as dss

@dataclass
class Audit:
    feasible: bool
    vmin: float
    vmax: float
    max_line_loading: float
    total_loss_kw: float
    error: str = ""

class FeederModel:
    def __init__(self, master_path: str | os.PathLike, battery_sites: Iterable[str] = ("634.1", "645.2", "675.1"),
                 battery_kw: float = 150.0, battery_kwh: float = 300.0,
                 v_limits=(0.95, 1.06), line_limit: float = 1.0):
        self.master_path = str(Path(master_path).resolve())
        self.battery_sites = tuple(battery_sites)
        self.battery_kw = float(battery_kw)
        self.battery_kwh = float(battery_kwh)
        self.v_limits = tuple(v_limits)
        self.line_limit = float(line_limit)
        self._load_base: Dict[str, float] = {}
        self._pv_base: Dict[str, float] = {}
        self._cache: Dict[tuple, Audit] = {}
        self._compile()

    def _compile(self):
        self._cache = {}
        dss.Basic.ClearAll()
        dss.Text.Command(f'redirect "{self.master_path}"')
        # The IEEE 13-bus feeder contains no native PV/storage. These additions
        # are explicit and are recorded in the data manifest for reproducibility.
        dss.Text.Command("new pvsystem.PV1 phases=1 bus1=675.1 kv=2.4 kVA=250 Pmpp=250 %cutin=0 %cutout=0 pf=1")
        for idx, bus in enumerate(self.battery_sites):
            # kV is chosen from the corresponding secondary/primary bus phase.
            kv = 0.277 if bus.startswith("634") else (2.4 if bus.startswith(("645", "675")) else 2.4)
            dss.Text.Command(
                f"new storage.Bat{idx} phases=1 bus1={bus} kv={kv} "
                f"kWRated={self.battery_kw} kWhrated={self.battery_kwh} "
                "%stored=70 %reserve=5 dispmode=external state=idl"
            )
        dss.Solution.Solve()
        # Cache original load/PV ratings. We scale profiles without changing the
        # feeder topology or the native load model.
        for name in dss.Loads.AllNames():
            dss.Loads.Name(name)
            self._load_base[name] = float(dss.Loads.kW())
        for name in dss.PVsystems.AllNames():
            dss.PVsystems.Name(name)
            self._pv_base[name] = float(dss.PVsystems.Pmpp())

    def reset(self):
        self._compile()

    def _set_load_scale(self, load_scale: float):
        for name, kw in self._load_base.items():
            dss.Loads.Name(name)
            dss.Loads.kW(kw * float(load_scale))

    def _set_pv(self, pv_fraction: float):
        for name, pmpp in self._pv_base.items():
            dss.PVsystems.Name(name)
            dss.PVsystems.Pmpp(pmpp * float(max(0.0, pv_fraction)))
            dss.PVsystems.Irradiance(1.0)

    def _set_batteries(self, p_kw: Mapping[str, float]):
        # Positive p_kw means grid export/discharge. OpenDSS storage kW is
        # negative while discharging and positive while charging.
        for idx, bus in enumerate(self.battery_sites):
            value = float(p_kw.get(bus, 0.0))
            state = "discharging" if value > 1e-9 else ("charging" if value < -1e-9 else "idl")
            dss.Text.Command(f"edit storage.Bat{idx} kW={-value:.8f} state={state}")

    def solve(self, load_scale: float = 1.0, pv_fraction: float = 0.0,
              p_kw: Mapping[str, float] | None = None) -> Audit:
        key=(round(float(load_scale),8),round(float(pv_fraction),8),tuple(sorted((str(k),round(float(v),8)) for k,v in (p_kw or {}).items())))
        if key in self._cache:
            return self._cache[key]
        try:
            self._set_load_scale(load_scale)
            self._set_pv(pv_fraction)
            self._set_batteries(p_kw or {})
            dss.Solution.Solve()
            if dss.Solution.Converged() is False:
                self._cache[key] = Audit(False, np.nan, np.nan, np.inf, np.nan, "OpenDSS did not converge")
                return self._cache[key]
            v = np.asarray(dss.Circuit.AllBusMagPu(), dtype=float)
            v = v[np.isfinite(v) & (v > 1e-6)]
            vmin = float(v.min()) if v.size else np.nan
            vmax = float(v.max()) if v.size else np.nan
            max_loading = 0.0
            for name in dss.Lines.AllNames():
                dss.Lines.Name(name)
                dss.Circuit.SetActiveElement(f"line.{name}")
                norm = float(dss.Lines.NormAmps())
                if norm <= 0:
                    continue
                cur = np.asarray(dss.CktElement.CurrentsMagAng(), dtype=float)[::2]
                if cur.size:
                    max_loading = max(max_loading, float(np.nanmax(cur) / norm))
            losses = np.asarray(dss.Circuit.Losses(), dtype=float)
            loss_kw = float(losses[0] / 1000.0) if losses.size else np.nan
            feasible = bool((vmin >= self.v_limits[0]) and (vmax <= self.v_limits[1]) and (max_loading <= self.line_limit))
            self._cache[key] = Audit(feasible, vmin, vmax, max_loading, loss_kw)
            return self._cache[key]
        except Exception as exc:  # keep the audit record instead of hiding a failed trajectory
            self._cache[key] = Audit(False, np.nan, np.nan, np.inf, np.nan, repr(exc))
            return self._cache[key]

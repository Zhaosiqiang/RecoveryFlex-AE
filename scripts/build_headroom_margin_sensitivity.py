#!/usr/bin/env python3
"""Deterministic AC-headroom margin sensitivity for the strict-v4 contract.

Each margin m replaces audited charge/export limits with (1-m) times the
limit. This is an operational stress test, not a forecast-error distribution
or probabilistic delivery guarantee. It re-solves the scalar-bound dispatch and
does not perform a fresh OpenDSS replay.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from recoveryflex.dispatch import plan_service

WINDOWS=((8,12),(24,28)); RECOVERY_WINDOWS=((12,24),(28,48))
HORIZON=48; DT_H=.5; ETA_C=.95; ETA_D=.95
SOC0=.8; SOC_MIN=.2; SOC_MAX=1.; TERMINAL_SOC=.8; ENERGY_KWH=2000.
FIXED_RATIO=8./(32.*ETA_C*ETA_D)
MARGINS=(0.,.05,.10,.20)

def boot(g,col,reps,seed):
    x=g.groupby("date",sort=False)[col].mean().to_numpy(float)
    if not len(x): return [float("nan")]*3
    rng=np.random.default_rng(seed)
    s=x[rng.integers(0,len(x),size=(reps,len(x)))].mean(axis=1)
    return [float(x.mean()),float(np.quantile(s,.025)),float(np.quantile(s,.975))]

def run(bounds_path,audit_path,out_dir,margins=MARGINS,energy=ENERGY_KWH,reps=5000,seed=20261003):
    b=pd.read_csv(bounds_path); a=pd.read_csv(audit_path)
    for d in (b,a):
        d["site"]=d.site.astype(str); d["date"]=d.date.astype(str)
    gate=a[["date","group","site","baseline_zero_feasible"]].rename(columns={"baseline_zero_feasible":"baseline_feasible"})
    rows=[]
    for (date,group,site),g in b.groupby(["date","group","site"],sort=True):
        g=g.sort_values("interval")
        if len(g)!=HORIZON: raise ValueError(f"{date}/{group}/{site}: expected 48 rows")
        c0=g.charge_limit_kw.to_numpy(float); e0=g.export_limit_kw.to_numpy(float)
        for m in margins:
            m=float(m)
            if not 0<=m<1: raise ValueError("margins must lie in [0,1)")
            common=dict(charge_limit_kw=c0*(1-m),export_limit_kw=e0*(1-m),
                        load_kw=np.zeros(HORIZON),service_windows=WINDOWS,
                        recovery_windows=RECOVERY_WINDOWS,energy_kwh=energy,
                        initial_soc=SOC0,terminal_soc_target=TERMINAL_SOC,
                        soc_min=SOC_MIN,soc_max=SOC_MAX,eta_charge=ETA_C,
                        eta_discharge=ETA_D,dt_h=DT_H,terminal_mode="exact")
            modes=(("network_lp",dict(mode="network_lp")),
                   ("fixed_recovery",dict(mode="fixed_recovery",fixed_recovery_ratio=FIXED_RATIO)),
                   ("myopic_recovery",dict(mode="myopic_recovery")),
                   ("energy_only",dict(mode="energy_only")))
            for method,kw in modes:
                r=plan_service(**common,**kw)
                rows.append(dict(date=date,group=int(group),site=site,margin=m,
                                 energy_kwh=energy,method=method,service_kw=float(r.service_kw),
                                 planner_feasible=int(r.feasible),replay_equivalent=int(r.feasible)))
    df=pd.DataFrame(rows).merge(gate,on=["date","group","site"],how="left",validate="many_to_one")
    if df.baseline_feasible.isna().any(): raise ValueError("missing baseline audit match")
    out_dir.mkdir(parents=True,exist_ok=True); df.to_csv(out_dir/"policy_rows.csv",index=False)
    rec=[]
    for (site,m,method),g in df[df.baseline_feasible==1].groupby(["site","margin","method"],sort=True):
        est,lo,hi=boot(g,"service_kw",reps,seed)
        rec.append(dict(site=site,margin=float(m),energy_kwh=energy,method=method,
                        estimate=est,ci_low=lo,ci_high=hi,n_units=len(g),n_dates=g.date.nunique()))
    summary=pd.DataFrame(rec); summary.to_csv(out_dir/"date_cluster_summary.csv",index=False)
    pivot=summary.pivot_table(index=["site","margin"],columns="method",values="estimate").reset_index()
    for method in ("fixed_recovery","myopic_recovery","energy_only"):
        if method in pivot: pivot[f"network_minus_{method}"]=pivot.network_lp-pivot[method]
    pivot.to_csv(out_dir/"policy_gaps.csv",index=False)
    payload={"status":"deterministic_headroom_margin_sensitivity","bounds":str(bounds_path.resolve()),
             "audit":str(audit_path.resolve()),"margins":[float(x) for x in margins],"energy_kwh":energy,
             "n_rows":len(df),"n_sites":int(df.site.nunique()),"n_dates":int(df.date.nunique()),
             "replay_definition":"tightened scalar-bound equivalence; no fresh OpenDSS replay",
             "interpretation":"Deterministic headroom stress, not a forecast-error distribution or probabilistic guarantee.",
             "summary_csv":str((out_dir/"date_cluster_summary.csv").resolve())}
    (out_dir/"summary.json").write_text(json.dumps(payload,indent=2)); return payload

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--bounds",type=Path,default=ROOT/"results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv")
    ap.add_argument("--audit",type=Path,default=ROOT/"results/network_recovery_external_2012_2013_strict_v4/baseline_zero_audit.csv")
    ap.add_argument("--out-dir",type=Path,default=ROOT/"results/headroom_margin_sensitivity_strict_v4")
    ap.add_argument("--margins",default="0,0.05,0.10,0.20")
    ap.add_argument("--energy-kwh",type=float,default=ENERGY_KWH)
    ap.add_argument("--bootstrap",type=int,default=5000)
    x=ap.parse_args(); ms=tuple(float(v) for v in x.margins.split(",") if v.strip())
    print(json.dumps(run(x.bounds,x.audit,x.out_dir,ms,x.energy_kwh,x.bootstrap),indent=2))


#!/usr/bin/env python3
"""Generate AC-audited time-varying bounds and compare recovery policies.

This is the first experiment in the redesign.  It does not tune a contract
from the old sequence table: OpenDSS supplies per-interval export/charge
limits, then the four dispatch modes solve the same multi-call horizon.  The
LP schedules are replayed through OpenDSS and only replay-passing rows are
marked as validated.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.dispatch import plan_service
import run_corrected_experiment as exp
from recoveryflex.profile_bank import load_bank

OUT=ROOT/'results'/'network_recovery_v1'
P_GRID=np.arange(0.,301.,10.)
SITES=('611.3','634.1')
METHODS=('network_lp','fixed_recovery','myopic_recovery','energy_only')
WINDOWS=((8,12),(24,28))
HORIZON_INTERVALS=28
RECOVERY_WINDOWS=((12,20),)
REARM_RATIO=exp._rearm_ratio(1.0)
BATTERY_ENERGY_KWH=2000.0

def _embed_external():
    dev=load_bank(exp.BANK_PATH); x=np.load(ROOT/'data/processed/ausgrid_external_2011_2012.npz',allow_pickle=False)
    load=np.transpose(x['load_kw'],(0,2,1)); pv=np.transpose(x['pv_kw'],(0,2,1))
    load=np.clip(exp.LOAD_OFFSET+exp.LOAD_GAIN*load/dev.train_load_scale_kw[None,None,:],.35,.85)
    pv=np.clip(exp.PV_OFFSET+exp.PV_GAIN*pv/dev.train_pv_scale_kw[None,None,:],0,1)
    return load,pv,x['dates'].astype(str)

def _bounds(feeder, load_day, pv_day, site):
    n=load_day.size; export=np.zeros(n); charge=np.zeros(n); reasons=[]
    for t in range(n):
        exp_ok=[]; ch_ok=[]
        for p in P_GRID:
            a=feeder.solve(float(load_day[t]),float(pv_day[t]),{site:float(p)})
            if a.feasible: exp_ok.append(float(p))
            a=feeder.solve(float(load_day[t]),float(pv_day[t]),{site:float(-p)})
            if a.feasible: ch_ok.append(float(p))
        export[t]=max(exp_ok) if exp_ok else 0.0
        charge[t]=max(ch_ok) if ch_ok else 0.0
        if not exp_ok: reasons.append((t,'export'))
        if not ch_ok: reasons.append((t,'charge'))
    return charge,export,reasons

def _replay(feeder, load_day, pv_day, site, result):
    audits=[]
    for t,(l,p) in enumerate(zip(load_day,pv_day)):
        command=float(result.discharge_kw[t]-result.charge_kw[t])
        a=feeder.solve(float(l),float(p),{site:command}); audits.append(a)
    return bool(result.feasible and all(a.feasible for a in audits)), audits

def run(max_days:int=4, groups:int=2, out_dir:Path=OUT):
    bank=load_bank(exp.BANK_PATH); dates=bank.dates
    # Development dates are used only to generate a stable bound cache; the
    # external-year rows are the final validation path.
    train=np.where(bank.split=='train')[0][:max_days]
    profile_load,profile_pv=exp._embed(bank)
    rows=[]; bound_rows=[]; trace_rows=[]
    for site in SITES:
      feeder=ACSnapshotFeeder(exp.FEEDER_PATH,battery_sites=(site,),pv_sites={'675.1':exp.PV_RATED_KW},voltage_limits=exp.VOLTAGE_LIMITS,line_loading_limit=exp.LINE_LIMIT)
      for day in train:
       for g in range(min(groups,bank.load_kw.shape[2])):
        load=np.clip(exp.LOAD_OFFSET+exp.LOAD_GAIN*bank.load_kw[day,:HORIZON_INTERVALS,g]/bank.train_load_scale_kw[g],.35,.85)
        pv=np.clip(exp.PV_OFFSET+exp.PV_GAIN*bank.pv_kw[day,:HORIZON_INTERVALS,g]/bank.train_pv_scale_kw[g],0,1)
        charge,export,reasons=_bounds(feeder,load,pv,site)
        baseline_feasible = int(len(reasons) == 0)
        for t in range(HORIZON_INTERVALS): bound_rows.append({'date':str(dates[day]),'day_index':int(day),'group':g,'site':site,'interval':t,'charge_limit_kw':charge[t],'export_limit_kw':export[t]})
        common=dict(charge_limit_kw=charge,export_limit_kw=export,load_kw=load,service_windows=WINDOWS,recovery_windows=RECOVERY_WINDOWS,energy_kwh=BATTERY_ENERGY_KWH,initial_soc=exp.SOC_INITIAL,terminal_soc_target=exp.SOC_INITIAL,soc_min=exp.SOC_RESERVE,soc_max=1.0,eta_charge=exp.ETA_CHARGE,eta_discharge=exp.ETA_DISCHARGE,dt_h=exp.DT_H,terminal_mode='exact')
        modes={
          'network_lp':dict(mode='network_lp'),
          'fixed_recovery':dict(mode='fixed_recovery',fixed_recovery_ratio=REARM_RATIO),
          'myopic_recovery':dict(mode='myopic_recovery'),
          'energy_only':dict(mode='energy_only'),
        }
        for method,kw in modes.items():
            result=plan_service(**common,**kw)
            replay_ok,audits=_replay(feeder,load,pv,site,result)
            rows.append({'date':str(dates[day]),'day_index':int(day),'group':g,'site':site,'method':method,'service_kw':result.service_kw,'planner_feasible':int(result.feasible),'replay_feasible':int(replay_ok),'baseline_feasible':baseline_feasible,'terminal_soc':result.terminal_soc,'max_vmax':max((a.vmax for a in audits if np.isfinite(a.vmax)),default=np.nan),'max_loading':max((a.max_line_loading for a in audits if np.isfinite(a.max_line_loading)),default=np.nan),'message':result.message})
            if day == train[0] and g == 0 and site == SITES[0]:
                trace_rows.extend({'interval':t,'method':method,'charge_kw':result.charge_kw[t],'discharge_kw':result.discharge_kw[t],'soc':result.soc[t],'grid_import_kw':result.grid_import_kw[t],'charge_limit_kw':charge[t],'export_limit_kw':export[t]} for t in range(len(load)))
    out_dir.mkdir(parents=True,exist_ok=True); pd.DataFrame(rows).to_csv(out_dir/'policy_rows.csv',index=False); pd.DataFrame(bound_rows).to_csv(out_dir/'ac_bounds.csv',index=False); pd.DataFrame(trace_rows).to_csv(out_dir/'representative_trace.csv',index=False)
    df=pd.DataFrame(rows); grouped=df.groupby(['site','method'],as_index=False).agg(mean_service_kw=('service_kw','mean'),replay_success=('replay_feasible','mean'),baseline_success=('baseline_feasible','mean'),n=('service_kw','size')); conditional=df[df.baseline_feasible==1].groupby(['site','method'],as_index=False).agg(conditional_replay_success=('replay_feasible','mean'),conditional_mean_service_kw=('service_kw','mean'),n_baseline=('service_kw','size')); summary={'status':'network_recovery_v1','battery_energy_kwh':BATTERY_ENERGY_KWH,'n_development_days':int(len(train)),'n_groups':min(groups,bank.load_kw.shape[2]),'sites':list(SITES),'methods':list(METHODS),'windows':[list(x) for x in WINDOWS],'recovery_windows':[list(x) for x in RECOVERY_WINDOWS],'summary':grouped.to_dict(orient='records'),'conditional_summary':conditional.to_dict(orient='records')}
    (out_dir/'summary.json').write_text(json.dumps(summary,indent=2)); return summary

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--max-days',type=int,default=4); ap.add_argument('--groups',type=int,default=2); ap.add_argument('--out-dir',type=Path,default=OUT); a=ap.parse_args(); print(json.dumps(run(a.max_days,a.groups,a.out_dir),indent=2))

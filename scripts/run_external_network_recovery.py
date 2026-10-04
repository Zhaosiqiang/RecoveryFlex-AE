#!/usr/bin/env python3
"""External-year replay of the frozen network-aware recovery contract."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.dispatch import plan_service
import run_corrected_experiment as exp
from recoveryflex.profile_bank import load_bank
from run_network_recovery_audit import (_bounds,_replay,SITES,METHODS,WINDOWS,RECOVERY_WINDOWS,P_GRID,BATTERY_ENERGY_KWH,REARM_RATIO,HORIZON_INTERVALS)

OUT=ROOT/'results'/'network_recovery_external_v1'

def run(max_days:int=12, groups:int=10, out_dir:Path=OUT, source:Path|None=None):
    dev=load_bank(exp.BANK_PATH); source=source or ROOT/'data/processed/ausgrid_external_2012_2013.npz'; x=np.load(source,allow_pickle=False)
    load=np.transpose(x['load_kw'],(0,2,1)); pv=np.transpose(x['pv_kw'],(0,2,1)); dates=x['dates'].astype(str)
    load=np.clip(exp.LOAD_OFFSET+exp.LOAD_GAIN*load/dev.train_load_scale_kw[None,None,:],.35,.85)
    pv=np.clip(exp.PV_OFFSET+exp.PV_GAIN*pv/dev.train_pv_scale_kw[None,None,:],0,1)
    rows=[]; bound_rows=[]; trace_rows=[]; nday=min(max_days,load.shape[0]); ng=min(groups,load.shape[2])
    for site in SITES:
      feeder=ACSnapshotFeeder(exp.FEEDER_PATH,battery_sites=(site,),pv_sites={'675.1':exp.PV_RATED_KW},voltage_limits=exp.VOLTAGE_LIMITS,line_loading_limit=exp.LINE_LIMIT)
      for day in range(nday):
       for g in range(ng):
        ld=load[day,:HORIZON_INTERVALS,g]; pv_d=pv[day,:HORIZON_INTERVALS,g]; charge,export,reasons=_bounds(feeder,ld,pv_d,site); baseline_feasible=int(len(reasons)==0)
        for t in range(HORIZON_INTERVALS): bound_rows.append({'date':dates[day],'day_index':day,'group':g,'site':site,'interval':t,'charge_limit_kw':charge[t],'export_limit_kw':export[t]})
        common=dict(charge_limit_kw=charge,export_limit_kw=export,load_kw=ld,service_windows=WINDOWS,recovery_windows=RECOVERY_WINDOWS,energy_kwh=BATTERY_ENERGY_KWH,initial_soc=exp.SOC_INITIAL,terminal_soc_target=exp.SOC_INITIAL,soc_min=exp.SOC_RESERVE,soc_max=1.0,eta_charge=exp.ETA_CHARGE,eta_discharge=exp.ETA_DISCHARGE,dt_h=exp.DT_H,terminal_mode='exact')
        for method,kw in {'network_lp':dict(mode='network_lp'),'fixed_recovery':dict(mode='fixed_recovery',fixed_recovery_ratio=REARM_RATIO),'myopic_recovery':dict(mode='myopic_recovery'),'energy_only':dict(mode='energy_only')}.items():
          r=plan_service(**common,**kw); ok,audits=_replay(feeder,ld,pv_d,site,r); rows.append({'date':dates[day],'day_index':day,'group':g,'site':site,'method':method,'service_kw':r.service_kw,'planner_feasible':int(r.feasible),'replay_feasible':int(ok),'baseline_feasible':baseline_feasible,'terminal_soc':r.terminal_soc,'max_vmax':max((a.vmax for a in audits if np.isfinite(a.vmax)),default=np.nan),'max_loading':max((a.max_line_loading for a in audits if np.isfinite(a.max_line_loading)),default=np.nan),'message':r.message});
          if day == 0 and g == 0 and site == SITES[0]: trace_rows.extend({'interval':t,'method':method,'charge_kw':r.charge_kw[t],'discharge_kw':r.discharge_kw[t],'soc':r.soc[t],'grid_import_kw':r.grid_import_kw[t],'charge_limit_kw':charge[t],'export_limit_kw':export[t]} for t in range(len(ld)))
    out_dir.mkdir(parents=True,exist_ok=True); df=pd.DataFrame(rows); df.to_csv(out_dir/'policy_rows.csv',index=False);pd.DataFrame(bound_rows).to_csv(out_dir/'ac_bounds.csv',index=False);pd.DataFrame(trace_rows).to_csv(out_dir/'representative_trace.csv',index=False)
    grouped=df.groupby(['site','method'],as_index=False).agg(mean_service_kw=('service_kw','mean'),replay_success=('replay_feasible','mean'),baseline_success=('baseline_feasible','mean'),n=('service_kw','size')); conditional=df[df.baseline_feasible==1].groupby(['site','method'],as_index=False).agg(conditional_replay_success=('replay_feasible','mean'),conditional_mean_service_kw=('service_kw','mean'),n_baseline=('service_kw','size')); summary={'status':'network_recovery_external_v1','source':str(source),'n_days':nday,'n_groups':ng,'battery_energy_kwh':BATTERY_ENERGY_KWH,'summary':grouped.to_dict(orient='records'),'conditional_summary':conditional.to_dict(orient='records')};(out_dir/'summary.json').write_text(json.dumps(summary,indent=2));return summary
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--max-days',type=int,default=12);ap.add_argument('--groups',type=int,default=10);ap.add_argument('--out-dir',type=Path,default=OUT);ap.add_argument('--source',type=Path,default=ROOT/'data/processed/ausgrid_external_2012_2013.npz');a=ap.parse_args();print(json.dumps(run(a.max_days,a.groups,a.out_dir,a.source),indent=2))

#!/usr/bin/env python3
"""Evaluate the frozen development policy on Ausgrid 2011--2012 profiles."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
from recoveryflex.profile_bank import load_bank
import run_corrected_experiment as exp
from recoveryflex.ac_snapshot import ACSnapshotFeeder

EXT=ROOT/'data/processed/ausgrid_external_2011_2012.npz'
OUT=ROOT/'results/external_validation_v1'

def run(offer_kw: float=140.0, out_dir: Path=OUT):
    dev=load_bank(exp.BANK_PATH)
    x=np.load(EXT,allow_pickle=False)
    load=np.asarray(x['load_kw'],float); pv=np.asarray(x['pv_kw'],float)
    # external bank is day,group,interval; embed with development-year scales
    load=np.transpose(load,(0,2,1)); pv=np.transpose(pv,(0,2,1))
    load=np.clip(exp.LOAD_OFFSET+exp.LOAD_GAIN*load/dev.train_load_scale_kw[None,None,:],.35,.85)
    pv=np.clip(exp.PV_OFFSET+exp.PV_GAIN*pv/dev.train_pv_scale_kw[None,None,:],0,1)
    dates=x['dates'].astype(str)
    f=ACSnapshotFeeder(exp.FEEDER_PATH,battery_sites=(exp.BATTERY_SITE,),pv_sites={'675.1':exp.PV_RATED_KW},voltage_limits=exp.VOLTAGE_LIMITS,line_loading_limit=exp.LINE_LIMIT)
    rows=[]
    for day in range(load.shape[0]):
      for g in range(load.shape[2]):
       for event_id,start in enumerate(exp.SERVICE_STARTS,1):
        r=exp.evaluate_event(f,load[:,:,g],pv[:,:,g],day,int(start),offer_kw,exp.SOC_INITIAL)
        rows.append({'date':dates[day],'day_index':day,'group':g,'event_id':event_id,'offer_kw':offer_kw,'ok':int(r.ok),'ac_ok':int(r.ac_ok),'energy_ok':int(r.energy_ok),'vmin':r.vmin,'vmax':r.vmax,'max_loading':r.max_loading,'service_realized_kw':r.service_realized_kw,'recovery_realized_kw':r.recovery_realized_kw,'error':r.error})
    df=pd.DataFrame(rows); out_dir.mkdir(parents=True,exist_ok=True); df.to_csv(out_dir/'external_rows.csv',index=False)
    day=df.groupby('date',as_index=False).ok.mean()
    summary={'status':'external_validation_v1','offer_kw':offer_kw,'n_days':int(df.date.nunique()),'n_groups':int(df.group.nunique()),'n_events':len(df),'event_success':float(df.ok.mean()),'day_success':float(day.ok.mean()),'day_bootstrap_ci':None,'source':str(EXT)}
    rng=np.random.default_rng(20261003); vals=day.ok.to_numpy(float); boots=np.array([rng.choice(vals,size=len(vals),replace=True).mean() for _ in range(5000)]); summary['day_bootstrap_ci']=[float(np.quantile(boots,.025)),float(np.quantile(boots,.975))]
    (out_dir/'external_summary.json').write_text(json.dumps(summary,indent=2)); return summary

if __name__=='__main__': print(json.dumps(run(),indent=2))

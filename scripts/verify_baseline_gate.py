#!/usr/bin/env python3
"""Verify p=0 AC feasibility for every external-year profile unit."""
from __future__ import annotations
import argparse, json, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
import run_corrected_experiment as exp
from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.profile_bank import load_bank

def _chunk(start, stop, source, sites):
    dev=load_bank(exp.BANK_PATH); x=np.load(source,allow_pickle=False)
    load=np.transpose(x['load_kw'],(0,2,1)); pv=np.transpose(x['pv_kw'],(0,2,1)); dates=x['dates'].astype(str)
    load=np.clip(exp.LOAD_OFFSET+exp.LOAD_GAIN*load/dev.train_load_scale_kw[None,None,:],.35,.85)
    pv=np.clip(exp.PV_OFFSET+exp.PV_GAIN*pv/dev.train_pv_scale_kw[None,None,:],0,1)
    out=[]
    for site in sites:
      feeder=ACSnapshotFeeder(exp.FEEDER_PATH,battery_sites=(site,),pv_sites={'675.1':exp.PV_RATED_KW},voltage_limits=exp.VOLTAGE_LIMITS,line_loading_limit=exp.LINE_LIMIT)
      for day in range(start,stop):
       for g in range(load.shape[2]):
        ok=True; reasons=[]
        for t in range(48):
         a=feeder.solve(float(load[day,t,g]),float(pv[day,t,g]),{site:0.0})
         if not a.feasible:
          ok=False; reasons.append(f'{t}:zero:{a.error}')
        out.append({'date':dates[day],'day_index':day,'group':g,'site':site,'baseline_zero_feasible':int(ok),'reason_count':len(reasons),'reasons':' | '.join(reasons[:4])})
    return pd.DataFrame(out)

def run(source,out,sites,workers):
    x=np.load(source,allow_pickle=False); days=x['load_kw'].shape[0]; edges=[round(i*days/workers) for i in range(workers+1)]
    frames=[]
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn')) as pool:
      fs=[pool.submit(_chunk,edges[i],edges[i+1],source,sites) for i in range(workers)]
      for f in as_completed(fs): frames.append(f.result())
    d=pd.concat(frames,ignore_index=True).sort_values(['day_index','group','site'])
    out.parent.mkdir(parents=True,exist_ok=True); d.to_csv(out,index=False)
    return {'n_units':len(d),'n_fail':int((d.baseline_zero_feasible==0).sum()),'by_site':d.groupby('site').baseline_zero_feasible.mean().to_dict()}

if __name__=='__main__':
 ap=argparse.ArgumentParser(); ap.add_argument('--source',type=Path,default=ROOT/'data/processed/ausgrid_external_2012_2013_strict.npz'); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--sites',default='611.3,634.1'); ap.add_argument('--workers',type=int,default=4); a=ap.parse_args(); print(json.dumps(run(a.source,a.out,tuple(s for s in a.sites.split(',') if s),a.workers),indent=2))

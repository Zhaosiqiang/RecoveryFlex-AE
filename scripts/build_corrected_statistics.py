#!/usr/bin/env python3
"""Compute day-clustered uncertainty summaries from frozen corrected outputs."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
R=ROOT/'results/corrected_v1'
rng=np.random.default_rng(20261003)
rows=pd.read_csv(R/'corrected_experiment_rows.csv')
seq=pd.read_csv(R/'sequence_capacity.csv')
summary={}
for split in ['train','cal','test']:
 g=rows[(rows.phase=='single')&(rows.split==split)].groupby('date').ok.mean().to_numpy(float)
 samples=g[rng.integers(0,len(g),size=(20000,len(g)))].mean(axis=1)
 summary[f'{split}_day_cluster_success']={'n_days':int(len(g)),'mean':float(g.mean()),'ci95':[float(np.quantile(samples,.025)),float(np.quantile(samples,.975))]}
for mode in ['full_rearm','reserve_limited']:
 summary[mode]={}
 for m in range(1,7):
  x=seq[(seq['mode']==mode)&(seq.events==m)].capacity_kw.to_numpy(float)
  summary[mode][str(m)]={'n_days':int(len(x)),'median':float(np.median(x)),'q25':float(np.quantile(x,.25)),'q75':float(np.quantile(x,.75)),'min':float(x.min()),'max':float(x.max())}
pa=pd.read_csv(R/'realized_power_audit.csv')
summary['readback']={'max_abs_error_kw':float(np.abs(pa.error_kw).max()),'commands_kw':pa.command_kw.tolist()}
(R/'statistical_summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))

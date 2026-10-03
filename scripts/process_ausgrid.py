"""Create small, date-aware Ausgrid features without random row splitting."""
from pathlib import Path
import pandas as pd, numpy as np, json, hashlib
ROOT=Path(__file__).resolve().parents[1]
fp=ROOT/'data/raw/ausgrid/Solar home 2010-2011.csv'
# first row is the original source warning; header is the second row
raw=pd.read_csv(fp,skiprows=[0])
raw['date']=pd.to_datetime(raw['date'],dayfirst=True,errors='coerce')
time_cols=[c for c in raw.columns if ':' in str(c)]
for c in time_cols: raw[c]=pd.to_numeric(raw[c],errors='coerce')
# household consumption (GC) and gross generation (GG) in kWh per half hour
agg=(raw[raw['Consumption Category'].isin(['GC','GG'])]
 .groupby(['Customer','date','Consumption Category'],as_index=False)[time_cols].mean())
gc=agg[agg['Consumption Category']=='GC'].set_index(['Customer','date'])[time_cols]
gg=agg[agg['Consumption Category']=='GG'].set_index(['Customer','date'])[time_cols]
idx=gc.index.intersection(gg.index)
rows=[]
for c,d in idx:
 load=gc.loc[(c,d)].to_numpy(float); pv=gg.loc[(c,d)].to_numpy(float)
 rows.append({'customer':int(c),'date':str(d.date()),'season':('winter' if d.month in [6,7,8] else 'summer' if d.month in [12,1,2] else 'shoulder'),
  'load_kwh':float(load.sum()),'pv_kwh':float(pv.sum()),'load_peak_kw':float(load.max()*2),'pv_peak_kw':float(pv.max()*2),
  'net_peak_kw':float((load-pv).max()*2),'net_min_kw':float((load-pv).min()*2),
  'load_ramp_kw':float(np.abs(np.diff(load*2)).max()),'pv_ramp_kw':float(np.abs(np.diff(pv*2)).max())})
out=ROOT/'data/processed/ausgrid_daily_features.csv'; out.parent.mkdir(exist_ok=True); pd.DataFrame(rows).to_csv(out,index=False)
meta={'source_file':str(fp),'source_sha256':hashlib.sha256(fp.read_bytes()).hexdigest(),'n_rows':len(rows),'n_customers':int(pd.DataFrame(rows).customer.nunique()),'date_min':str(pd.DataFrame(rows).date.min()),'date_max':str(pd.DataFrame(rows).date.max()),'note':'GC/GG paired customer-days only; no random row split; derived features for scenario scaling.'}
(ROOT/'data/processed/ausgrid_manifest.json').write_text(json.dumps(meta,indent=2))
print(json.dumps(meta,indent=2))

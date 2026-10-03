from pathlib import Path
import pandas as pd,numpy as np,json,hashlib
ROOT=Path(__file__).resolve().parents[1]; fp=ROOT/'data/raw/opsd_household_15min.csv'
df=pd.read_csv(fp,usecols=['utc_timestamp','DE_KN_residential1_grid_import','DE_KN_residential1_pv','interpolated'])
df['timestamp']=pd.to_datetime(df.utc_timestamp,utc=True); df['date']=df.timestamp.dt.date
df['load']=pd.to_numeric(df.DE_KN_residential1_grid_import,errors='coerce'); df['pv']=pd.to_numeric(df.DE_KN_residential1_pv,errors='coerce').clip(lower=0)
df=df.dropna(subset=['load','pv'])
rows=[]
for date,g in df.groupby('date'):
 if len(g)<80: continue
 l=g.load.to_numpy(float); pv=g.pv.to_numpy(float)
 rows.append({'date':str(date),'season':('winter' if pd.Timestamp(date).month in [12,1,2] else 'summer' if pd.Timestamp(date).month in [6,7,8] else 'shoulder'),'load_kwh':float(l.sum()*.25),'pv_kwh':float(pv.sum()*.25),'load_peak_kw':float(l.max()),'pv_peak_kw':float(pv.max()),'net_peak_kw':float((l-pv).max()),'net_min_kw':float((l-pv).min()),'interpolated_fraction':float(g.interpolated.notna().mean())})
out=ROOT/'data/processed/opsd_daily_features.csv'; pd.DataFrame(rows).to_csv(out,index=False)
meta={'source': 'Open Power System Data Household Data 2020-04-15','source_url':'https://data.open-power-system-data.org/household_data/2020-04-15/household_data_15min_singleindex.csv','source_sha256':hashlib.sha256(fp.read_bytes()).hexdigest(),'n_days':len(rows),'note':'DE_KN_residential1 grid_import and pv; daily features; no random row split.'}
(ROOT/'data/processed/opsd_manifest.json').write_text(json.dumps(meta,indent=2)); print(json.dumps(meta,indent=2))

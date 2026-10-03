from pathlib import Path
import pandas as pd, numpy as np, json
ROOT=Path(__file__).resolve().parents[1]
df=pd.read_csv(ROOT/'data/processed/ausgrid_daily_features.csv',parse_dates=['date'])
# Date-aware representative set: per season, choose low/median/high net-load and PV days.
df['load_rank']=df.groupby('season')['load_kwh'].rank(pct=True)
df['pv_rank']=df.groupby('season')['pv_kwh'].rank(pct=True)
targets=[(.15,.15),(.50,.50),(.85,.85),(.85,.15)]
rows=[]
for season in sorted(df.season.unique()):
 sub=df[df.season==season].copy()
 for j,(lr,pr) in enumerate(targets):
  sub['dist']=(sub.load_rank-lr)**2+(sub.pv_rank-pr)**2
  r=sub.sort_values('dist').iloc[0]
  rows.append({'scenario':f'{season}_{j+1}','customer':int(r.customer),'date':r.date.date().isoformat(),'season':season,
   'load_scale':float(np.clip(.50+.25*r.load_rank,.50,.75)),
   'pv_fraction':float(np.clip(.20+.75*r.pv_rank,.20,.95)),
   'source_load_kwh':float(r.load_kwh),'source_pv_kwh':float(r.pv_kwh),'load_rank':float(r.load_rank),'pv_rank':float(r.pv_rank)})
out=ROOT/'data/processed/ausgrid_scenarios.csv'; pd.DataFrame(rows).to_csv(out,index=False)
(ROOT/'data/processed/ausgrid_scenarios_manifest.json').write_text(json.dumps({'n_scenarios':len(rows),'selection':'four joint load/PV quantile representatives per season; one customer-day per representative; no random row split'},indent=2))
print(pd.DataFrame(rows).to_string(index=False))

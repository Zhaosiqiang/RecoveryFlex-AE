from pathlib import Path
import pandas as pd,numpy as np,json
ROOT=Path(__file__).resolve().parents[1]; df=pd.read_csv(ROOT/'data/processed/opsd_daily_features.csv')
df['lr']=df.groupby('season').load_kwh.rank(pct=True); df['pr']=df.groupby('season').pv_kwh.rank(pct=True)
rows=[]
for season in sorted(df.season.unique()):
 sub=df[df.season==season].copy(); sub['d']=(sub.lr-.5)**2+(sub.pr-.5)**2
 for j,(_,r) in enumerate(sub.nsmallest(2,'d').iterrows()):
  rows.append({'scenario':f'opsd_{season}_{j+1}','date':r.date,'season':season,'load_scale':float(np.clip(.50+.25*r.lr,.50,.75)),'pv_fraction':float(np.clip(.20+.75*r.pr,.20,.95)),'interpolated_fraction':r.interpolated_fraction,'load_rank':r.lr,'pv_rank':r.pr})
out=ROOT/'data/processed/opsd_scenarios.csv'; pd.DataFrame(rows).to_csv(out,index=False); print(pd.DataFrame(rows).to_string(index=False))

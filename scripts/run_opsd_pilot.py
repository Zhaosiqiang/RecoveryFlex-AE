from pathlib import Path
import sys,numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
from run_pilot import find_offer
sc=pd.read_csv(ROOT/'data/processed/opsd_scenarios.csv'); rows=[]
for _,s in sc.iterrows():
 for site in ('634.1','645.2'):
  for tele in (0.0,1.0):
   for err in (0.0,.1):
    offer,ok,soc,aud=find_offer(site,float(s.load_scale),float(s.pv_fraction),1.0,2.0,tele,err,True)
    rows.append({'scenario':s.scenario,'date':s.date,'site':site,'telemetry':tele,'forecast_error':err,'service_kw':offer.service_kw,'accepted':int(ok),'min_v':min((a.vmin for a in aud),default=np.nan),'max_line':max((a.max_line_loading for a in aud),default=np.nan)})
out=ROOT/'results/opsd_pilot.csv'; pd.DataFrame(rows).to_csv(out,index=False); print(pd.DataFrame(rows).groupby(['telemetry','forecast_error']).service_kw.mean().round(1))

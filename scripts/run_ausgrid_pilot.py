from pathlib import Path
import sys,json,csv,numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
from run_pilot import find_offer
sc=pd.read_csv(ROOT/'data/processed/ausgrid_scenarios.csv')
rows=[]
for _,s in sc.iterrows():
 for site in ('634.1','645.2'):
  for dur in (.25,1.0):
   for rec in (1.0,4.0):
    for tele in (0.0,.5,1.0):
     for err in (0.0,.1):
      offer,ok,soc,aud=find_offer(site,float(s.load_scale),float(s.pv_fraction),dur,rec,tele,err,True)
      rows.append({'scenario':s.scenario,'season':s.season,'customer':s.customer,'date':s.date,'site':site,'duration_h':dur,'recovery_h':rec,'telemetry':tele,'forecast_error':err,'accepted':int(ok),'service_kw':offer.service_kw,'soc_final':soc,'min_v_pu':min((a.vmin for a in aud),default=np.nan),'max_v_pu':max((a.vmax for a in aud),default=np.nan),'max_line_loading':max((a.max_line_loading for a in aud),default=np.nan),'mean_loss_kw':np.mean([a.total_loss_kw for a in aud]) if aud else np.nan})
out=ROOT/'results/ausgrid_envelope.csv'; pd.DataFrame(rows).to_csv(out,index=False)
print('rows',len(rows),'accepted',sum(r['accepted'] for r in rows),'mean_kw',np.mean([r['service_kw'] for r in rows]))

from pathlib import Path
import sys,numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from recoveryflex import FeederModel, BatterySpec, robust_margin
SPEC=BatterySpec(power_kw=150,energy_kwh=300,soc_initial=.70,soc_target=.70); DT=.25
MASTER=ROOT/'data/raw/ieee123_qsts/master.dss'; SITES=('47.1','65.2','79.3'); sc=pd.read_csv(ROOT/'data/processed/ausgrid_scenarios.csv').iloc[[2,6,10]]
def aud(m,site,p,dur,rec,l,pv,M):
 ns=round(dur/DT); nr=round(rec/DT); pc=min(150,p*dur/rec/(.95*.95)); soc=.7; vals=[]
 for q in ([p]*ns+[-pc]*nr)*M:
  soc += (-q*DT/.95/300) if q>=0 else ((-q)*DT*.95/300)
  if not .05<=soc<=.95: return False,soc,vals
  a=m.solve(load_scale=l*1.1,pv_fraction=pv*.9,p_kw={site:q}); vals.append(a)
  if not a.feasible: return False,soc,vals
 return soc>=.7-1e-9,soc,vals
rows=[]
for _,s in sc.iterrows():
 for site in SITES:
  m=FeederModel(MASTER,battery_sites=SITES,battery_kw=150,battery_kwh=300,v_limits=(.95,1.06),line_limit=1.10)
  for rec in (1.0,2.0):
   for M in (1,2,3):
    best=0
    for p in (0,25,50,75,100,125,150):
     ok,soc,v=aud(m,site,p,2.0,rec,float(s.load_scale),float(s.pv_fraction),M)
     if ok: best=p
    ok,soc,v=aud(m,site,best,2.0,rec,float(s.load_scale),float(s.pv_fraction),M)
    rows.append({'scenario':s.scenario,'site':site,'duration_h':2,'recovery_h':rec,'events':M,'service_kw':best,'accepted':int(ok),'terminal_soc':soc,'min_v':min((x.vmin for x in v),default=np.nan),'max_line':max((x.max_line_loading for x in v),default=np.nan)})
out=ROOT/'results/ieee123_stress.csv'; pd.DataFrame(rows).to_csv(out,index=False); print(pd.DataFrame(rows).groupby(['recovery_h','events']).service_kw.agg(['mean','min','max']))

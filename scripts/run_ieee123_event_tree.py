from pathlib import Path
import sys,numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from recoveryflex import FeederModel
SPEC={'eta_c':.95,'eta_d':.95,'e':300,'soc0':.70,'target':.70,'pmax':150}; DT=.25
MASTER=ROOT/'data/raw/ieee123_qsts/master.dss'; SITES=('47.1','65.2','79.3')
sc=pd.read_csv(ROOT/'data/processed/ausgrid_scenarios.csv').set_index('scenario')
# Service is tested at high-PV days; successive recovery windows use increasingly stressed days.
paths=[['shoulder_3','shoulder_2','shoulder_3','shoulder_3'],['summer_3','summer_2','summer_3','summer_3']]

def replay(m,site,p,dur,rec,M,path):
 ns=round(dur/DT); nr=round(rec/DT); pc=min(150,p*dur/rec/(.95*.95)); soc=.7; audits=[]
 for k in range(M):
  service=sc.loc[path[min(2*k,len(path)-1)]]; recovery=sc.loc[path[min(2*k+1,len(path)-1)]]
  for q in [p]*ns:
   soc-=q*DT/.95/300; a=m.solve(load_scale=float(service.load_scale),pv_fraction=float(service.pv_fraction),p_kw={site:q}); audits.append(a)
   if not a.feasible or soc<.05: return False,soc,audits
  for q in [-pc]*nr:
   soc+=(-q)*DT*.95/300; load_r=float(recovery.load_scale)*(1.0 if k==0 else 1.10); pv_r=float(recovery.pv_fraction)*(1.0 if k==0 else 0.90); a=m.solve(load_scale=load_r,pv_fraction=pv_r,p_kw={site:q}); audits.append(a)
   if not a.feasible or soc>.95: return False,soc,audits
 if soc<.70-1e-8: return False,soc,audits
 return True,soc,audits
rows=[]
for pi,path in enumerate(paths):
 for site in SITES:
  m=FeederModel(MASTER,battery_sites=SITES,battery_kw=150,battery_kwh=300,v_limits=(.95,1.06),line_limit=1.08)
  for rec in (1.0,2.0,4.0):
   for M in (1,2,3):
    best=0
    for p in (0,25,50,75,100,125,150):
     ok,soc,aud=replay(m,site,p,1.0,rec,M,path)
     if ok: best=p
    ok,soc,aud=replay(m,site,best,1.0,rec,M,path)
    rows.append({'path':pi,'site':site,'duration_h':1,'recovery_h':rec,'events':M,'service_kw':best,'accepted':int(ok),'soc':soc,'min_v':min((a.vmin for a in aud),default=np.nan),'max_line':max((a.max_line_loading for a in aud),default=np.nan)})
out=ROOT/'results/ieee123_event_tree.csv'; pd.DataFrame(rows).to_csv(out,index=False); print(pd.DataFrame(rows).groupby(['path','recovery_h','events']).service_kw.mean().round(1))

from pathlib import Path
import sys,csv,numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from recoveryflex import FeederModel, BatterySpec, robust_margin
SPEC=BatterySpec(power_kw=150,energy_kwh=300,soc_initial=.70,soc_target=.70); DT=.25
MASTER=ROOT/'data/raw/ieee123_qsts/master.dss'; SITES=('47.1','65.2','79.3')
sc=pd.read_csv(ROOT/'data/processed/ausgrid_scenarios.csv').iloc[[0,2,4,6,8,10]]

def audit(model,site,p,dur,rec,load,pv,err,M):
 ns=max(1,round(dur/DT)); nr=max(1,round(rec/DT)); pc=min(SPEC.power_kw,p*dur/max(rec,DT)/(SPEC.eta_charge*SPEC.eta_discharge))
 pat=([p]*ns+[-pc]*nr)*M; soc=SPEC.soc_initial; aud=[]
 for q in pat:
  soc += (-q*DT/SPEC.eta_discharge/SPEC.energy_kwh) if q>=0 else ((-q)*DT*SPEC.eta_charge/SPEC.energy_kwh)
  if soc<SPEC.soc_min-1e-9 or soc>SPEC.soc_max+1e-9: return False,soc,aud
  a=model.solve(load_scale=load*(1+err),pv_fraction=max(0,pv*(1-err)),p_kw={site:q}); aud.append(a)
  if not a.feasible: return False,soc,aud
 return bool(soc>=SPEC.soc_target-1e-9),soc,aud
rows=[]
for _,s in sc.iterrows():
 for site in SITES:
  model=FeederModel(MASTER,battery_sites=SITES,battery_kw=SPEC.power_kw,battery_kwh=SPEC.energy_kwh,v_limits=(.95,1.06),line_limit=1.05)
  for dur in (1.0,):
   for rec in (2.0,4.0):
    for tele in (0.0,1.0):
     for M in (1,2,3):
      derate=max(0,1-3*robust_margin(tele,.10)); best=0
      for req in (0,50,100,150):
       p=req*derate; ok,soc,aud=audit(model,site,p,dur,rec,float(s.load_scale),float(s.pv_fraction),.10,M)
       if ok: best=p
      ok,soc,aud=audit(model,site,best,dur,rec,float(s.load_scale),float(s.pv_fraction),.10,M)
      rows.append({'scenario':s.scenario,'site':site,'duration_h':dur,'recovery_h':rec,'telemetry':tele,'events':M,'service_kw':best,'accepted':int(ok),'min_v_pu':min((a.vmin for a in aud),default=np.nan),'max_line_loading':max((a.max_line_loading for a in aud),default=np.nan),'terminal_soc':soc})
print('rows',len(rows),'accepted',sum(r['accepted'] for r in rows))
out=ROOT/'results/ieee123_sequence.csv'; pd.DataFrame(rows).to_csv(out,index=False)
print(pd.DataFrame(rows).groupby(['events','recovery_h','telemetry']).service_kw.mean().round(1))

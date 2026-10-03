from pathlib import Path
import sys,csv,numpy as np
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'scripts'))
from recoveryflex import FeederModel
from run_pilot import audit_sequence, SPEC
MASTER=ROOT/'data/raw/ieee123_qsts/master.dss'; SITES=('47.1','65.2','79.3')
rows=[]
for site in SITES:
 for load in (.5,.7):
  for pv in (.5,.9):
   for dur in (.5,1.0):
    for rec in (2.0,4.0):
     model=FeederModel(MASTER,battery_sites=SITES,battery_kw=SPEC.power_kw,battery_kwh=SPEC.energy_kwh,v_limits=(.95,1.06),line_limit=1.05)
     best=None
     for p in [0,50,100,150]:
      ok,soc,aud=audit_sequence(model,site,p,dur,rec,load,pv,.10,True)
      if ok: best=(p,soc,aud)
     p,soc,aud=best if best is not None else (0,SPEC.soc_initial,[])
     rows.append({'site':site,'load_scale':load,'pv_fraction':pv,'duration_h':dur,'recovery_h':rec,'service_kw':p,'accepted':int(best is not None),'min_v_pu':min((a.vmin for a in aud),default=np.nan),'max_line_loading':max((a.max_line_loading for a in aud),default=np.nan)})
out=ROOT/'results/ieee123_smoke.csv'; out.parent.mkdir(exist_ok=True); csv.DictWriter(out.open('w',newline=''),fieldnames=list(rows[0])).writeheader();
with out.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print('rows',len(rows),'accepted',sum(r['accepted'] for r in rows),'mean',np.mean([r['service_kw'] for r in rows]))

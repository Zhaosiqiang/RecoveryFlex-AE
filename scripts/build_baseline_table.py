from pathlib import Path
import pandas as pd, numpy as np
ROOT=Path(__file__).resolve().parents[1]; x=pd.read_csv(ROOT/'results/ieee123_event_tree.csv')
g=x.groupby(['recovery_h','events']).service_kw.mean().reset_index(name='proposed_ac_kw')
rows=[]
for _,r in g.iterrows():
 h=float(r.recovery_h); m=int(r.events); p_soc=min(150,150*h*.95*.95/1.0); p_ac=float(r.proposed_ac_kw); rows.append({'recovery_h':h,'events':m,'copper_plate_soc_kw':p_soc,'proposed_ac_kw':p_ac,'sequence_contraction':np.nan if m==1 else p_ac/float(g[(g.recovery_h==h)&(g.events==m-1)].proposed_ac_kw.iloc[0]),'network_recovery_penalty':1-p_ac/p_soc})
out=ROOT/'results/baseline_comparison.csv'; pd.DataFrame(rows).to_csv(out,index=False)
tex=pd.DataFrame(rows).to_latex(index=False,float_format=lambda z:f'{z:.3f}',caption='Copper-plate SOC upper bound versus AC-audited event-tree capacity.',label='tab:baseline')
(ROOT/'paper/tables').mkdir(exist_ok=True); (ROOT/'paper/tables/baseline_comparison.tex').write_text(tex)
print(pd.DataFrame(rows).round(3).to_string(index=False))

from pathlib import Path
import math,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
def wilson(k,n,z=1.96):
 if n==0:return [None,None]
 ph=k/n; den=1+z*z/n; cen=(ph+z*z/(2*n))/den; half=z*math.sqrt(ph*(1-ph)/n+z*z/(4*n*n))/den; return [cen-half,cen+half]
rows=[]
for name in ['pilot_envelope','ausgrid_envelope','opsd_pilot','ieee123_sequence','ieee123_event_tree','ieee123_stress']:
 p=ROOT/'results'/f'{name}.csv'
 if not p.exists(): continue
 df=pd.read_csv(p); k=int(df.accepted.sum()) if 'accepted' in df else 0; n=len(df); lo,hi=wilson(k,n)
 rows.append({'dataset':name,'n':n,'pass':k,'pass_rate':k/n if n else None,'wilson_low':lo,'wilson_high':hi,'mean_service_kw':df.service_kw.mean() if 'service_kw' in df else None})
out=ROOT/'results/metrics_report.csv'; pd.DataFrame(rows).to_csv(out,index=False); print(pd.DataFrame(rows).round(3).to_string(index=False))

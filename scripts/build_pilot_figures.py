from __future__ import annotations
from pathlib import Path
import sys
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
ROOT=Path(__file__).resolve().parents[1]
DF=pd.read_csv(ROOT/'results/pilot_envelope.csv')
OUT=ROOT/'figures'; OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,'axes.labelsize':9,'figure.dpi':180,'savefig.dpi':300,'axes.spines.top':False,'axes.spines.right':False})

def save(fig,name):
 fig.tight_layout(); fig.savefig(OUT/f'{name}.pdf',bbox_inches='tight'); fig.savefig(OUT/f'{name}.png',bbox_inches='tight'); plt.close(fig)

# Figure 1: method contract schematic
fig,ax=plt.subplots(figsize=(8.2,2.3)); ax.set_xlim(0,10); ax.set_ylim(0,3); ax.axis('off')
boxes=[(0.2,1.2,1.7,0.8,'telemetry +\nforecast error','''#E8F1FB'''),(2.4,1.2,1.7,0.8,'state uncertainty\nmargin','''#EAF5EA'''),(4.6,1.2,1.7,0.8,'service event\nP,D','''#FFF2CC'''),(6.8,1.2,1.7,0.8,'AC-constrained\nrecovery H','''#FCE4D6'''),(9.0,1.2,0.8,0.8,'repeat\npass','''#E4DFEC''')]
for x,y,w,h,t,c in boxes:
 ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.04,rounding_size=.06',facecolor=c,edgecolor='#2F5597',lw=1))
 ax.text(x+w/2,y+h/2,t,ha='center',va='center',fontsize=8)
for i in range(len(boxes)-1):
 x=boxes[i][0]+boxes[i][2]; x2=boxes[i+1][0]
 ax.add_patch(FancyArrowPatch((x+.03,1.6),(x2-.03,1.6),arrowstyle='-|>',mutation_scale=12,lw=1,color='#444'))
ax.text(5,0.55,'Accepted contract = service + recovery + terminal SOC, replayed in nonlinear OpenDSS AC power flow',ha='center',fontsize=9,fontweight='bold')
ax.text(5,2.45,'Hidden load/PV scenarios are used only for the final audit; telemetry changes the candidate uncertainty margin',ha='center',fontsize=8,color='#444')
save(fig,'fig1_contract_workflow')

# Figure 2: duration x recovery heatmap
sel=DF[(DF.telemetry==1.0)&(DF.forecast_error==0.10)]
g=sel.groupby(['duration_h','recovery_h']).service_kw.mean().unstack()
fig,ax=plt.subplots(figsize=(5.5,3.6)); im=ax.imshow(g.values,aspect='auto',cmap='viridis',vmin=0,vmax=150)
ax.set_xticks(range(len(g.columns)),[f'{x:g}' for x in g.columns]); ax.set_yticks(range(len(g.index)),[f'{x:g}' for x in g.index]); ax.set_xlabel('Recovery window H (h)'); ax.set_ylabel('Service duration D (h)'); ax.set_title('AC-audited repeatable service capacity (pilot mean, kW)')
for i in range(g.shape[0]):
 for j in range(g.shape[1]): ax.text(j,i,f'{g.iloc[i,j]:.0f}',ha='center',va='center',color='white' if g.iloc[i,j]<90 else 'black',fontsize=9)
fig.colorbar(im,ax=ax,label='Accepted service power (kW)'); save(fig,'fig2_duration_recovery_heatmap')

# Figure 3: telemetry information ablation
sel=DF[DF.forecast_error==0.10]
g=sel.groupby('telemetry').service_kw.agg(['mean','std']).reset_index()
fig,ax=plt.subplots(figsize=(5.6,3.4)); ax.errorbar(g.telemetry*100,g['mean'],yerr=g['std'],marker='o',capsize=3,lw=1.8,color='#1f77b4'); ax.set_xlabel('Telemetry coverage proxy (%)'); ax.set_ylabel('Accepted service power (kW)'); ax.set_title('Information ablation: forecast-error stress (pilot)'); ax.set_xticks([0,50,100]); ax.grid(axis='y',alpha=.25); save(fig,'fig3_telemetry_value')

# Figure 4: placement comparison
sel=DF[(DF.telemetry==1.0)&(DF.forecast_error==0.10)]
fig,ax=plt.subplots(figsize=(5.5,3.4)); data=[sel.loc[sel.site==s,'service_kw'] for s in sel.site.unique()]; ax.boxplot(data,labels=[s for s in sel.site.unique()],patch_artist=True,boxprops={'facecolor':'#9ecae1'},medianprops={'color':'#d62728','lw':2}); ax.set_xlabel('Battery placement (bus.phase)'); ax.set_ylabel('Accepted service power (kW)'); ax.set_title('Placement dependence of repeatable capacity'); ax.grid(axis='y',alpha=.25); save(fig,'fig4_placement_dependence')

# Figure 5: service/recovery trajectories
D=.0; dur=1.0; rec=4.0; p=120; n_s=round(dur/.25); n_r=round(rec/.25); x=np.arange(2*(n_s+n_r)+1)*.25
patt=np.r_[np.repeat(p,n_s),np.repeat(-p*dur/rec,n_r),np.repeat(p,n_s),np.repeat(-p*dur/rec,n_r)]
soc=[.7]
for q in patt: soc.append(soc[-1]-q*.25/.95/300 if q>=0 else soc[-1]+(-q)*.25*.95/300)
fig,ax1=plt.subplots(figsize=(7.0,3.3)); t=x[:-1]; ax1.step(t,patt,where='post',lw=2,color='#2ca02c',label='service (+) / recharge (−)'); ax1.axhline(0,color='#888',lw=.6); ax1.set_xlabel('Episode time (h)'); ax1.set_ylabel('Battery power (kW)'); ax1.axvspan(0,dur,color='#fee0d2',alpha=.5); ax1.axvspan(dur,dur+rec,color='#deebf7',alpha=.5); ax1.axvspan(dur+rec,2*dur+rec,color='#fee0d2',alpha=.5); ax1.axvspan(2*dur+rec,2*(dur+rec),color='#deebf7',alpha=.5); ax2=ax1.twinx(); ax2.plot(x,soc,'o-',color='#1f77b4',ms=2,lw=1.5,label='SOC'); ax2.axhline(.7,color='#1f77b4',ls='--',lw=.8); ax2.set_ylabel('SOC'); ax2.set_ylim(.4,.8); ax1.text(.5,ax1.get_ylim()[1]*.92,'event 1',ha='center',fontsize=8); ax1.text(dur+rec+.5,ax1.get_ylim()[1]*.92,'event 2',ha='center',fontsize=8); fig.suptitle('Repeated service requires recovery before the second call'); save(fig,'fig5_repeated_service_trace')

# Table summary
summ=(DF.groupby(['telemetry','forecast_error']).agg(accepted_rate=('accepted','mean'),service_kw_mean=('service_kw','mean'),service_kw_p10=('service_kw',lambda x:np.percentile(x,10)),service_kw_p90=('service_kw',lambda x:np.percentile(x,90)),vmin=('min_v_pu','min'),line_loading=('max_line_loading','max')).reset_index())
summ.to_csv(ROOT/'results/pilot_summary.csv',index=False)
print(summ.to_string(index=False))

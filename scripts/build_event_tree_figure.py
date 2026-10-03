from pathlib import Path
import pandas as pd, matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]; df=pd.read_csv(ROOT/'results/ieee123_event_tree.csv')
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'figure.dpi':180,'savefig.dpi':300,'axes.spines.top':False,'axes.spines.right':False})
g=df.groupby(['recovery_h','events']).service_kw.mean().reset_index()
fig,ax=plt.subplots(figsize=(6.3,3.6))
for h,sub in g.groupby('recovery_h'):
 ax.plot(sub.events,sub.service_kw,marker='o',lw=2,label=f'H={h:g} h')
ax.set_xticks([1,2,3]); ax.set_xlabel('Number of consecutive service calls, M'); ax.set_ylabel('Mean accepted service power (kW)'); ax.set_title('IEEE 123-node event-tree audit: sequence contraction'); ax.grid(axis='y',alpha=.25); ax.legend(frameon=False,ncol=3,loc='lower left'); fig.tight_layout();
for ext in ['pdf','png']: fig.savefig(ROOT/'figures'/f'fig6_event_tree_contraction.{ext}',bbox_inches='tight')

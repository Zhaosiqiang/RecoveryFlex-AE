from __future__ import annotations
import csv, json, math, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from recoveryflex import FeederModel, BatterySpec, candidate_offer

MASTER = ROOT / 'data' / 'raw' / 'IEEE13Nodeckt.dss'
DT = 0.25
SPEC = BatterySpec(power_kw=150, energy_kwh=300, soc_initial=.70, soc_target=.70)
SITES = ('634.1','645.2','675.1')


def audit_sequence(model, site, p_service, duration_h, recovery_h, load_scale, pv_fraction, hidden_error, two_events=True):
    """Replay service/recovery with perturbed hidden load/PV and own SOC accounting."""
    n_s = max(1, round(duration_h / DT)); n_r = max(1, round(recovery_h / DT))
    # charge just enough to close the energy debt, never above inverter limit
    p_charge = min(SPEC.power_kw, p_service * duration_h / max(recovery_h, DT) / (SPEC.eta_charge * SPEC.eta_discharge))
    pattern = [p_service] * n_s + [-p_charge] * n_r
    if two_events:
        pattern = pattern + [p_service] * n_s + [-p_charge] * n_r
    soc = SPEC.soc_initial
    audits=[]
    # Hidden perturbation is fixed within an episode, as in a forecast miss.
    load_hidden = load_scale * (1.0 + hidden_error)
    pv_hidden = max(0.0, pv_fraction * (1.0 - hidden_error))
    for p in pattern:
        if p >= 0:
            soc -= p * DT / SPEC.eta_discharge / SPEC.energy_kwh
        else:
            soc += (-p) * DT * SPEC.eta_charge / SPEC.energy_kwh
        if soc < SPEC.soc_min - 1e-9 or soc > SPEC.soc_max + 1e-9:
            return False, soc, audits
        a = model.solve(load_scale=load_hidden, pv_fraction=pv_hidden, p_kw={site: p})
        audits.append(a)
        if not a.feasible:
            return False, soc, audits
    if soc < SPEC.soc_target - 1e-9:
        return False, soc, audits
    return True, soc, audits


def find_offer(site, load_scale, pv_fraction, duration_h, recovery_h, telemetry, forecast_error, two_events=True):
    model = FeederModel(MASTER, battery_sites=SITES, battery_kw=SPEC.power_kw, battery_kwh=SPEC.energy_kwh,
                        v_limits=(.95,1.06), line_limit=1.05)
    best=None
    # monotone search over requested service. Candidate derating is telemetry conditioned;
    # AC audit is run at hidden error and never replaced by the reduced-order screen.
    for requested in np.linspace(0, SPEC.power_kw, 11):
        offer = candidate_offer(site, requested, duration_h, recovery_h, load_scale, pv_fraction,
                                telemetry, forecast_error, DT, SPEC)
        if not offer.candidate_feasible:
            continue
        ok, soc_final, audits = audit_sequence(model, site, offer.service_kw, duration_h, recovery_h,
                                               load_scale, pv_fraction, forecast_error, two_events)
        if ok:
            best=(offer, soc_final, audits)
        else:
            # Search is monotone for this pilot; continue to find smaller feasible values.
            continue
    if best is None:
        offer = candidate_offer(site, 0.0, duration_h, recovery_h, load_scale, pv_fraction,
                                telemetry, forecast_error, DT, SPEC)
        return offer, False, SPEC.soc_initial, []
    offer, soc_final, audits = best
    return offer, True, soc_final, audits


def main():
    rows=[]
    load_levels=(.50,.70)
    pv_levels=(.25,.95)
    durations=(.25,1.0)
    recoveries=(1.0,4.0)
    telemetries=(0.0,.50,1.0)
    errors=(0.0,.10)
    for site in SITES[:2]:
      for load in load_levels:
       for pv in pv_levels:
        for dur in durations:
         for rec in recoveries:
          for tele in telemetries:
           for err in errors:
            offer,ok,soc,audits=find_offer(site,load,pv,dur,rec,tele,err,True)
            rows.append({
              'site':site,'load_scale':load,'pv_fraction':pv,'duration_h':dur,'recovery_h':rec,
              'telemetry':tele,'forecast_error':err,'accepted':int(ok),'service_kw':offer.service_kw,
              'soc_final':soc,'n_audits':len(audits),
              'min_v_pu':min((a.vmin for a in audits),default=np.nan),
              'max_v_pu':max((a.vmax for a in audits),default=np.nan),
              'max_line_loading':max((a.max_line_loading for a in audits),default=np.nan),
              'mean_loss_kw':np.mean([a.total_loss_kw for a in audits]) if audits else np.nan,
              'false_safe':int(bool(offer.service_kw>0 and not ok)),
            })
    out=ROOT/'results'/'pilot_envelope.csv'; out.parent.mkdir(exist_ok=True)
    with out.open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    meta={'rows':len(rows),'master':str(MASTER),'seed':20261003,'dt_h':DT,'spec':SPEC.__dict__,'note':'pilot; all accepted trajectories replayed in OpenDSS'}
    (ROOT/'results'/'pilot_manifest.json').write_text(json.dumps(meta,indent=2))
    print(json.dumps(meta,indent=2))
    print('accepted',sum(r['accepted'] for r in rows),'/',len(rows))

if __name__=='__main__': main()

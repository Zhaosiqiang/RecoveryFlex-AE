# Adversarial review round 1 (Applied Energy reviewer 2)

**Date:** 2026-10-03  
**Candidate under review:** `RecoveryFlex_AE_2026`, corrected v1 working package  
**Review purpose:** try to falsify the claimed contribution before any manuscript is rewritten or submitted.

## Recommendation at this stage

**Reject in the current form; reconsider only after a major experimental redesign.** The corrected v1 pipeline is materially better than the invalidated pilot: it has command/readback checks, disjoint date splits, interval profiles, and a useful full-rearm control. Those checks establish software provenance. They do not yet establish that the paper's headline result is a new energy-system phenomenon. The reported sequence loss can be reproduced from the SOC recursion without running OpenDSS, and the network and profile models currently supply a relatively small, synthetic perturbation around that arithmetic.

The paper should not claim that it has measured a general repeated-service flexibility contract until the proposed falsification tests are run. A narrower methods/benchmark paper may be defensible if the claims are reduced accordingly.

## What I attempted to falsify

The working claim appears to be: an AC-audited, repeated service contract for a distribution-connected BESS can be identified by composing service and recovery actions, and a reserve-limited contract loses capacity as the number of calls increases. I tested four alternative explanations:

1. the decline is a deterministic SOC bookkeeping result chosen by the recovery ratio and battery size;
2. the OpenDSS feeder is only a feasibility wrapper around that arithmetic;
3. the measured profile bank is an artificial stress signal created by offsets, gains, clipping, one selected group, and an arbitrary PV rating;
4. the result has no demonstrated DSO or energy-system value beyond reporting a smaller number after repeated calls.

All four explanations remain plausible, and the current outputs do not rule them out.

## Blocking finding 1: the main sequence table is analytically predetermined

The corrected script fixes `E=500 kWh`, `SOC_initial=0.80`, `SOC_reserve=0.20`, four 30-minute service intervals, eight 30-minute recovery intervals, efficiencies 0.95/0.95, and a recovery command of `0.30P` (`scripts/run_corrected_experiment.py:44-56`). The reserve-limited SOC update in `evaluate_event` and the sequence loop (`:147-152`, `:283-291`) is

\[
\Delta s_d(P)=\frac{4(0.5)P}{0.95E}=0.0042105263P,
\qquad
\Delta s_r(P)=\frac{0.30P\,8(0.5)0.95}{E}=0.0022800000P.
\]

Thus the net loss after each completed call is `0.0019305263 P`. The largest feasible command before the `m`th service is exactly

\[
P_m^{\max}=\frac{(0.80-0.20)}{0.0042105263+(m-1)0.0019305263}.
\]

For `m=1,...,6`, this gives 142.50, 97.70, 74.33, 59.99, 50.28, and 43.28 kW. Rounding down to the predeclared 10-kW grid gives **140, 90, 70, 50, 50, 40 kW**, exactly the reported median sequence (`results/corrected_v1/statistical_summary.json`). The same values occur for every test day and the full-rearm values remain 140 kW for every event count.

This is not a failure of the arithmetic; it is evidence that the headline contraction is currently an expected consequence of the chosen battery and recovery contract. The OpenDSS replay cannot make the sequence result causal because the sequence capacity loop computes `ac_cache[p]` once per repeated copy and then changes only the SOC recursion (`:267-297`). In the current output, all 80 test days have the same reserve-limited capacities. A reviewer can therefore reproduce the central figure with a four-line algebraic calculation and no feeder, profiles, or uncertainty.

**Required repair.** Add an analytic baseline to the paper and report the residual network contribution separately. A valid claim would need a scenario in which the same SOC recursion predicts one capacity but AC replay changes it materially, or in which AC constraints alter the recovery policy and therefore the subsequent state. Report `P_M^{SOC}`, `P_M^{AC}`, their difference and cause labels for every day. If the curves remain identical, state explicitly that the experiment validates an auditable implementation of a recovery contract rather than discovering a new sequence effect.

## Blocking finding 2: the full-rearm control is a tautological negative control

The full-rearm ratio is set to `4/(8*0.95*0.95)=0.5540` (`:155-158`), which is selected precisely to return the SOC to 0.80. The repeated event is the same held-out event at the same start time, and the OpenDSS model is a deterministic static snapshot with controls off. Therefore `C_M=1` is required by construction whenever the event is feasible. It is a good software invariant, but it cannot by itself identify a network contribution or validate a learned contract.

The non-reset sequence is the complementary tautology: it repeats the identical event while carrying a deliberately incomplete recovery. The observed `C2=0.5` is an average of `[success, failure]` (`:242-254`), not a standard viability ratio and not a confidence statement. The capacity table is the meaningful object; the `C2` scalar should be removed or renamed.

**Required repair.** Keep the full-rearm test as a unit test, then add interventions that change one mechanism at a time: (i) reset SOC but retain the same AC trajectory; (ii) carry SOC but replace OpenDSS by an unconstrained copper plate; (iii) carry SOC and retain AC constraints; and (iv) carry SOC while applying measured, nonconstant battery power from the terminal readback. Pre-register the expected ordering and report failure cause (reserve, voltage, line, transformer, or command tracking). A two-way state-by-network factorial is the minimum causal design.

## Blocking finding 3: the profile bank is still an artificial stress embedding

The profile conversion itself is now auditable, but the experiment does not use the measured feeder load/PV trajectory. `_embed` maps one selected group to two clipped unitless factors (`scripts/run_corrected_experiment.py:73-85`):

```text
load_scale = clip(0.40 + 0.30 * load_kw / train_load_scale, 0.35, 0.85)
pv_fraction = clip(0.10 + 0.60 * pv_kw / train_pv_scale, 0.00, 1.00)
```

The run uses `GROUP=0` only (`:37`), ignores the other nine seeded groups, places a 300-kW fixed-P PV surrogate at `675.1`, and puts the battery at one phase (`611.3`) (`:38-43`, `:191-196`). The data therefore determine the *shape* of a stress signal, while the offsets, gains, clipping limits, group choice, network placement, and PV rating determine its physical magnitude. This is not yet evidence that an Ausgrid trajectory represents a feeder operating condition. It is a synthetic embedding whose parameters can move the offer from 140 kW to another grid point.

The 96.25% test rate also does not show a 95% contract guarantee. The day-cluster bootstrap already stored in `statistical_summary.json` gives a test mean of 0.9625 with a 95% interval of approximately [0.931, 0.988]. The lower limit is below 0.95. Under a predeclared one-sided 95% guarantee criterion, the current result fails that criterion even before accounting for model-form uncertainty.

**Required repair.** Run a predeclared embedding sensitivity on held-out dates: all ten customer groups, at least three PV ratings (for example 150/300/500 kW), at least two calibrated load scalings, and a waveform-preserving versus interval-shuffled negative control. Calibrate the scale by matching a documented feeder net-load or hosting-capacity quantity; do not tune it after observing the offer. Report the distribution of `P_1` and `P_M` across embeddings, not only the single group-0 run. If the ranking and failure causes are unstable, narrow the claim to an illustrative IEEE-13 stress study.

## Blocking finding 4: IEEE-13 snapshot physics do not support feeder-level generalization

The adapter is a useful deterministic audit, but the current experiment contains one static IEEE-13 feeder, one battery site, one phase, automatic controls disabled, and constant-PQ load surrogates (`src/recoveryflex/ac_snapshot.py:121-168`). It does not impose a battery inverter kVA/current limit, reactive-power capability, voltage-dependent clipping, ramp limit, SOC-dependent power limit, temperature/aging state, or a measured battery efficiency curve. `P` can therefore be commanded at any value that the ideal constant-power load accepts. The transformer check is a derived apparent-power ratio, but no explicit system-wide transformer/element thermal contract is documented as a study input.

The current output has only a small AC footprint at the selected offer: the test failures are six of 160 single-event audits, with `vmax` just over 1.05 pu or a line ratio just over 1.0. The sequence capacities nevertheless follow the SOC formula exactly, so the paper cannot say that an unbalanced distribution feeder materially shapes the repeated-service contract without showing an AC-active case.

As a quick adversarial replay, keeping the same profiles and voltage/current limits but changing only the fixed PV rating gave test-day AC pass rates at `P=140 kW` of 15.6%, 38.1%, 49.4%, 98.8%, 96.3%, 92.5%, 88.8%, and 72.5% for PV ratings 100, 150, 200, 250, 300, 350, 400, and 500 kW, respectively. The non-monotonic jump between 200 and 250 kW is a warning that the 300-kW choice is an operating-point selection, not a validated physical calibration. With the 300-kW PV fixed, moving the battery to `634.1`, `645.2`, `675.1`, or `692.3` produced 160/160 feasible test events at 140 kW, whereas the chosen `611.3` site produced 154/160. These are useful sensitivity diagnostics, but they cannot be turned into a main result without a predeclared placement and rating protocol.

**Required repair.** Repeat the frozen protocol on at least the IEEE-13 and IEEE-123 feeders (or one public realistic feeder with a documented transfer test), with near-source, mid-feeder, and remote placements and at least two phases. Add an inverter capability curve and a fixed kVA/ramp limit. Report AC-only and SOC-only frontiers, including cases where the network is the binding constraint. A strict 0.95--1.05 pu limit must be justified and accompanied by a sensitivity; it cannot be selected because it creates the desired 140-kW breakpoint.

## Blocking finding 5: no energy-system value has been demonstrated

The package reports a successful event fraction and a declining contract power. It does not show how a DSO, aggregator, or market operator would use that contract. There is no dispatch objective, tariff, avoided overload, PV curtailment, reliability benefit, reserve procurement cost, or comparison with a static one-event envelope. A 500-kWh ideal battery exporting 140 kW for two hours is an input to the study, not a system-level result.

This omission matters for Applied Energy: the paper needs to show that a sequence-aware contract changes an operational decision or a measurable energy outcome. Otherwise the contribution reads as a SOC bookkeeping demonstration on a test feeder.

**Required value experiment.** On the same held-out customer-days, run a fixed 24-h DSO dispatch with repeated activation opportunities (for example 2, 4, and 6 calls at the two service windows and later windows). Compare three frozen policies:

- a one-event/static envelope (`P_1` offered at every call);
- the proposed sequence contract (`P_M` or the state-dependent feasible command);
- an SOC-only oracle and an AC-feasible dispatch oracle as upper bounds.

Replay every dispatch in OpenDSS and report delivered service MWh, failed-call count, overload/voltage violation hours, PV curtailment, residual SOC, and a transparent avoided-cost or service-revenue metric under a fixed public or predeclared price. The key causal contrast is the operational loss caused by using the static envelope; the value of the proposed method is credible only if it materially reduces violations or improves net value at a stated reserve cost.

## Suggested minimum factorial experiment (pre-register before looking at results)

For every held-out date and service start, evaluate `M=1,...,6` and the fixed 10-kW command grid in this four-arm design:

| Arm | AC network | SOC state | Purpose |
|---|---|---|---|
| A | IEEE-13 replay | reset/re-arm | network-only repeatability control |
| B | copper plate (no voltage/thermal limits) | reset/re-arm | deterministic baseline |
| C | IEEE-13 replay | carry SOC with `r=0.30` | proposed contract |
| D | copper plate | carry SOC with `r=0.30` | SOC-only counterfactual |

For each arm, store the event-level failure cause and calculate `P_M`, cluster bootstrap intervals, and the difference-in-differences

\[
[(P_M^A-P_M^B)-(P_M^C-P_M^D)].
\]

The expected pattern is `A≈B` for re-arm, `C≈D` if SOC alone explains the decline, and a nonzero AC increment only when the feeder is actually binding. Add a fifth arm with a deliberately measured nonconstant battery command and state updates based on terminal readback to verify that the ideal constant-P surrogate is not driving the result. If the fourth-arm pattern is exactly the algebraic prediction, the paper must say so and move the novelty to contract auditing/operational use rather than sequence physics.

## Statistical and reporting requirements

- Define the independent resampling unit as a customer-day or feeder-day before the analysis. Report a day-cluster bootstrap or cluster-robust interval for every primary frontier and season/embedding subgroup.
- Predeclare whether a 95% contract means an observed rate above 0.95 or a lower confidence bound above 0.95. The current test interval does not support the latter.
- Report the 10-kW grid uncertainty (at least ±5 kW) and, where possible, refine the grid around the frontier.
- Separate `P_M^{SOC}`, `P_M^{AC}`, command/readback error, and profile embedding uncertainty. A single `ok` column hides the causal mechanism.
- Do not use `C2 = mean(success)/first_success` as the main effect size. Report the frontier, event-level survival probability, and failure cause instead.
- Every audit row must carry the actual calendar date, not only an array index; this is needed to reproduce the chronological split and to cluster uncertainty correctly.
- Keep the invalid V0 material out of all manuscript numbers and public release paths.

## Editorial gate for the next round

I would not recommend sending the current corrected v1 manuscript to Applied Energy. The minimum acceptable revision is the four-arm state-by-network counterfactual plus the profile/PV/placement sensitivity. To support an Applied Energy claim, add the held-out DSO dispatch value experiment. Only after these results show a reproducible network effect or a clearly quantified operational benefit should the title, abstract, highlights, and cover letter be finalized.

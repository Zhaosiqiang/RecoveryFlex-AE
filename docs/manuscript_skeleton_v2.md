# Manuscript skeleton for Applied Energy (v2)

**Working status.** This is a writing scaffold for the new network-feasible study. It is not a submission manuscript. Bracketed fields are evidence placeholders and must be replaced only after the independent-year run, statistical audit, figure review, and internal editorial/methods/adversarial checks are complete. No numerical result below is a claim.

## Front matter

### Proposed title

**Network-feasible recovery scheduling for repeated distribution-flexibility services: an AC--SOC benchmark on the IEEE 13-node feeder**

The current evidence supports this benchmark title. A market-clearing or economic title is not used because the study does not contain a validated cost model.

### Authors and affiliations

Siqiang Zhao\(^{1,*}\), Fengxiang Zhang\(^{1}\)

1. [Department, institution, city, country — to be completed]

\* Corresponding author: [name, postal address, e-mail — to be completed]

### Abstract (replace placeholders after the evidence gate)

Repeated local flexibility from distribution-connected batteries is limited by both future state-of-charge (SOC) headroom and time-varying feeder constraints. We formulate a benchmark contract that couples constant service power, two two-hour service windows, recovery windows, repeated calls, and a terminal SOC requirement. An unbalanced OpenDSS feeder generates time-varying AC-tested charging and export bounds, and an offline chronological linear program schedules recovery across the two calls. The hindsight full-horizon benchmark is compared with a fixed-recovery policy, a myopic recovery policy, and a copper-plate energy-only counterfactual using public residential load/photovoltaic profiles, two single-phase locations on the IEEE 13-node feeder, and the 2012--2013 external year. Under the frozen protocol, the feasible service-power estimate is [X] kW for the full-horizon benchmark, compared with [Y] kW for [named baseline], with a paired difference of [D] kW (descriptive date-cluster bootstrap CI [L, U]). The AC replay yields [replay result] and shows [network-versus-energy result] under [validation design]. These results delimit when recovery headroom and feeder limits change an offline repeated-flexibility offer, while also defining the limits imposed by the feeder model, active-power battery surrogate, and absence of field measurements.

**Abstract completion rule:** every number and adjective such as “external” must be traceable to the frozen external-year result directory and the final statistics file. If the B1 versus B3 comparison is not directionally consistent at both placements, describe the work as an auditable benchmark and do not present a general policy advantage.

### Highlights (each line must be checked against the final result and kept within the journal character limit)

- AC-tested recovery makes repeated BESS service a DSO screening decision.
- Network limits reduce safe offers below the copper-plate bound.
- Sequence-aware recovery preserves headroom for future calls.
- A strict external-date audit quantifies model-based delivery and network optimism.

Delete or rewrite a highlight that is not supported by the independent-year table. Do not use “first”, “guaranteed”, “real-time”, or “field validated”.

### Keywords

Battery energy storage; distribution flexibility; repeated service; recovery scheduling; unbalanced AC power flow; OpenDSS; delivery feasibility; smart grids.

## 1. Introduction

Distribution-connected batteries are increasingly considered for local flexibility, congestion relief, voltage support, and demand response. A battery that responds to one call, however, is not automatically able to respond to a later call: service energy must be recovered, the recovery action consumes network headroom, and the next call may occur at a different electrical state. This creates an applied energy-system screening question for a distribution system operator (DSO): how much repeated flexibility can be offered while satisfying explicit AC and SOC tests over a complete service sequence?

Existing flexibility formulations provide useful abstractions for aggregate storage and recovery requirements (e.g., Evans et al., 2022), and recent work has connected dynamic feasible regions and distribution-network operation (e.g., Xiao et al., 2025; Cheng et al., 2026). Studies of flexibility offers also show that offer size and recovery assumptions affect operating decisions (e.g., Wanapinit et al., 2022). Two practical issues remain coupled insufficiently for the decision considered here. First, a repeated offer is often represented by an SOC-only or copper-plate model, although the charging and export actions used to restore the battery can be more restrictive than the service action itself. Second, a single-call AC feasibility check does not reveal whether a policy has preserved the headroom required for a later call. A policy may therefore appear feasible at the first call while being unable to support the complete contract.

This paper studies an **offline network-aware repeated-flexibility benchmark** rather than a new battery chemistry or a generic optimizer. The contract contains a constant service power, two service windows, declared recovery windows, a repeated-call sequence, and a terminal SOC requirement. For every profile and battery location, an OpenDSS audit supplies time-varying charging and export limits. A hindsight full-horizon linear program then chooses recovery actions using the complete realized profile. The result is compared with a fixed recovery rule, a short-sighted recovery policy, and an energy-only upper bound under the same profiles, feeder, SOC limits, and terminal condition.

The paper makes four bounded contributions:

1. It defines an auditable contract object that exposes service duration, recovery windows, repeated calls, and terminal SOC to a DSO screening decision.
2. It couples an unbalanced AC feasibility audit to chronological recovery scheduling, retaining voltage, line, transformer, command/readback, and convergence status records rather than silently dropping infeasible schedules.
3. It separates the effects of network headroom, fixed recovery, short-sighted recovery, and full-horizon recovery using four policies with identical data and boundary conditions.
4. It reports a strict chronological development-to-external-year evaluation on 219 non-contiguous retained dates, public profiles, and two IEEE 13-node feeder locations, with descriptive date-cluster bootstrap intervals and complete AC replay records.

The claims are deliberately narrower than an online recovery policy or a general recovery guarantee. The study does not establish field performance, market-wide optimality, or feeder transferability beyond the quantitative cases evaluated. The remainder of the paper describes the data and contract, the AC audit and dispatch model, the statistical protocol, the results, and the operational limits of the findings.

## 2. Materials and methods

### 2.1 Study design and information boundary

The development data are the earliest chronological portion of the profile bank. They are used to check units, construct the frozen customer-group mapping, select normalization constants, and test the implementation. The 2012--2013 Ausgrid source is evaluated under the frozen protocol after development; its 365 raw dates yield 219 retained complete dates in three non-contiguous blocks (2012-07-01--2012-10-11, 2013-01-01--2013-01-25, and 2013-04-01--2013-06-30) after fixed-denominator customer-level completeness checks. It is therefore a temporal external evaluation, not an untouched continuous-year holdout. The group mapping, development-year scales, feeder locations, service/recovery windows, SOC and efficiency parameters, AC pass criteria, power grid, random seed, and output schema are frozen before the external-year result is read. No external-year outcome is used to tune a threshold, re-cluster customers, or change a policy.

The unit of the primary paired analysis is date × frozen customer group × battery location. All dates, including AC failures, remain in the audit table. The descriptive confidence interval uses 5,000 date-cluster bootstrap replicates with seed 20261003; a date × group bootstrap is a sensitivity analysis. The analysis reports the conditional primary endpoint only for profiles that pass the baseline AC-feasibility gate, and reports the number and recorded statuses of profiles excluded by that gate.

### 2.2 Public profiles and preprocessing

The profile bank contains [number of] [load/photovoltaic] series at 30-min resolution from [public source and citation]. The external 2012--2013 source contains 365 raw dates, 219 retained complete dates, 10 frozen groups, and 48 half-hour samples per retained date after documented parsing and unit conversion. The source file hash is recorded in `data/processed/ausgrid_external_2012_2013_strict.json`; the final paper will report the exact hash, retrieval metadata, and license/attribution statement.

Profile preparation consists of [documented conversion steps]. Missing or invalid records are handled by [rule]; no external-year record is imputed using future information. The chronological split is [development split details from the final manifest]. All profile values passed to the feeder model are reported in kW with their sign convention. The preprocessing script and manifest are versioned with the code release.

### 2.3 Feeder and battery placement

The quantitative case is the unbalanced IEEE 13-node OpenDSS feeder. The photovoltaic surrogate is [300] kW at bus 675.1. The battery is placed as a single-phase device at buses [611.3] and [634.1], with the phase and connection specified explicitly in the configuration. The AC audit uses voltage limits of [0.95--1.05] pu and line and transformer loading limits of [1.0] per unit. The adapter creates an isolated OpenDSS context for each snapshot, disables unintended controls for the snapshot solve, initializes the circuit, solves without control actions, and reads back phase voltages, line currents, and transformer winding currents.

The active-power battery command uses the sign convention (p_t>0) for export/service and (c_t>0) for charging, with (Q=0) in the development protocol. Each candidate setpoint is passed through the same command/readback and AC checks; a candidate is feasible only when convergence, command/readback, voltage, line, and transformer checks all pass. The audit retains the limiting margin and AC status for each attempted command. The IEEE 123-node file is retained as an adapter diagnostic only because its strict baseline gate currently fails under the same limits; it is not used to support quantitative transfer claims.

### 2.4 Repeated-flexibility contract

For each profile and placement, the contract is

\[
c=(P,T_s,T_r,M,s_{\rm end}),
\]

where (P) is the constant service/export power, (T_s) is the service duration, (T_r) denotes the declared recovery windows, (M) is the number of calls, and (s_{\rm end}) is the terminal SOC requirement. The frozen protocol uses 48 half-hour intervals, two two-hour service windows ([8,12)) and ([24,28)), recovery windows ([12,24)) and ([28,48)), initial and terminal SOC 0.80, SOC bounds [0.20, 1.00], usable energy [2,000] kWh, and charge/discharge efficiencies [0.95, 0.95]. The candidate service-power grid spans 0--300 kW and is refined by a conservative prefix search to a resolution below 0.1 kW for every interval bound.

The fixed-recovery policy uses the frozen recovery ratio

\[
r=\frac{8}{32\,\eta_c\eta_d}=0.2770083,
\]

only in the declared recovery windows; it does not silently pre-charge outside those windows. This rule is a transparent negative control, not an asserted optimum. The terminal SOC condition gives every policy a declared opportunity to restore the battery after the second call.

### 2.5 AC transition bounds and chronological dispatch

For each profile interval, the audit searches the candidate active-power commands (p\in[0,300]) kW for export and charging, checks monotonicity, and refines the largest feasible prefix value to below 0.1 kW. The resulting values are conservative checked-grid bounds, not a proof that every intermediate command is feasible; command-grid resolution is therefore included as a sensitivity. Each selected schedule is replayed through OpenDSS; the reduced dispatch model is never accepted without the replay.

For the network-aware policy, the linear program maximizes the constant (P):

\[
\max P,
\]

subject to

\[
e_{t+1}=e_t+\eta_c c_t\Delta t-\frac{d_t\Delta t}{\eta_d},
\]

\[
0\leq c_t\leq\bar c_t^{\rm AC},\qquad
0\leq d_t\leq\bar p_t^{\rm AC},\qquad
d_t=P\;\text{in service windows},
\]

\[
E s_{\min}\leq e_t\leq E s_{\max},\qquad e_0=E s_0,\qquad e_T=E s_{\rm end}.
\]

Charging is zero in service windows and no additional discharge is invented outside a service window. The solver returns the full charge, discharge, energy, SOC, and PCC-import trajectories. A schedule is physically deliverable only if its AC replay passes at every interval.

The four benchmark policies are:

| Label | Policy | Purpose | Physical interpretation |
|---|---|---|---|
| B1 | `network_lp` | Hindsight full-horizon AC-bounded benchmark | Optimizes (P) and recovery against the complete realized time-varying AC bounds and exact terminal SOC. |
| B2 | `fixed_recovery` | Fixed-rule negative control | Uses the same ratio in the declared recovery windows; it cannot adapt the recovery profile to headroom. |
| B3 | `myopic_recovery` | Short-horizon decision baseline | Charges toward the next contiguous service block and only considers the terminal target once no future service block remains. |
| B4 | `energy_only` | Copper-plate counterfactual upper bound | Uses the maxima of the audited charge/export bounds, then undergoes AC replay; failures are reported and this schedule is not called deliverable. |

The labels and ordering in the final tables must remain unchanged. B1 is an offline hindsight benchmark: it receives the complete realized profile and all future AC bounds before selecting the recovery trajectory. It is not a forecast, rolling-horizon, robust, or chance-constrained controller. The primary comparison is B1--B3 on baseline-AC-feasible profiles; B4 is shown as an energy-only upper bound and its AC replay outcome is a diagnostic of network optimism.

### 2.6 Outcomes and statistical analysis

The primary outcome is feasible constant service power (kW), conditional on baseline AC feasibility, by placement and policy in the 219 retained external dates. We report means, medians, and an explicitly labelled empirical lower-tail service-power percentile where useful, paired B1-minus-baseline effects, and descriptive date-cluster bootstrap confidence intervals. A percentile describes the evaluated profile sample; it is not a probabilistic guarantee and is not described as “95% reliability.”

Secondary outcomes are delivered service MWh, recovery MWh, terminal SOC, AC replay success, shortfall kW/MWh, and counts of voltage, line, transformer, command/readback, convergence, and SOC failures. For each policy and placement we report the baseline-gate denominator, all attempted schedules, and the conditional denominator used for the primary endpoint.

No cost or market-clearing objective is fitted in this benchmark. The results are reported as a technical service-power and AC-replay comparison. Any DSO implication is phrased as an offline screening use case, not as a validated economic recommendation.

### 2.7 Reproducibility and quality control

The code release records the OpenDSS adapter version, source hashes, configuration, random seed, protocol version, and result-directory manifest. Unit tests cover profile-bank chronology, dispatch constraints, adapter isolation, transformer-current parsing, and AC-audit status handling. The final run is executed in a new result directory; later changes cannot overwrite it. Figures are generated from the result CSV/JSON files rather than hand-entered values. A final audit checks that every number in the abstract, highlights, main tables, graphical abstract, and cover letter appears in the frozen result files.

## 3. Results (to be written only after the external-year run)

### 3.1 Data and feasibility gate

Report [N profiles attempted], [N baseline-feasible], and [baseline-feasibility rate] for each placement, with a compact baseline-gate status table. State whether the primary endpoint is conditional and why. Do not silently exclude a placement or date.

### 3.2 Main repeated-service frontier

**Table 1.** Mean feasible service power, selected percentile safe offer, paired B1-minus-B2/B3 effect, and date-cluster 95% CI for both placements. Include the number of profile units and the baseline-gate denominator.

**Figure 1.** External-year frontier by placement and policy, with date-cluster intervals and the B4 energy-only upper bound visually separated from physically deliverable policies.

Narrative template: “At [placement], B1 delivered [X] kW (95% CI [L,U]) on [N] baseline-feasible units. The paired difference from B3 was [D] kW (95% CI [L,U], [direction/interpretation]). At [second placement], the corresponding values were [values]. The B4 schedule exceeded an AC limit on [rate] of attempted replays and is therefore reported as an upper bound.”

### 3.3 Recovery trajectory and active constraints

**Figure 2.** A representative, pre-specified external-year date × group × placement trace showing service power, charge power, SOC, minimum phase voltage, maximum line loading, and transformer loading. Shade service and recovery windows. The trace is illustrative; the aggregate table remains primary.

Narrative template: “The full-horizon benchmark used [pattern] recovery before the second call. The replay status and tightest recorded margin were [result]. The trace is consistent/inconsistent with the aggregate frontier because [evidence].”

### 3.4 AC replay and robustness

**Figure 3.** AC replay outcomes by policy and placement. Include sensitivity to [date × group bootstrap], [power-grid resolution], [terminal-SOC convention if pre-specified], and [baseline-feasibility conditioning].

Report whether the B1-versus-B3 direction remains after each sensitivity. If not, narrow the conclusion to the primary protocol and state the instability.

### 3.5 Offline screening interpretation

**Figure 4 / Table 2.** Show the service-power versus AC-replay comparison for the two placements and the four benchmark policies. Describe how a DSO could use the result to screen a repeated offer, without assigning a market price or claiming an economic optimum.

## 4. Discussion

The discussion should answer three applied questions. First, how much of the energy-only offer is removed by feeder headroom at each electrical location? Second, when does the hindsight full-horizon benchmark change the service-power result relative to the fixed and myopic policies? Third, how could a DSO or aggregator use this offline comparison to screen a repeated offer before adding a forecast or online control layer?

Interpret any B1 improvement as a consequence of the specified future-call and terminal-SOC constraints under the tested feeder and data, not as a universal guarantee. Explain differences between locations using the recorded voltage, line, transformer, and SOC margins. Distinguish development diagnostics from the 2012--2013 external-year estimate. Compare the result with the cited storage-recovery and dynamic-feasible-region literature without claiming priority or generality beyond the evidence.

## 5. Limitations

1. The quantitative network experiment uses one IEEE 13-node feeder and two single-phase locations. The IEEE 123-node case is an adapter diagnostic whose strict baseline gate fails; no transfer claim is made.
2. The battery is represented by an active-power surrogate with fixed efficiencies and (Q=0) in this development protocol. Detailed inverter apparent-power, reactive-power, thermal, degradation, and state-estimation models are outside the current evidence.
3. OpenDSS snapshot bounds and replay demonstrate model-based feasibility, not field telemetry or protection-system validation. Regulator/control behavior and parameter uncertainty require a separate study.
4. The public profile year and frozen customer grouping do not represent every climate, tariff, feeder topology, or market rule. The external-year design reduces temporal leakage but does not establish population-wide generalization.
5. The hindsight full-horizon benchmark uses realized future profiles and therefore overstates what an online controller could know. It is an offline upper-envelope comparison, not a deployable forecast policy.
6. The reported confidence intervals describe variation over the retained profile dates; they do not establish a delivery guarantee for unobserved events.

## 6. Conclusions (replace after evidence review)

This study evaluated repeated distribution-flexibility contracts by coupling AC-audited feeder headroom with chronological BESS recovery. Under the frozen [feeder/data] protocol, the network-aware policy produced [main quantitative finding] relative to [baseline], while the energy-only counterfactual produced [network optimism/failure finding]. The result indicates that [operational implication] for offline DSO screening of repeated offers under the tested feeder and profile design. These conclusions are limited to the modeled feeder, locations, active-power battery surrogate, and external-year evaluation; broader claims require additional feeders, reactive-power/inverter models, and field or multi-year validation.

## Declarations

### CRediT authorship contribution statement

**Siqiang Zhao:** Conceptualization, Methodology, Software, Validation, Formal analysis, Investigation, Data curation, Visualization, Writing — original draft. **Fengxiang Zhang:** Supervision, Writing — review & editing. The author order and contribution statement were confirmed by both authors.

### Funding

No dedicated external funding was received for this work. [Confirm wording against the authors' institutional requirements before submission.]

### Declaration of competing interest

The authors declare that they have no known competing financial interests or personal relationships that could have appeared to influence the work reported in this paper.

### Acknowledgements

No additional acknowledgements are requested. [Add institutional or data acknowledgements only if required by a data licence or funder.]

### Data availability

The public profile source, preprocessing metadata, source hashes, frozen group mapping, and derived external-year manifest are provided in the code repository. The development repository is [https://github.com/Zhaosiqiang/RecoveryFlex-AE]. A persistent archive DOI will be inserted here after the code, protocol, figures, and manuscript are frozen: [ZENODO DOI TO BE CREATED]. The paper will state the source licence and attribution exactly as required by the dataset provider. No private participant-level data are claimed.

### Code availability

The analysis code is released under the MIT License at [repository URL], with the exact release tag/commit [TAG/COMMIT TO BE CREATED]. The release will include the OpenDSS adapter, dispatch planner, profile preprocessing, experiment commands, tests, figure scripts, and result-manifest hashes. The repository currently contains development evidence and must not be cited as the final archival release until the independent-year audit is complete.

### Use of AI-assisted tools

OpenAI Codex/ChatGPT and Manus were used as editorial and programming assistants for drafting, code organization, figure-generation support, and internal consistency checks. The authors reviewed and verified all scientific claims, methods, data handling, figures, and final text and remain fully responsible for the content. No AI tool is an author and no confidential or restricted data were provided to an AI tool. The wording must be checked against the current Applied Energy/Elsevier AI-disclosure policy immediately before submission.

## Required final files before any submission decision

- Final manuscript PDF and editable source generated from the same frozen commit.
- Main figures, graphical abstract, and Highlights checked against the latest Applied Energy author guide.
- External-year result directory, statistics, raw audit CSV, and SHA-256 manifest retained read-only.
- Final bibliography with verified DOI metadata; no unsupported citation or novelty claim.
- Completed affiliation and corresponding-author email.
- Editorial, methods, and adversarial review logs with no unresolved desk-reject or transfer concern.
- A separate decision record stating whether the evidence gate permits submission. This skeleton itself is not permission to submit.

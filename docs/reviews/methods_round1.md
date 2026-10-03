# Corrected-v1 methods and statistics review (round 1)

**Reviewer:** internal methods/statistics audit  
**Date:** 2026-10-03  
**Scope:** `src/recoveryflex/ac_snapshot.py`, `src/recoveryflex/profile_bank.py`, `scripts/run_corrected_experiment.py`, `scripts/build_corrected_statistics.py`, corrected-v1 result files, and `paper/main.tex`.

## Decision

**Block submission and any public release until the items marked BLOCKER are repaired and the complete experiment is rerun.** The corrected-v1 outputs cannot yet support the headline AC-constrained sequence claim. The most serious implementation defect is that transformer loading is effectively disabled by a unit error. There are also unresolved command-versus-realized-energy coupling, an uncommitted parameter change that invalidates the stored outputs, and a mismatch between the number/type of profiles described in the manuscript and the profiles actually evaluated.

## What passed this audit

- The old V0 outputs remain quarantined and are not used here.
- `ProfileBank` computes normalization scales from train dates only (`src/recoveryflex/profile_bank.py:6-17`), and the Ausgrid/OPSD builders create disjoint date labels before experiment outcomes are computed.
- Candidate offer selection calls only train dates and calibration factor selection calls only calibration dates (`scripts/run_corrected_experiment.py:177-214`). No direct test-date call is used to choose the offer.
- The OpenDSS context is isolated with `NewContext()`, battery command signs are explicit, and terminal-power readback is recorded (`src/recoveryflex/ac_snapshot.py:91-96`, `237-261`). The direct readback file shows command changes at -70, 0, 70, and 140 kW.
- Event-level failures are retained as `ok=0` rows. They are not silently dropped from the reported rates.
- The full-rearm test is a useful negative-control idea: with an exactly repeated event and an explicitly restored SOC, any contraction should be zero up to grid resolution.

These passing points are process checks only; they do not validate the current numerical claims.

## Blockers

### B1 — Transformer loading ratio has a factor-of-1000 error (fatal AC validity)

At `src/recoveryflex/ac_snapshot.py:230-234`, the code obtains `CktElement.Powers()` and computes `hypot(P,Q) / 1000`. OpenDSS returns terminal powers in kW and kVAr, so this division converts valid kW to MW even though `Transformers.kVA()` is in kVA. The resulting ratios are about 0.001 in the stored audit and cannot reject an overloaded transformer. The code also sums both transformer terminals, which double-counts the apparent power and allows cancellation/terminal ambiguity.

**Required repair:** compute a documented terminal loading metric in consistent units. For each transformer, use the maximum (or otherwise explicitly defined) apparent power of the loaded winding, with `Powers()` in kW/kVAr and `kVA()` in kVA. If a three-phase winding is represented by multiple conductors, aggregate the appropriate phases once; do not sum primary and secondary terminals. Add a unit test that commands a known load or battery change and verifies a meaningful transformer ratio, then rerun offer selection and all results. Include transformer name, ratio, and limiting component in event-level output.

### B2 — SOC is updated from the command, not the measured AC terminal power (major physical coupling)

`_event_ac()` returns only feasibility and extrema (`scripts/run_corrected_experiment.py:88-125`). `evaluate_event()` then updates SOC from the requested `p_kw` (`147-152`), even though the adapter has a potentially different `battery_realized_kw` after the nonlinear solve (`ac_snapshot.py:237-260`). A readback tolerance of 1% therefore permits an unreported energy discrepancy, and the claimed AC-audited recovery contract is not actually coupled to the measured terminal trajectory.

**Required repair:** return every interval's realized battery P (and its acceptance status) from `_event_ac()` and integrate the measured value with the declared efficiency convention. Store command, realized P, error, SOC increment, interval index, and feasibility reason. Alternatively, explicitly define the command as the contractual meter value and publish a worst-case error bound plus an energy sensitivity; the manuscript must then stop claiming SOC is measured from terminal readback.

The current working-tree patch now updates SOC from interval-average readback, but it exposes a second failure: the full-rearm sequence capacity becomes 0 kW for several held-out dates in `results/corrected_v2_readback/sequence_capacity.csv`. The 0-kW rows arise because the fixed re-arm ratio leaves a readback-induced SOC drift of roughly (10^{-6})--(10^{-5}), while the sequence loop requires `soc >= SOC_INITIAL - 1e-8`. This is a numerical/readback tolerance artifact, not a demonstrated zero service capability. It must be resolved by a measured-energy-consistent re-arm command or a predeclared tolerance derived from the readback error, with the resulting drift reported.

### B3 — Stored results are stale relative to the current protocol/code (fatal provenance)

The working tree currently contains uncommitted changes to both the AC adapter and experiment runner (measured-power SOC updates and corrected transformer ratios), while `results/corrected_v1/*`, figures, and the PDF still contain outputs from the pre-repair implementation. During this review a transient `PV_RATED_KW=500` change also produced the untracked `results/pv500_smoke/` directory while the stored protocol/results still reported 300 kW. The transient value has since been reverted, but it demonstrates that the package has mixed-generation artifacts. A smoke test failed during that mixed state before being relaxed; the current tests do not establish that the full stored outputs are regenerated.

**Required repair:** freeze the parameter set in one versioned protocol/configuration, remove or quarantine all mixed-generation outputs, rerun the full pipeline from clean outputs after the adapter and runner repairs, regenerate figures/statistics/manuscript, and record the commit hash, source hashes, environment, and command. No result or figure from the mixed state may remain in the submission package.

### B4 — Profile unit of analysis is misdescribed and only one of ten groups is used (major generalization error)

The bank contains ten seeded group-mean trajectories, but `GROUP=0` is hard-coded (`scripts/run_corrected_experiment.py:35-43`, `73-85`). The experiment therefore evaluates one mean group (roughly 30 customers) for each of 214/71/80 dates. The manuscript calls these “customer-days” and presents ten groups as if they were evaluated. The two event starts are repeated measurements on the same date, not 160 independent held-out customer-day observations.

**Required repair:** either evaluate all groups and use a two-level cluster analysis (date as the primary independent unit, group nested within date), or state precisely that this is a single fixed group-day stress trajectory and add a prespecified group-sensitivity result. Rewrite “customer-days” to “group-days” wherever only group 0 is used. Report the number of independent dates, group trajectories, and repeated starts in every rate/CI statement.

### B5 — Offer selection threshold and uncertainty unit are inconsistent (major statistical design issue)

Offer selection averages two event starts per date (`_event_success_fraction`, lines 169-174) and applies a 95% event-level threshold. The uncertainty summary then averages the same two rows within date and bootstraps dates (`build_corrected_statistics.py:13-16`). In the full output, the 140-kW training rate is 420/428 events (98.13%) but only 206/214 dates have both starts accepted (96.26%). The protocol says day is the resampling unit without stating whether selection is event-level or day-level.

**Required repair:** predeclare one estimand and use it consistently. For a service product promised for both starts, select on the date-level success rule (for example, both starts pass, or a declared per-day fraction), then report date-clustered bootstrap intervals. If event-level selection is retained, call it event-level and explain the repeated-measure dependence; do not present the resulting rate as an independent-day guarantee. Freeze the rule before rerunning.

### B6 — Sequence contraction is imposed by an arbitrary fixed recovery ratio and is not an independent physical result (major scientific validity/scope)

The reserve-limited result uses `RECOVERY_RATIO=0.30` and an ideal SOC recursion. The sequence capacity loop reuses one identical AC event per day and only changes the scalar SOC recursion (`scripts/run_corrected_experiment.py:256-299`). The reported 140 -> 90 -> 70 -> 50 -> 50 -> 40 kW sequence is therefore largely an analytic consequence of the chosen ratio, energy capacity, reserve, and 10-kW grid. No recovery policy is optimized, no feeder-limited recovery headroom is inferred, and no uncertainty/temperature/degradation state is present.

**Required repair:** add a protocol-fixed sensitivity over recovery ratio, energy capacity/reserve, efficiency, and command-grid resolution, with an analytic SOC reference. More importantly, derive the recovery limit from a declared operational constraint (or clearly label the result as a contract-design illustration). Compare energy-only and AC-limited recovery and show the incremental contribution of the feeder. Narrow the Applied Energy claim if the result remains an illustrative IEEE feeder demonstration.

### B7 — Sequence results use only service start 8 although the offer audit uses starts 8 and 32 (major design inconsistency)

`SERVICE_STARTS=(8,32)` is used for train/calibration/test offer rates, but `control_start=SERVICE_STARTS[0]` is used for every repeated-sequence capacity (`scripts/run_corrected_experiment.py:227-274`). The capacity distribution therefore omits the second operating window and cannot be read as the sequence capability of the evaluated service product.

**Required repair:** predeclare whether a sequence contract covers one start or both. If both, compute repeated capacities for both starts (or a worst-case joint contract) and cluster/report by date and start. If one start is intended, remove the second start from the product claim and explain why.

### B8 — AC failure provenance is too coarse for an auditable contract (major reproducibility)

`_event_ac()` retains at most two generic strings such as “service AC infeasible” or “recovery AC infeasible” (`scripts/run_corrected_experiment.py:101-124`). The row file does not identify interval, limiting bus voltage, limiting line, transformer, readback error, or convergence status. A reader cannot independently distinguish voltage, line, transformer, and command failures from the published table or figure.

**Required repair:** emit a tidy interval audit with `date`, `start`, `phase`, `interval`, `command`, `realized_kw`, `vmin`, `vmax`, limiting bus, max line ratio, limiting line, max transformer ratio, limiting transformer, convergence, and failure reason. Build event-level summaries from this table; retain failed intervals rather than only the first two strings.

### B9 — Full-rearm negative control is too narrow and its C2 statistic can be undefined/misleading (major inference)

The control repeats one test-day event twice (`scripts/run_corrected_experiment.py:227-240`) and computes a ratio using `max(int(control_single.ok),1)`. If the first event fails, the denominator is forced to one and the quantity is no longer a contraction ratio. Two repeats on one date do not test invariance across the six-event sequence or across the two service starts.

**Required repair:** define `C_M` from a capacity computed for each M and each prescribed start, with a denominator that is explicitly handled when the single-event capacity is zero. Report the full-rearm invariance across all held-out days/starts and all M, including an exact equality check at the 10-kW grid resolution.

### B10 — Transformer/control initialization and model claims are not fully reproducible (moderate-to-major AC issue)

`ACSnapshotFeeder._compile()` solves once at line 127-129 and only then issues `set controlmode=off`. Regulator/capacitor controls may therefore act before they are frozen. The protocol says controls are disabled and initial settings are used, which is not what the call order guarantees.

**Required repair:** set control mode before the first solve (or explicitly document and record the resulting tap/capacitor states). Add the feeder control state and OpenDSS version to the manifest. Verify that `reset()` reproduces the same baseline state byte-for-byte or within declared numerical tolerance.

## Additional concerns to address before a second review

1. **Grid resolution and boundary effects.** A 10-kW grid creates stepwise capacities and can make the exact C-ratio look more precise than it is. Report neighboring feasible/infeasible commands, a finer-grid sensitivity around the boundary, and confidence intervals for date-level capacity where appropriate.
2. **No confidence intervals for sequence capacities.** The summary gives min/median/max only. Add bootstrap or paired date-level intervals for each M and the difference between full-rearm and reserve-limited modes; avoid treating repeated M rows as independent.
3. **Fixed group means and synthetic stress embedding.** The `clip(0.40+0.30·load_norm)` and `clip(0.10+0.60·pv_norm)` bridge is declared, but its constants are hand-selected and may be carrying the result. Keep it pre-registered and add a scale sensitivity that is not selected from test outcomes.
4. **Static snapshot limitation.** A static IEEE-13 feeder cannot support claims about dynamic operating envelopes, temporal feeder controls, or field feeder generalization. The title, abstract, and discussion should state that the profile-to-feeder mapping is synthetic and that only a public benchmark feeder was audited.
5. **Transformer results are absent from publication tables.** After B1, publish the limiting transformer and its ratio; otherwise “line and transformer limits” is not verifiable.
6. **Portable provenance.** Absolute paths appear in the profile manifest and summary. Use repository-relative paths plus SHA-256 hashes, record the exact Python/OpenDSS versions, and make the clean rerun command a tested script.
7. **Tests are insufficient for failure modes.** Add tests for transformer units, a line/voltage violation, negative charging readback, reset reproducibility, no-date leakage, test-date immutability during selection, and measured-P SOC integration. The current smoke test hard-codes a contraction expectation that disappeared after a parameter change.

## Minimum acceptance gate for round 2

I would re-review only after all of the following are present:

1. Correct transformer loading units/terminal aggregation and a passing unit test.
2. One frozen protocol/config commit; no mixed-parameter output; all results, figures, tables, and PDF regenerated from a clean run.
3. Interval-level AC/SOC audit using realized terminal P or a declared command-error bound.
4. Correct unit-of-analysis language and either all ten groups evaluated or a transparent single-group sensitivity.
5. Predeclared date-level/event-level selection rule aligned with the bootstrap estimand.
6. Sequence capacities for both service starts (or an explicit one-start product) plus recovery-ratio/energy/grid sensitivities and paired uncertainty intervals.
7. Machine-readable failure reasons and transformer/line limiting components.
8. Updated tests and a reproducible clean-run record.

Until then, corrected-v1 should remain an internal methods draft and should not be submitted or cited as evidence of the Applied Energy contribution.

# Methods review round 2 — v2 network-recovery experiment

**Decision: BLOCKED for an Applied Energy submission.**  The v2 code is a useful
development benchmark and its tests are reproducible, but the present evidence
does not support the words *risk-calibrated*, *95% reliable*, or *network-feasible
contract*.  The blockers below are independent of manuscript prose and must be
resolved in the protocol and result files before a new editorial review.

## 1. The old external result used an invalid baseline gate; the repair is not yet rerun

The archived v2 result was generated when `run_network_recovery_v2.py:55–76`
accepted a profile if each sign had *some* feasible grid point (`:59–64`,
`:83–88`), rather than requiring p=0.  Its 3,528/3,650 conditional denominator
therefore cannot be used in a manuscript.  OpenDSS feasibility can be
non-monotone in a battery command: a zero-command high-voltage point can be
relieved by charging, while another nonzero command remains feasible.  A
minimal abstract counterexample is the feasible grid `[False, True]` at
`p=[0,20]` for both signs; the old gate labels this profile baseline-feasible.

The current working tree now adds `zero_ok` and `baseline_export`/
`baseline_charge` checks (`run_network_recovery_v2.py:55–97`), which is the
right direction.  However, all full-year summary/statistics files reviewed
here predate that patch, and the gate is still inferred from the bound-search
routine rather than recorded as a separate p=0 audit table.

**Repair status:** the adapter-final rerun now includes
`baseline_zero_audit.csv` with one p=0 audit per date×group×placement and the
four failed units are retained.  The result directory and every statistical
table must continue to use this immutable gate.  Add a unit test with a
nonzero feasible command but infeasible p=0 before claiming the gate is
regression-proof.

## 2. The AC “bound” is still not certified as a continuous inner interval

The working-tree search now keeps only the largest *prefix* of the checked
grid (`run_network_recovery_v2.py:63–80`), which correctly avoids jumping over a
coarse-grid gap.  It still assumes that every command between adjacent grid
points is feasible and refines the final transition with only eight bisection
steps.  A sub-grid feasible island or a narrow violation between 20-kW grid
points is not ruled out.  Thus the returned scalar is a conservative grid
prefix, not a mathematically certified inner interval.

`dispatch.py` then treats each returned scalar as the upper edge of a complete
box (`_solve_lp`, especially `:176–200` and `:259–270`).  A linear programme may
choose a command below the scalar that lies in an untested infeasible island.
Replay is a useful check, but it does not repair the claim that the bound is
AC-feasible or quantify how often the interpolation assumption fails.  The
current output's replay rate is therefore an empirical property of these
schedules, not a proof of network-feasible availability over the contract set.

**Required repair:** either prove monotonicity for the exact OpenDSS model and
validate it on a dense independent command grid, or construct certified inner
intervals by bracketing every connected feasible component.  Record bound-level
violations separately from schedule replay and include a resolution sensitivity
(20, 5, 1, and 0.1 kW or an equivalent certified tolerance).

## 3. `network_lp` is a hindsight oracle, not a risk-calibrated policy

For each realized profile, the script first computes all 48 time-varying AC
limits (`run_network_recovery_v2.py:148–170`) and then gives the complete arrays
to a full-horizon LP (`:181–193`).  Thus the proposed method knows the future
load/PV trajectory and every future charge/export limit while selecting today’s
contract and recovery actions.  This is an offline upper envelope.  It is not a
forecast, rolling-horizon, robust, or chance-constrained controller.

The statistical script reports means and percentile bootstrap intervals
(`build_network_recovery_statistics.py:84–118`), and the protocol calls these
“uncertainty” intervals (`docs/experiment_protocol_v2.md:41–47`).  A 95% CI for
the *mean* is not a 95% delivery guarantee.  No epsilon is used in the planner,
no lower quantile of delivered power is selected, and no joint event such as
“all service intervals and terminal SOC pass with probability ≥ 1−epsilon” is
tested.  The manuscript skeleton still contains the unresolved instruction
“P05 or P95 [choose one]” (`docs/manuscript_skeleton_v2.md:134–146`).

**Required repair:** predeclare a risk estimand (for example, the lower 5th
percentile of per-profile delivered power, or a one-sided upper confidence bound
on the failure probability), choose the percentile convention before reading
the external year, and calibrate an offer on a separate calibration block.
Add a forecast/rolling-horizon or scenario policy if the result is to be called
a policy.  Keep the hindsight LP explicitly labelled as an offline upper bound
if no information model is added.  Do not call a bootstrap CI a guarantee.

## 4. The myopic comparator is deliberately weak and cannot isolate the claimed mechanism

The implementation explicitly says it is “short-sighted” (`dispatch.py:273–290`)
and the rollout only targets the next service block until no future block
remains (`:306–318`).  It has no receding-horizon optimization, no terminal
headroom reservation for a later call, and no alternative recovery timing.
Consequently, any `network_lp − myopic_recovery` gain can be caused by the
baseline's hand-written information restriction rather than by the proposed
network-aware formulation.

A minimal counterexample uses two one-interval calls, energy 100 kWh,
initial/terminal SOC 0.20, and no reserve.  Let the only useful charging
opportunity before the first call be 100 kW at `t=0`, with zero charge limit
between the calls and a 100 kW terminal recharge after the second call.  The
myopic rollout charges only enough for call 1 and then reaches zero, so it can
deliver `P=0` at call 2.  A full-horizon schedule charges twice the call energy
at `t=0`, delivers a positive `P` at both calls, and uses the post-call interval
to restore terminal SOC.  The difference is created by the comparator rule,
not AC physics.  The same failure mode is directly allowed by the comment in
`dispatch.py:306–318`.

**Required repair:** include a strong AC baseline with the same information
pattern (e.g., receding-horizon LP with a declared forecast window), a
full-horizon SOC-only LP, and an AC-only/static-recovery control.  Keep the
hand-written myopic policy as a sensitivity baseline and label it as such; do
not make it the main causal comparator.

## 5. The historical one-hour wording was inconsistent with the two-hour contract

The archived protocol described one-hour calls, although the half-hour windows
`(8,12)` and `(24,28)` contain four intervals each.  The current working tree
correctly says **2 h per call** (`run_network_recovery_v2.py:33–40`;
`docs/experiment_protocol_v2.md:11–20`).  The current fixed recovery windows
`(12,24)` and `(28,48)` are six hours and ten hours respectively (16 h total),
and the updated ratio uses 32 recovery intervals.  Any figure/table produced
from the archived 20-h protocol therefore has a different SOC requirement and
must not be mixed with the repaired 24-h result.

**Required repair:** freeze one convention and propagate it to the title,
abstract, equations, figures, captions, ratio derivation, and all scripts.  Add
an assertion that `sum(end-start)*dt_h` equals the stated service duration.

## 6. The placement set is not demonstrably predeclared

The quantitative experiment hard-codes only `611.3` and `634.1`
(`run_network_recovery_v2.py:31`, `:140–149`).  The redesign note acknowledges
that these are the two selected sites while IEEE-123 is diagnostic only
(`docs/reviews/redesign_decision.md:69–73`).  The prior adversarial audit found
that, with the same PV and limits, the selected `611.3` site had 154/160 passes
whereas several alternative sites had 160/160 (`docs/reviews/adversarial_round1.md:75–77`).
This shows that placement materially changes the apparent network effect and
that selecting two sites without a topology-based sampling rule can be
post-hoc.

**Required repair:** before using external-year outcomes, publish a placement
rule covering near-source, mid-feeder, and remote buses and at least two phase
assignments, or include all candidate placements and transparently report the
selection.  Treat 611.3/634.1 as a development subset unless a dated protocol
proves the choices preceded all placement results.

## 7. AC failure classes are discarded from the v2 result table

`ACSnapshotFeeder.solve` produces detailed `failure_reasons` and a limiting
component (`ac_snapshot.py:395–437`), but `_replay` returns only a boolean and
the list of audits (`run_network_recovery_v2.py:100–106`).  The row written at
`:202–227` keeps `replay_feasible`, `max_vmax`, `max_loading`, and the LP
message; it does not serialize any voltage, line, transformer, convergence, or
readback reason.  Consequently, the protocol's promised failure-class table
(`docs/experiment_protocol_v2.md:41–47`; skeleton `:138`) cannot be regenerated
from the full external result directory.  An energy-only failure rate of 100%
without its limiting components is a diagnostic, not a mechanistic network
result.

**Required repair:** write one auditable failure record per interval and
policy, including the first/maximum failure class, component, command,
voltage, line loading, transformer loading, and convergence/readback status.
Derive failure-rate figures only from that immutable table.

## 8. The archived external day was silently truncated to 20 h

The processed external profiles contain 48 half-hour intervals.  The archived
v2 experiment used `HORIZON_INTERVALS = 40` and discarded the final 4 h of every
profile (`run_network_recovery_v2.py` in the old result revision).  The current
working tree has changed this to 48 intervals and extends the final recovery
window to `(28,48)` (`run_network_recovery_v2.py:34–36`), which is the correct
repair direction.  The archived 20-h summaries are audit-only; the
adapter-final strict_v3 result is the first 48-interval rerun.  Its manifest,
service/recovery durations, and terminal SOC rule must accompany every figure.
Do not reuse any 20-h means or figures as full-day procurement risk.

## 9. The adapter-final strict run does not meet the predeclared effect gate

The adapter-final 48-interval run on the strict 2012–2013 bank contains 219 retained
dates (2,188 baseline-feasible date×group units per placement).  Its conditional
date-cluster results are:

| placement | network mean (kW) | fixed mean (kW) | myopic mean (kW) | network − myopic (kW, 95% CI) |
|---|---:|---:|---:|---:|
| 611.3 | 128.526 | 128.368 | 128.526 | 0.000 [0.000, 0.000] |
| 634.1 | 138.511 | 138.187 | 136.078 | 2.433 [1.682, 3.293] |

Network replay is 0.99954 at 611.3 and 1.000 at 634.1 after the baseline
gate; the explicit `baseline_zero_audit.csv` records 2,188/2,190 feasible units
at each placement and identifies the four zero-command failures.  The
predeclared hard gate in
`docs/reviews/redesign_decision.md:87`—a directionally consistent, meaningful
B4-vs-B3 improvement at both placements—is not met.  The apparent effect is
zero at one placement and small at the other.  It is not defensible to select a
placement or redefine the primary comparator after seeing this result.

These numbers are descriptive audit evidence only until failure records and the
risk estimand are repaired; they are included to prevent a later manuscript
from reporting the energy-only upper-bound gap as the proposed method's effect.

## 10. Scope and submission consequence

The protocol itself says IEEE-123 is an adapter diagnostic, not a quantitative
transfer test (`docs/experiment_protocol_v2.md:31–35`).  Combined with the
ideal constant-P battery surrogate, one static feeder, the stale external
output, the hindsight LP, and the unresolved risk estimand, the current output
is an auditable IEEE-13 benchmark.  It is not yet an Applied Energy
contribution with a calibrated procurement-risk decision.  Do not write an
acceptance-ready manuscript or submit until findings 1–8 are closed and a
fresh editorial review verifies every number against the repaired frozen result
directory.

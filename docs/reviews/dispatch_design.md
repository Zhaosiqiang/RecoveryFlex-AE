# Chronological dispatch core design review

**Status:** design and unit-test specification only; no experiment outputs or manuscript claims are attached.

## Purpose

The new dispatch core separates a service contract from the feeder replay. The feeder adapter must first convert each half-hour operating point into battery-side limits:

- `charge_limit_kw[t]`: maximum feasible charging power at interval `t`;
- `export_limit_kw[t]`: maximum feasible battery export at interval `t`;
- `load_kw[t]`: net native load seen at the point of common coupling, using positive import convention.

The planner then asks a DSO question: what is the largest constant export `P` that can be promised in all prescribed service windows while a chronological battery state recovers to its terminal target? This keeps time-varying AC charging opportunity in the decision. The module does not run OpenDSS and does not claim that an SOC recursion is itself novel.

The formulation is consistent with the recovery-guarantee idea in Evans, Tindemans and Angeli, *IEEE Transactions on Smart Grid* 13(5), 3519–3531 (2022), DOI [10.1109/TSG.2022.3173900](https://doi.org/10.1109/TSG.2022.3173900), while adding time-indexed network-side charge/export limits for a downstream operational counterfactual. The implementation uses SciPy HiGHS linear programming; its contract is documented in the [SciPy `linprog` reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html).

## Public interface

`src/recoveryflex/dispatch.py` exposes:

```python
from recoveryflex.dispatch import DispatchInputError, DispatchResult, plan_service

result = plan_service(
    charge_limit_kw, export_limit_kw, load_kw,
    service_windows=[(4, 8), (20, 24)],  # half-open indices
    energy_kwh=500.0,
    initial_soc=0.80,
    terminal_soc_target=0.80,
    soc_min=0.20,
    soc_max=1.00,
    eta_charge=0.95,
    eta_discharge=0.95,
    dt_h=0.5,
    peak_import_cap=None,
    mode="network_lp",
)
```

A service window `(start, end)` covers `start <= t < end`; windows must be within the horizon and cannot overlap. During a service interval, the battery exports exactly `P` and does not charge. During other intervals, the planner may charge and cannot invent additional discharge. This convention measures recovery opportunity rather than arbitrage value.

`DispatchResult` records the maximum `service_kw`, charging and discharge trajectories, chronological `energy_kwh` and `soc`, PCC imports, solver status, and a diagnostic message. An infeasible problem returns `feasible=False` with NaN state arrays; callers must not interpret its zero `service_kw` as a feasible zero-power contract.

## Network-aware LP

The optimization variable is

\[
x=(P,c_0,\ldots,c_{T-1},e_0,\ldots,e_T),
\]

where `c_t` is charging power and `e_t` is stored energy. The LP maximizes `P` subject to:

\[
 e_{t+1}=e_t+\eta_c\,\Delta t\,c_t
                  -\frac{\Delta t}{\eta_d}m_tP,
\]

where `m_t=1` inside a service window and `m_t=0` otherwise. It imposes

\[
0\le c_t\le \bar c_t,
\quad 0\le P\le\bar p_t\quad (m_t=1),
\quad E s_{min}\le e_t\le E s_{max},
\]

and `e_0=E s_0`. The terminal requirement is either `e_T >= E s_target` (`terminal_mode="at_least"`) or `e_T = E s_target` (`"exact"`). If supplied, a PCC cap adds

\[
load_t+c_t-m_tP\le \bar g_t.
\]

This is a continuous LP. It is intentionally transparent: the shadow price or binding row can later be used to label whether a contract is limited by an AC charge opportunity, export headroom, PCC cap, or stored energy.

## Baselines

`fixed_recovery` is a policy baseline. It requires either a full `fixed_recovery_kw` profile or a non-negative `fixed_recovery_ratio`, which enforces `c_t = ratio * P` in every recovery interval. The profile must be zero in service windows and cannot exceed the supplied charging limit. It is useful for testing whether a fixed recovery rule wastes a time-varying charging opportunity.

`myopic_recovery` is a deliberately declared rule baseline, not an optimizer. For a candidate `P`, it charges only toward the next contiguous service block; after the last service block it charges toward the terminal target. A bisection over `P` finds the largest feasible command under that rule. It does not reserve energy for a later target while a future service block still exists, which makes it a useful counterfactual for demonstrating the value of chronological look-ahead. Any paper use must report the rule explicitly rather than calling it an optimal policy.

`energy_only` is the network-free counterfactual. It calls the same chronological LP after replacing all time-varying charge limits and export limits with constant nominal limits (by default, the maxima of the supplied arrays) and dropping the PCC cap. The resulting frontier measures the haircut caused by time-varying network opportunities; it is not a feasible feeder offer.

## Required coupling to AC replay

The OpenDSS layer should produce one row per half-hour and record the command/readback check before calling this planner. A suitable row contains date, interval, placement, phase, load/PV state, battery command, realized battery kW, voltage minimum/maximum, line/transformer loading, and a boolean AC feasibility flag. The dispatch core should consume only rows that pass this audit. The state update uses the commanded contract power in the planning model; a replay audit should then recompute SOC using realized terminal power and report any deviation.

A value experiment should compare `network_lp`, `fixed_recovery`, `myopic_recovery`, and `energy_only` on the same held-out dates and service windows. The primary decomposition is

\[
P^{energy-only}-P^{network\ LP},
\qquad
P^{network\ LP}-P^{fixed/myopic},
\]

with day-cluster uncertainty and separate failure labels. This turns time-varying charging opportunity into a DSO decision metric without presenting the SOC arithmetic as the novelty.

## Unit-test contract

`tests/test_dispatch.py` covers:

1. multiple service windows and chronological recovery, including a network LP versus energy-only gap;
2. exact enforcement of a fixed recovery profile;
3. efficiency-aware fixed recovery ratio;
4. a PCC import cap binding both service and recovery periods;
5. the declared myopic baseline being weaker than look-ahead LP on a deliberately constructed horizon;
6. overlapping-window, missing-policy, and invalid-efficiency validation.

The tests use small synthetic trajectories only. They do not read the existing profile bank, OpenDSS feeder, or any previously generated result.

## Scope limits before publication

The planner does not model simultaneous charge and discharge, reactive power, ramping, degradation, temperature, reserve uncertainty, or discrete inverter modes. Those constraints must be added before claiming a full BESS market product. In particular, a network-aware result is only meaningful if `charge_limit_kw` and `export_limit_kw` come from an independently frozen AC audit and are not selected after observing the dispatch frontier.

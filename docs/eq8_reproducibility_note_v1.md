# Eq. (8) reproducibility note

This note is the implementation companion for Eq. (8) in `paper/main_v5.tex`.
It describes the scalar inventory certificate only.  The certificate does not
solve OpenDSS and does not certify joint nonlinear AC feasibility.

## Inputs and indexing

The horizon has intervals (t=0,ldots,T-1) and state nodes
(t=0,ldots,T).  Every service and recovery window is half-open, so
([a,b)) contains intervals (a,ldots,b-1).  For a fixed service power
(P), define

\[
b_t={\bf1}_{t\in S}\frac{P\Delta t}{\eta_d},
\qquad
a_t={\bf1}_{t\in R}\eta_c\bar c_t\Delta t,
\]

where (b_t) is mandatory stored-energy withdrawal and (a_t) is the
maximum stored-energy recovery.  Let

\[
A_{ij}=\sum_{t=i}^{j-1}a_t,
\qquad
B_{ij}=\sum_{t=i}^{j-1}b_t.
\]

At node (i), the admissible energy interval is
([p_iE,q_iE]).  The initial node is (p_0=q_0=s_0); internal nodes use
(p_i=s_{\min},q_i=s_{\max}).  For an exact terminal target,
(p_T=q_T=s_T).  For an at-least target,
(p_T=\max(s_{\min},s_T)) and (q_T=s_{\max}).

## Pseudocode

```text
certificate(P, cbar, dbar, S, R, dt, eta_c, eta_d, s0, sT, smin, smax, mode):
    validate finite nonnegative inputs and non-overlapping half-open masks
    reject if P > min(dbar[t] for t in S)
    a[t] = eta_c * cbar[t] * dt if t in R else 0
    b[t] = P * dt / eta_d       if t in S else 0
    A[0] = B[0] = 0
    for t = 0,...,T-1:
        A[t+1] = A[t] + a[t]
        B[t+1] = B[t] + b[t]
    set (p_i, q_i) at the initial, internal, and terminal nodes
    E_low = 0; E_high = +infinity
    for i = 0,...,T-1:
        for j = i+1,...,T:
            Aij = A[j] - A[i]; Bij = B[j] - B[i]
            # ceiling/monotonicity cut
            c1 = p_i - q_j; rhs1 = Bij
            if c1 > 0: E_high = min(E_high, rhs1 / c1)
            if c1 == 0 and rhs1 < 0: return infeasible
            # recovery/reachability cut
            c2 = p_j - q_i; rhs2 = Aij - Bij
            if c2 < 0: E_low = max(E_low, rhs2 / c2)
            if c2 > 0: E_high = min(E_high, rhs2 / c2)
            if c2 == 0 and rhs2 < 0: return infeasible
    return feasible iff 0 <= E_low <= E_high, with active witnesses
```

The code records the equivalent positive-denominator form for the lower cut,
((B_{ij}-A_{ij})/(-c_2)), to avoid a sign error.  Optional charging may be
curtailed at the SOC ceiling; no surplus charge is forced into the state.
The export-bound check is a separate prerequisite because Eq. (8) concerns the
scalar SOC layer after the interval AC audit.

## Worked numerical example

Take (T=2), (Delta t=1) h, (S=[0,1)), (R=[1,2)),
(P=1) kW, (\bar c=(2,2)) kW, and (\bar d=(10,10)) kW.  Set
(eta_c=0.9), (eta_d=0.8), (s_0=0.8), (s_T=0.9),
(s_{\min}=0.2), and (s_{\max}=1.0).  Then

\[
a=(0,1.8),\qquad b=(1.25,0).
\]

The first service interval gives the lower witness

\[
(0.8-0.2)E\ge 1.25
\quad\Longrightarrow\quad E\ge 2.083333\ {\mathrm{kWh}}.
\]

The full-horizon recovery cut gives the upper witness

\[
0.1E+1.25\le 1.8
\quad\Longrightarrow\quad E\le 5.5\ {\mathrm{kWh}}.
\]

Thus the exact scalar feasible-capacity interval is

\[
2.083333\le E\le 5.500000\ {\mathrm{kWh}}.
\]

For (E=4) kWh, service leaves (0.8E-1.25=1.95) kWh and the recovery
interval charges (1.65/0.9=1.833333) kW, reaching (0.9E=3.6) kWh.
At (E=2) kWh the post-service state is below the (0.2E) floor; at
(E=5.6) kWh the required stored recovery (1.25+0.1E=1.81) kWh exceeds
the 1.8-kWh recovery limit.

## Boundary cases and tests

The implementation rejects overlapping service/recovery windows, empty service
windows, non-integral or out-of-range endpoints, negative limits, and invalid
SOC/efficiency values.  An empty recovery set is allowed for a one-call edge
case, but exact terminal equality can then make the certificate infeasible.
The tests cover exact versus at-least terminal targets, half-open interval
membership, no-surplus charging at the SOC ceiling, export-limit witnesses,
the middle recovery-window cut, and both sides of a certificate boundary.  The
worked example above is a regression test with the expected interval and
feasibility at (E=2.0,4.0,5.6) kWh.

The certificate is (O(T^2)) in time and (O(T)) in working memory.  It is
exact for the declared scalar inventory LP and remains silent about the joint
nonlinear AC feasible set.

## Fixed-recovery comparator and infeasibility convention

The fixed-recovery comparator is a separate policy constraint, not a second
certificate. For the declared recovery mask `R`, it sets

```text
c_t = r P  for every t in R,
c_t = 0    outside R,
r = N_service / (N_recovery * eta_c * eta_d).
```

Here `c_t` and `P` are AC-side kW and `N_*` count half-hour intervals. The
ratio follows from

```text
eta_c * (r P) * N_recovery * dt
    = (P / eta_d) * N_service * dt.
```

The LP also imposes `c_t <= cbar_t`; a row is infeasible whenever `rP`
exceeds any declared recovery charge bound, or when the resulting SOC
trajectory violates either SOC bound or the exact terminal equality. An
infeasible fixed policy is retained as an infeasible row (service power zero
in summaries that require a numeric endpoint); it is never silently replaced
by the work-conserving scalar LP. For `terminal_mode=exact`, optional charging
in the scalar LP may be curtailed in the final recovery interval to hit
`e_T=E*s_T`; for `terminal_mode=at_least`, remaining headroom may be left
unused.

The certificate itself does not impose `c_t=rP`: it audits the
work-conserving interval `0 <= c_t <= cbar_t` policy. Comparing the two
therefore measures a declared recovery-rule restriction only after service
windows, recovery mask, efficiencies, SOC bounds, terminal mode, and AC-bound
arrays are held fixed.

The independent random regression
`tests/test_capacity_certificate.py::test_certificate_matches_fixed_power_lp_on_deterministic_random_instances`
checks 250 fixed-power instances against the HiGHS implementation with a
fixed seed. It compares the closed interval returned by the cumulative cuts
with the LP at a randomly selected capacity and exercises exact terminal SOC,
multiple half-open windows, efficiency losses, SOC ceiling truncation, and
both feasible and infeasible rows.

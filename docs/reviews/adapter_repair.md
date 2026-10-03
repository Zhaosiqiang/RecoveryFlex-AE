# AC snapshot adapter repair (2026-10-03)

This note records the independent review and repairs to `src/recoveryflex/ac_snapshot.py`.
The adapter is the evidence path used by the measured-AC experiment; the old
process-global adapter and experiment data were not changed.

## Repairs

- **No automatic controls during snapshots.**  After redirecting a master file,
  the adapter issues `set controlmode=off` and uses OpenDSS `InitSnap()` followed
  by `SolveNoControl()`.  A master may contain its own `Solve` while it is
  redirected; that initial parse-time solve cannot be intercepted, so the
  adapter immediately establishes the held-control snapshot state.  Three
  no-control passes are used because OpenDSS can report `Converged` while a
  second pass still updates currents after a large load jump.  Repeated events
  therefore do not depend on the preceding event's Newton warm start.

- **Surrogate isolation is case-insensitive.**  Internal `BatRF*` and `PVRF*`
  load names are excluded from the native-load baseline using `casefold()`.
  A solver version that changes name casing cannot scale a battery/PV twice.
  `reset()` also clears all generated element dictionaries before recompiling.

- **Transformer thermal evidence is winding/phase based.**  `CktElement.Powers()`
  is not used as the transformer thermal limit: summing terminal kVA can hide a
  single-phase overload and `Transformers.kVA()` is only the active winding.
  The adapter reads `Transformers.WdgCurrents()`, which OpenDSS returns as
  complex current pairs for both terminals, and reports
  `transformer.<name>.wdg<w>.phase<p>` plus an aggregate maximum.  Each current
  is divided by the corresponding winding base-kVA current rating.  For a
  2/3-phase winding, `kV` is phase-to-phase; a wye winding rating uses
  `kV/sqrt(3)` and a delta winding uses `kV`.  The calculation is therefore
  `I_rating = (kVA / nphase) / V_winding` (A after the kV conversion), with the
  maximum magnitude across the two winding terminals.  The aggregate transformer
  loading is the maximum phase ratio, so one overloaded phase cannot be masked by
  a three-phase sum.  `transformer_loading_limit` is explicit and defaults to
  `line_loading_limit` for backward-compatible feasibility semantics.

- **Failure records are actionable.**  `SnapshotAudit.failure_reasons` and
  `limiting_component` distinguish non-convergence, non-finite voltages or
  currents, lower/upper voltage violations, line loading, transformer
  winding/phase loading, battery readback mismatch, unknown battery sites, and
  adapter exceptions.  The human-readable `error` field contains the same
  classification and the offending component/value.

## Validation

`tests/test_ac_snapshot.py` now covers:

1. IEEE-13 and IEEE-123 solves with finite winding/phase ratios and measured
   battery readback;
2. case-insensitive exclusion of generated surrogates from native loads;
3. aggregate transformer loading equal to the maximum per-winding/per-phase
   ratio;
4. solve-order independence after low/high and high/low event sequences with
   controls held; and
5. explicit line and transformer-phase failure classifications.

The dedicated adapter tests pass (`6 passed`).  The OpenDSS API interpretation
used here follows the EPRI/DSS-Extensions definitions: `Powers()` is a complex
array of kW/kvar terminal powers, `WdgCurrents()` is the phase/winding current
array, transformer `kVA` is a winding base rating, and `SolveNoControl()` is the
snapshot solve that skips control actions.

API references: [EPRI WdgCurrents](https://opendss.epri.com/WdgCurrents.html),
[EPRI SolveNoControl](https://opendss.epri.com/SolveNoControl.html),
and the [DSS-Extensions Transformer schema](https://dss-extensions.org/dss-format/Transformer.html).

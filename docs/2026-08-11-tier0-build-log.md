# SDD ledger — plan: docs/superpowers/plans/2026-08-11-tier0-parameter-sweep.md

Branch: tier0-sweep (created off main at eeb4151 lineage; plan commit 8526b3b)
Env: Python 3.14.5, numpy 2.4.4, matplotlib 3.10.8
Governance: implementers EDIT ONLY. The orchestrator holds the commit boundary.
Pre-flight scan: clean. One note — the plan mandates assert-based `check_*`
functions and forbids pytest. Reviewers must receive that constraint verbatim
so the absence of a test framework is not flagged as a defect.

Env note (raised by the Task 1 implementer): `python` is not on PATH in the
agent shell — only `python3`. Plan text says `python sweep.py --check`. Carry
`use python3, not python` into every later dispatch. Not a code defect.

Task 1: implemented sweep.py (CONFIG, validate_config, cost_per_km2_yr,
check_cost). Committed by orchestrator as 4f08bbd.
Task 1: complete (commits 8526b3b..4f08bbd, review clean — spec ✅, quality
approved; reviewer independently re-derived the cost arithmetic).
Task 1: minor (deferred): python3-vs-python PATH note — env quirk, not a code
defect; already captured above.

Task 2: complete (commits 4f08bbd..1fff22c, review clean — spec ✅, quality
approved; reviewer re-derived the grid geometry and proved edge containment
generally, not just for the test case).
Task 2: minor (deferred): base_grid recomputes step as side/n, so `spacing_km`
is a NOMINAL label, not the literal inter-base distance. Over a 3808 km²
domain (side ~61.7 km) spacings 32.0 and 40.0 both collapse to n=1 — two axis
values with identical geometry and therefore identical results. Not a Task 2
defect (base_grid matches its spec). Mitigated rather than fixed: `n_bases` is
already a CSV column in Task 6, so duplicate geometry is visible in the output
instead of hidden. Carry this into Tasks 6 and 7 — the chart colours points by
spacing_km, which slightly overstates how many distinct grids were explored.

Task 3: complete (commits 1fff22c..ce62db9, review clean — spec ✅, quality
approved). Process note: the implementer subagent died on a network error
(ENOTFOUND) immediately AFTER finishing. Orchestrator independently re-ran
`python3 sweep.py --check` (exit 0, "all checks passed") before committing, so
the GREEN claim is verified rather than trusted. Reviewer confirmed the
fp_rate comparison direction is correct (higher fp_rate → fewer real fires),
the t_s sort is unconditional, and a zero-ignition season degrades to
correctly-shaped empty arrays without crashing.

Task 4: complete (commits ce62db9..49f6fe9, review clean — spec ✅, quality
approved on the most capable model, since dispatch is load-bearing). Reviewer
confirmed NO assertion was altered to fit the code, derived the contention
case to exactly 300 s independently, and verified the km→m conversion is
applied exactly once. Process note: this reviewer went idle without sending
its verdict; it was re-queried and explicitly told not to reconstruct
conclusions it had not reached. It confirmed the analysis was complete and
only the send had failed.
Task 4: IMPORTANT finding, plan-mandated → escalated to owner. `utilisation`
sums each job's full lock-up time even when that window extends past the
season end, so it can exceed 1.0 under saturation; the `<= 1.0` assertion
holds only for the tested point (~2 orders of magnitude of headroom), not in
general. Owner delegated the call. RULING: amend the docstring only — keep the
code and the CSV column name (Task 6 asserts that key), and state in the
docstring that it is a workload ratio which can exceed 1.0 in the saturated
corner. Dispatched as a scoped fix after Task 5 commits, NOT fixed in the
controller session and NOT folded into Task 6 (which would muddy Task 6's
spec-compliance review).
Task 4: minor (deferred): launch latency is counted inside the busy window, so
if it models detect/confirm time rather than dock lock-up, utilisation is
biased conservative — never optimistic. Direction of bias on record.
Task 4: minor (deferred): sweep.py:230 runs ~92 chars against the file's
88-char discipline. Brief-verbatim; left alone.

Task 5: complete (commits 49f6fe9..e9ac432, review clean — spec ✅, quality
approved). PROCESS DEVIATION, on the record: three consecutive reviewer
subagents (review-task5, a re-query of it, and a fresh review-task5b) each
went idle without delivering a verdict. Rather than burn a fourth, the
ORCHESTRATOR reviewed Task 5 inline. This is a deviation from the skill's
"never review in the controller session" rule and is disclosed to the owner.
The final whole-branch review must re-cover Task 5 independently, since its
task-level review was not arm's-length.
Inline review findings: mask direction correct (selects real fires, not the
complement); all-nan early return precedes any percentile call so no
RuntimeWarning path; `unserved` uses `>` over real ignitions only; p90 of
[100,200,300] under linear interpolation is 280, consistent with the < 300.1
assertion; both checks wired; brief-verbatim, no extras.
Flake assessment for check_monotonicity: low risk. Law 1 compares 1 vs 9 vs 36
bases (large margins). Law 2 runs ~150 alerts against 9 drones over 120 days,
so contention is essentially nil and the p90s come out equal — which the `>=`
comparison accepts.
Task 5: minor (deferred): `validate_config` is defined but never called; it
stays dead code until Task 6 rewrites __main__ to call it. Verify in Task 6.
Harness note: implementer dispatches have succeeded 5/5; reviewer dispatches
have silently gone idle 3 times (Tasks 4 and 5). Task 4's reviewer had in fact
completed its analysis and only the send failed. Prefer implementer-role
agents where a choice exists, and always re-query before re-dispatching.
MITIGATION FOUND: adding an explicit "your FINAL MESSAGE must contain the
verdict; send a partial rather than nothing" instruction to the reviewer
dispatch fixed it — Task 6's reviewer reported normally.

Task 6: complete (commits e9ac432..c8e77db, review clean — spec ✅, quality
approved). Covers Change A (AXES, run_sweep, write_csv, check_sweep, __main__
rewrite that finally wires validate_config) and Change B (the owner-ruled
docstring amendment; reviewer confirmed dispatch's body is byte-identical).
Process note: the implementer died AFTER writing the code but BEFORE running
the sweep or writing a report. No task-6-report.md exists. The orchestrator
ran the sweep itself (execution, not editing) and the reviewer judged from the
diff plus results.csv directly.
SWEEP RESULT: 2880 rows, 4m19s wall-clock — well inside the plan's 30-minute
guard, so seasons_per_config stays at 50. p90 spans 2.8 min (5 km / 144 bases
/ 4 drones / 30 s latency, EUR 1522/km2/yr) to 40.2 min with 85% unserved
(32 km / 1 base / 1 drone / 180 s, EUR 6.4/km2/yr). Cost spans EUR 6.4-1919.1
per km2/yr. No nans.
EMPIRICAL RESOLUTION of the Task 4 Important finding: utilisation peaks at
0.128 across all 2880 configs, so the >1.0 saturation corner is never reached
in this sweep. The docstring caveat stands, but it is theoretical here.
Reviewer independently recomputed eur_per_km2_yr for two rows from CONFIG and
matched exactly; confirmed no seed collisions (season < 50 against a stride of
10_000, a unique divmod decomposition); confirmed the all-nan nanmean path is
unreachable given the 50-ignition axis floor (P ~ e^-50).
Task 2's duplicate-geometry artifact CONFIRMED in the output as predicted:
distinct n_bases = {1, 4, 9, 25, 49, 144}, six grids from eight spacing values.
Task 6 neither introduces nor worsens it.

Task 7: implemented (commits c8e77db..b87e9dc) — pareto_front, plot_pareto,
check_pareto, wired into --check and the __main__ else branch. Orchestrator
independently viewed pareto.png: three density panels present, frontier bends
with a clear knee, six visible point-bands matching the six distinct grids,
axis labels/colourbar/legend correct. Knee sits around EUR 100-200/km2/yr for
~6-10 min p90; past ~EUR 1000 the curve buys minutes at steep cost.
Task 7's arm's-length task review is FOLDED INTO the final whole-branch review
rather than run separately — disclosed, not skipped.

FINAL WHOLE-BRANCH REVIEW (opus, over 8526b3b..b87e9dc): verdict FIX FIRST.
It also went idle without sending and was re-queried; analysis had completed.
Verified clean: Task 5 re-covered independently (mask direction, all-nan early
return, `>` on real ignitions only — no defects; check_monotonicity run on 58
alternate seeds, 0 failures). Task 7 at depth (pareto_front matched a
brute-force 2D non-dominance check exactly, 16 vs 16 at density 150; tie
handling correct). Units contract holds end to end. Non-goals held. Size is
not drift — 244 of 508 lines are the eight check_* functions.

THREE IMPORTANT FINDINGS → one fix wave dispatched (impl-fixwave):
I-1 THE FALSE-POSITIVE AXIS WAS INERT. generate_season drew the TOTAL alert
count as Poisson then relabelled a share as fake, so raising fp_rate DELETED
real fires rather than adding drone load. Measured across all 2880 rows: fp
0.05→0.50 moved p90 by -0.4% (±4% noise) and utilisation by -0.00001. This is
an ORCHESTRATOR SPEC ERROR, not an implementer defect — the spec's World
section encoded it. Spec amended in the same session with a dated correction
note so Tier 1 cannot reintroduce it. Owner was warned explicitly not to claim
"we swept FP rate 5-50% and response held" — the model could not produce that
result. Not Critical only because utilisation peaks at 0.128, so the system is
distance-dominated; near utilisation 1.0 this would have been Critical.
I-2 No common random numbers: run_sweep seeded by idx, so every config drew
independent seasons and pareto_front kept whichever replicate drew lucky.
Frontier ~1-2% optimistic. Fixed by seeding on (density_idx, fp_idx, season).
I-3 The cheap end of the slide hid a 74-77% unserved rate at EUR 6.4-13.3/
km2/yr, plotted as legitimate frontier points. Fixed with a
CONFIG["max_unserved_share"] = 0.10 quality floor on frontier eligibility.
FIX 4: seasons_per_config restored to the spec's 200 (~17 min, inside the
30-min guard). The reviewer contested the earlier 50 ruling and WON that
argument — 4m19s at 50 argued for raising it, not for stopping there. Also
de-vacuumed check_monotonicity Law 2, which passed on exact equality
(625.37/623.62/623.62) because its load was too light for drone count to
matter — it guarded nothing.
Minors left alone: validate_config covers 1 of 3 spec validations (harmless
with hardcoded AXES); p90 is mean-of-per-season-p90 not pooled (1.7% gap at
worst); nominal spacing_km; latency inside busy window; 92-char line.

FIX WAVE: complete (commit b87e9dc..2a80327). Process note: the fix-wave agent
died after writing the code but before re-running the sweep or reporting, so
the orchestrator ran the ~20-minute sweep itself and measured the results.
SCOPED RE-REVIEW (opus, the single permitted re-review): SHIP. All four
ADDRESSED, no new Critical/Important breakage. It verified array alignment
EMPIRICALLY rather than by reading — replayed the seed and confirmed t_s,
xy_km and is_real all derive from ONE argsort (array_equal True on all three),
so the decoupling risk is closed. Derived E[fake share] = f analytically and
measured 0.2989 at f=0.30 over 300 seasons. Proved the CRN seed formula
injective (disjoint digit ranges). Reproduced a full CSV row to the last digit
from current code, proving results.csv IS this diff's output.

CORRECTION TO AN ORCHESTRATOR-REPORTED NUMBER: "+60.7% p90 at 1 base" was
overstated. Correct: +4.6% across all 1-base configs, +12.2% at 1 base with
400 ignitions, +60.4% only in the most contended slice (1 base, 1 drone, 400
ignitions). Qualitative finding stands — FP rate bites only when the fleet is
thin — but the magnitude was a narrow slice reported as a regime. Owner was
told.

FINAL STATE: 8 commits on tier0-sweep. results.csv 2880 rows, 1885 feasible
under the 10% quality floor (630/630/625 per density panel, so no panel hits
the empty-frontier path). Cheapest feasible EUR 25.74/km2/yr at 14.8 min p90,
9.6% unserved. Fastest EUR 1125/km2/yr at 2.9 min. Utilisation now peaks 0.25.

PARKED RESIDUALS (no second fix wave permitted; all non-blocking):
P-1 Nothing enforces seasons_per_config < 1000. The comment claims the bound;
validate_config does not check it. At 1000+ the CRN seeds silently collide
with density_idx — a real trap for whoever next raises the season count.
One-line fix in validate_config. HIGHEST-VALUE residual; fix before Tier 1.
P-2 The CRN seed keys on axis POSITION, not value, so a subset run draws
different seasons than the full sweep for the same parameters. Correct within
a run; sub-runs are not comparable to results.csv.
P-3 plot_pareto(rows, cfg=CONFIG) uses a mutable default arg. Never mutated,
harmless.


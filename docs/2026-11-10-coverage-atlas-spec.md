# Coverage Atlas: implementation contract

## Goal And Non-Goals

Add a captured, local spatial-coverage explorer. Historical science and
captures remain unchanged. Coverage means the fraction of equal-area cell
centers reached within 900 seconds by an initially idle network. It is NOT a
season success rate, ignition-risk estimate, confidence interval, forecast,
detector result, geographic map or flight-control system.

No terrain, routing, new physics, queue simulation, online recomputation,
downloads, packages, cloud services, storage or new numerical metrics.
Workers implement presentation/adapters only. Lead owns numerical code,
scenario definitions, capture writing/verification, fixtures, data contracts
and scientific regression tests. Worker reports are proposals until reviewed.

## Tests First

1. Lead engine equals independent calls to existing dispatch_physical for at
   least 120 specified single-alert comparisons; response error <=1e-9 seconds,
   identical reachability/timeliness and original base identifiers.
2. Exactly 388 unique scenarios; all 8 nominal 12 m/s headings stay at or below
   the model weather limit without changing that limit. Exactly 2 weather-
   closure scenarios have 0 served cells. Original source/capture hashes match.
3. Every 80x80 case has 6400 cell records and 4 exclusive outcome counts summing
   to 6400. Counts/fractions match the arrays, verified by lead, not UI workers.
4. Lead compares 40/80/160 cell-center resolutions for declared cases, reports
   observed numerical differences, not statistical intervals or convergence
   guarantees. Never infer numerical convergence from one resolution.
5. Missing/tampered capture, unknown case and wrong provenance cause 0 successful
   payloads. No silent fixture data or automatic capture generation.
6. New HTTP paths retain existing Host/Origin/security/JSON safeguards. Existing
   mission, replay and CLI behavior remains unchanged. Unlisted assets and
   traversal fail; atlas tests and raw archives are not HTTP-served.
7. Session round trips preserve exactly selected case(s)/cell and capture hash.
   Unknown keys/cases, malformed/oversized text, bad hashes/indices reject
   before callback. Failed import causes 0 API requests and 0 state mutations.
8. Latest request wins: 0 stale case/partner payloads publish after case changes
   or comparison toggle-off. No 2 panes with mismatched capture/grid.
9. Map selected cell is consistent at 1440x1000 and 390x844, including all 4
   corners and center. Shared selection persists across 2 panes. Null response
   means unavailable, never zero. No invented paths or base assignments.
10. Browser save/restore, filters, paired cases, table selection and exact-result
    JSON downloads work with 0 page/console/external request errors and 0 page
    horizontal overflow. Real API must be exercised, not only fetch stubs.
11. Deliberately broken numerical and provenance guards must make existing
    assertions fail. One final Python gate after integration; native JS tests
    stay standalone. New tests must work in a clean checkout without private
    captures, credentials, network or optional browser packages.

## Lead-Owned Science And Capture

New lead modules: coverage_scenarios.py, coverage_engine.py, coverage_capture.py,
coverage_test_fixture.py and coverage_web/data_contract.js. Do not edit these.
They may not yet exist in your snapshot; use the exact interfaces here.

coverage_scenarios.make_scenarios() returns 388 ordered descriptors:
- Layouts 9 and 25 from simulator_engine.layout_bases, original IDs retained.
- Eight directions (degrees toward which wind blows, east=0, north=90), speed
  12; diagonals use signed 12/sqrt(2) components, not rounded trig values.
- At every direction/layout, reference healthy plus every single-site outage:
  8*(10+26)=288 scenarios.
- Two selected outage pairs per direction/layout, [0,1] and [0,center_id]:
  32 scenarios. These are NOT exhaustive or worst-pair optimization.
- Four healthy stress profiles at every direction/layout: endurance 36 min,
  reserve .35, launch 180 seconds, and all three combined: 64 scenarios.
- Two healthy calm reference cases and two healthy 13 m/s weather-closed cases.
- Reference parameters: airspeed18, endurance46, reserve.25, launch60, model
  dwell/max-wind/layout/900-second deadline unchanged. No queueing.

Descriptor keys: case_id (opaque unique string), n_bases, wind_mps (2 numbers),
wind_speed_mps, heading_deg (null for calm), profile (reference, short_endurance,
larger_reserve, slow_launch, combined), offline_bases (sorted original ID list),
airspeed_mps, endurance_min, reserve_fraction, launch_latency_s.

coverage_capture.write_capture(root, scenarios=None, grid_n=80) exclusively
creates a new directory and writes scenarios.json, summary.csv, coverage.npz,
manifest.json. Never overwrites. No scientific configuration in worker files.
coverage_capture.load_capture(root) verifies hashes, numerical consistency,
types, coordinates, case order and source generation; returns a dict:
{manifest, scenarios, summary_rows, arrays, capture_sha256}.
Missing/corrupt input raises ValueError or OSError. No automatic recomputation.

manifest fields: schema_version1, kind="wildfire-coverage-atlas-capture",
study_id="2026-11-10-coverage-atlas-v1", grid_n, domain_side_km,
timely_threshold_s900, outcome_codes={"unreachable":0,"late":1,"timely":2,
"weather_closed":3}, source_sha256, files (filename->SHA256), grid={
order:"y-major-x-fast",locations:"cell-centers",north:"positive-y"}, limitations.
capture_sha256 is SHA256 of manifest.json bytes, returned by the lead loader.

NPZ arrays: case_ids (ordered strings), x_km and y_km (grid_n center-coordinate
vectors), response_s (float64 cases x grid_n x grid_n; +inf for unserved),
selected_base_id (int16 same shape; -1 unserved), outcome_code (uint8 same shape).
Response/base are from the lead engine, not reconstructed by adapters.

summary_rows are typed dicts: case_id, timely_cells, late_cells,
unreachable_cells, weather_closed_cells, total_cells, timely_area_fraction,
reachable_area_fraction. Fractions in [0,1] are already calculated. Do not
calculate new rates, deltas, intervals, rankings or scientific classifications.

coverage_test_fixture.create_fixture(root) writes a small real capture using
lead-approved first/last scenarios at grid_n4, returning root. Numerical fixture
configuration is lead-authored. Tests may call it, never invent study inputs.

## Backend Interfaces

coverage_data.CoverageData(root=None): root defaults to
ROOT/research_results/2026-11-10-coverage-atlas-v1. Constructor stores path;
load lazily via lead load_capture, no startup requirement that capture exists.
Methods catalog() and case(case_id) return independent JSON-safe dicts.

catalog(): schema_version1, mode="coverage_catalog", study_id, capture_sha256,
grid_n, domain_side_km, timely_threshold_s, outcome_codes, source_sha256, grid,
limitations, layouts={"9":[base records],"25":[base records]}, cases=[descriptor
with summary:typed summary row]. Layout records use existing layout_bases.

case(id): schema_version1, mode="coverage", study_id, capture_sha256, grid_n,
domain_side_km, timely_threshold_s, outcome_codes, source_sha256, grid,
limitations, case (same descriptor+summary), bases (original IDs, availability
based on offline_bases), cells=[{index,row,column,x_km,y_km,outcome,
response_s,selected_base_id}]. outcome is the string for the stored code.
index=row*grid_n+column. Coordinates come from stored x_km/y_km, not new
geometry. +inf/-1 become null; no NaN/Infinity in JSON.

Server adds GET /api/coverage/catalog and GET /api/coverage?case=<id> only.
No POST, generation, local filesystem-path parameter or source exposure.
Existing make_server gains keyword-only coverage_root=None, used for tests;
otherwise retains its current parameters and behavior. Lazy CoverageData
instance. Missing/corrupt capture => JSON503, invalid query/unknown case =>400.

Serve /coverage and /coverage/ as coverage_web/index.html (no external redirect
required); /coverage/<allowed basename> from coverage_web. Allowed basenames:
index.html,styles.css,app.js,map.js,controls.js,table.js,details.js,comparison.js,
export.js,session.js,api.js,state.js,legend.js,data_contract.js.
No directory serving. Reuse existing local-origin/path/MIME/CSP protections.
Font URL /fonts/geist-latin.woff2 already exists. Keep old root UI intact.

coverage_client.main(argv=None)->int: --base-url (same loopback validation as
simulator_client), catalog and case --case ID subcommands. Reuse existing
_local_base_url/_request_json, no redirects, JSON stdout, clean stderr/exit2
on error. No CSV metrics or subprocess/network destinations beyond that server.

render_coverage.main(argv=None)->int: --capture PATH --output NEW.md.
Read via CoverageData; render an escaped Markdown inventory/table with stored
scenario inputs, stored counts/fractions, provenance and limits. No imports
from science modules except the reader, no recomputation/plots. Exclusive
output creation; existing output unchanged on failure.

## Browser Contract

No packages/bundler, pure ES modules, native DOM, local Geist Sans, neutral
palette with #006bff. No orange, gradients, emojis or redesign of Mission Lab.
Prefix styles/IDs cov-. All modules exports below are named, imports at top.
No innerHTML, eval, storage, external URLs or invented fallback data.

Lead data_contract.js exports validateCatalog(catalog)->catalog,
validateCase(payload,catalog)->payload, validatePair(a,b,catalog)->{a,b}.
These throw on schema/provenance/coordinate/outcome mismatch. They do NOT
compute new scientific metrics. Other modules must call them, never replace.

api.js: createCoverageApi({fetchImpl=globalThis.fetch,baseUrl=""}={}) returns
async catalog({signal}={}) and case(caseId,{signal}={}). Only the 2 endpoints
above; encode query, same-origin credentials, require successful JSON object,
surface status/error. No request on construction.

state.js: createCoverageStore(initial={}) returns getState(),patch(partial),
subscribe(fn)->unsubscribe. Independent structuredClone snapshots; no DOM/I/O.

map.js: createCoverageMap(container,{onCell=()=>{},idPrefix="cov-map"}={})
returns render(payload,selectedCellIndex=null),setBusy(bool),destroy().
Canvas heatmap: north up, stored outcomes, no scientific interpolation. Include
base markers from actual payload and original IDs; no inferred trajectories.
Responsive device-pixel ratio handling. Click maps to an existing cell;
arrow keys move one cell, Home/End first/last, Enter selects; labelled focusable
canvas and live text announce stored selected-cell values. Export pure
cellFromPoint(x,y,width,height,gridN)->index|null (coordinates inside canvas,
y screen down, outside/nonfinite/invalid dims =>null); this is pixel mapping,
not geography. Unique IDs and full listener/resize cleanup. No 6400 tab stops.

controls.js: createCoverageControls(container,{onCase,onCompare}={}) returns
setCatalog(catalog),setSelection({case_id,compare_case_id=null}),setBusy(bool),
destroy(). Primary/optional comparison selectors plus metadata-driven filters
n_bases/profile/wind_speed_mps/heading_deg/outage_count. Case IDs opaque.
onCase(caseId); onCompare(caseIdOrNull). Never request data itself or fabricate
pair partners. Keep selection consistent when filters change.

table.js: createCoverageTable(container,{onCase}={}) returns render(catalog,
selectedCaseId=null),setFilter(caseIdsOrNull),destroy(). Stored summary fields
only, escaped DOM cells, selectable row/button, responsive scroll wrapper.
No fresh metrics, data export or guessed role ordering.

details.js: createCoverageDetails(container) returns render(payloadOrNull,
selectedCellIndex=null),showError(message),destroy(). Explain exact selected
case, model limits and stored cell outcome/response/base; null not zero.

comparison.js: createCoverageComparison(container,{onCell}={}) returns
render(primary,secondary,selectedCellIndex=null),setBusy(bool),showError(text),
destroy(). Uses 2 createCoverageMap instances with distinct idPrefix values;
calls lead validatePair using catalog supplied by setCatalog(catalog).
Never compute rates/differences or own a second selection state.

legend.js: createCoverageLegend(container) returns render(catalog),destroy().
Explain 4 stored outcomes, cell-center approximation, one-alert/idle assumption
and non-field-validation. Include textual/color-independent cues.

export.js: createCoverageExport(container) returns setSnapshot(snapshot|null),
setBusy(bool),destroy(). Full received JSON only. snapshot={primary,secondary}
where secondary=null or exact received payload. Explicit download button,
disabled absent/pending; safe Blob URL cleanup and filename wildfire-coverage-
<primary.case.case_id>.json (sanitize ID for filename). No recomputation.

session.js pure makeSession(snapshot,catalog,{selectedCellIndex=null}={}) and
parseSession(text,catalog) validate exact shape:
{kind:"wildfire-coverage-session",schema_version:1,capture_sha256,
case_id,compare_case_id:null|string,selected_cell_index:null|int}.
Both case IDs in catalog; selected index in [0,grid_n*grid_n); SHA exact catalog
64-lowercase-hex; no supplied results. Native JSON semantics, max65536 text
chars and file bytes, no false duplicate-key detection claims. Ignore edited
controls; save only validated received snapshot. Panel createCoverageSession(
container,{onRestore}={}) returns setCatalog,setSnapshot(snapshot,options={}),
setBusy,destroy. Catch callback failures; late older file reads ignored.
onRestore receives parsed thin session only, before no API/state mutation.

app.js is sole integrator. Required DOM IDs: cov-controls,cov-map,cov-compare,
cov-table,cov-details,cov-legend,cov-export,cov-session,cov-status.
Load/validate catalog once, then its first actual case. One store owns selected
case, optional secondary, selected cell and latest tokens. Validate every
response against catalog and requested case before publish. Clear downloads
while pending/failed. Invalidate old partner on changes/toggle-off. Primary
map hidden only when 2 validated panes ready; errors retain last successful
map but no stale successful export. Session restore requests exactly selected
case(s), no intermediate default. Selection shared across maps/details.
Show loading/error/empty states accessibly; never call the science engine.

HTML declares those IDs, stylesheet/module paths and same local font, links
back to /. CSS uses actual module classes cov-*, stacks paired maps on mobile,
contains tables without clipping keyboard focus. No inline script/style.

Shared class contract (HTML/CSS/modules use these exact names): cov-main,
cov-header,cov-hero,cov-layout,cov-panel; cov-button and cov-button-primary;
cov-controls-form,cov-field,cov-select; cov-map-view,cov-canvas,cov-map-live;
cov-table-wrap,cov-table,cov-row-selected; cov-detail-list,cov-error,cov-status;
cov-pair-grid,cov-pane,cov-pane-title,cov-pair-status; cov-export-actions;
cov-session-content,cov-session-actions,cov-session-file-label,cov-session-file,
cov-session-status; cov-legend-list,cov-legend-item,cov-legend-swatch.
CSS defines outcome variables --cov-timely:#47a447, --cov-late:#f5a623 (status
amber only), --cov-unreachable:#7d7d7d, --cov-weather:#171717. Canvas/legend use
those same values. Timely=solid, late=diagonal hatch, unreachable=dots,
weather=crosshatch with text legend, selected cell=blue outline. Global
[hidden]{display:none!important}. Focus outlines must not be clipped.

## Test Ownership And Documentation

Python worker tests use unittest and the real create_fixture in TemporaryDirectory,
not private captures. Server tests use make_server(coverage_root=fixture_root)
with existing port parameter; inspect supplied server source for its signature.
CLI/renderer tests invoke real main/subprocess; no mocked network-only success.
Node tests use node:test and assert/strict, data-URL imports for no-package ESM.
Fetch stubs permitted only for transport negatives; final real HTTP/browser
tests mandatory. Sessions test all schema/hash/case/index/size edges and
caller-object isolation; state tests cloning/unsubscribe; API tests endpoints,
encoding/status/parse/abort/no eager fetch. Asset tests assert exact allowlist,
no test/capture exposure or remote assets, not permissive subset checks.

Docs distinguish spatial approximation from previous season experiments.
Scenario inventory states exact coverage and omissions, no claim of all
possible scenarios. README edits only Mission Lab/Atlas navigation section.
All workers report UNTESTED, never claim tests ran. Only lead integrates,
validates scientific results, commits, publishes or changes scope.

# Mission Lab: test-first build contract

## Confirmed Context And Goal

User wants15 agents moving research project forward through real features,
not another audit fleet. Research/resume showcase, for the author and research
reviewers inspecting synthetic assumptions. Existing research-dossier tone,
Geist Sans, blue006bff, neutral white/ink, no orange, gradients or emoji.

Deliver a LOCAL interactive mission sandbox plus a separate frozen-season
replay/evidence explorer. No new framework, package, cloud service or model.
Standalone Python transport and browser-native modules, isolated from existing
research runners. Existing models, protocols and frozen studies unchanged.

## Tests Before Implementation Plan

Lead authors all numerical adapter/configuration/measurement tests.

1. At a base in calm wind, response equals launch latency60s, flight times0,
   airborne equals existing dwell120s, chosen base exact original index.
2. For base0 to point10km east, air18/wind6 east: outbound416.6666667s,
   return833.3333333s, airborne1370s, within1e-6; selected route must match
   actual dispatch_physical response within1e-9.
3. Wind13 east gives weather_rejected/null response/no selection; reserve.9
   and endurance1 yields battery_rejected with finite flight candidates.
4. Remove selected base, exactly1 unavailable, same original site IDs and
   dispatcher equality. All9/25 sites individually removable, no mutation.
5. Negative/nonfinite/bool/out-of-domain/unknown input fields rejected.
   Response serializes strictJSON, unreachable values null, never NaN/Infinity.
6. Replay first and last seasons of all8 cases must equal actual captured
   offsets/coordinates/real flags/responses and per-season CSV counts.
   Canonical rates/contrasts exactly equal captured CSV, never re-aggregated.
7. Tampered capture fails startup. Snapshot arrays read-only; returned caller
   objects cannot mutate future responses. Capture receipt stable before/after
   loading. Replay never calls a generator/dispatcher/runner.
8. Real HTTP ephemeral loopback server: catalog200; valid mission200;
   unknown route404; traversal404; invalidJSON400; oversize413;
   bad content type415; wrong Host/Origin403; no CORS credentials;
   static files only exact whitelist. Every JSON finite.
9. Browser at1440x1000 and390x844: no console/page/network failures,
   no horizontal overflow, actual map target changes backend result,
   wind13 rejects, offline toggle changes availability, replay requests a
   distinct case/season, play/pause/scrub work, export parses as actual JSON.
   Replay markers:0 before first alert, exact captured count at its timestamp,
   all captured alerts at season end; selected alert survives subsequent frames.
   CLI redirect targets receive0 requests, nonfinite JSON exits2 with empty stdout.
10. Deliberate bad return-flight and replay-offset mutations fail real numerical
    assertions; actual source/input mutation rejected, not mocked success.

## Lead-Owned Numerical/Data Interfaces

New simulator_engine.py:
- PROTOCOL from simulator_protocol.json; default_parameters()->dict with
  point_km (fraction converted using sqrt(CONFIG.domain_km2)), all other defaults.
- model_metadata()->dict: domain_side_km, defaults, parameter_limits,
  layouts (object keys"9"/"25", arrays{id,x_km,y_km,available:true}),
  assumptions {dwell_s,turnaround_s,max_wind_mps,queueing:false},
  source_sha256, limitations.
- run_mission(payload:dict)->dict. Merge defaults, reject extra fields.
  n_bases exactly9/25, offline_base null or original index, point_km in square.
  wind components use configured bounds; numeric fields finite non-bool.
  Actual dispatch_physical is authoritative, one alert at0, idle drones.
  Explain candidates using existing flight_times; assert chosen route/time
  matches dispatcher, fail on disagreement. No model change or JS physics port.
- Result keys: schema_version1,mode"mission",inputs(normalized),domain_side_km,
  point_km,bases[{id,x_km,y_km,available}],candidates[{base_id,outbound_s,
  return_s,airborne_s,arrival_s,flight_ok,battery_ok,eligible,reason}],
  selected_base_id(int|null),status(existing dispatcher status),response_s
  (finite|null),within_15min(bool),usable_airborne_s,assumptions,
  source_sha256,limitations. reason offline/weather/flight/battery/eligible.
- Snapshot source hashes, fail if code/protocol changes after module load.

New simulator_data.py:
- DEFAULT_CAPTURE public frozen resilience directory.
- ExplorerData(capture_dir=DEFAULT_CAPTURE), catalog()->dict,
  replay(case_id:str,season:int)->dict.
- Immutable verified snapshot; load with allow_pickle=False, reverify before
  accepting snapshot. Catalog freshly copied on return.
- catalog keys: schema_version1,mode"catalog", plus model_metadata fields,
  study{id,manifest_sha256,heldout_seasons,training_seasons,heldout_real_alerts,
  cases[{case_id,n_bases,wind_east_mps,offline_base(null healthy),active_bases}],
  summary[actual canonical CSV rows, numeric fields parsed],
  contrasts[actual canonical CSV rows, numeric fields parsed],
  limitations}. study.id="2026-11-09-resilience".
- replay keys: schema_version1,mode"replay",case_id,season,domain_side_km,
  season_days,bases,counts(actual selected season CSV row),study_manifest_sha256,
  alerts[{index,alert_s,x_km,y_km,is_real,response_s,within_15min,status}],
  limitations. Alert status within_15min/late/unreachable, NOT invented
  battery/queue/flight assignment reasons. Null infinite responses.
- No new simulation, source counts, rates or bootstrap computation for replay.

## Transport Contract (Agent01)

simulator_server.py: WEB_ROOT=.../simulator_web,
make_server(port=0,data=None,web_root=WEB_ROOT)->ThreadingHTTPServer.
Server binds127.0.0.1 only; .server_address supplies actual port.
data defaults ExplorerData; handler calls data.catalog(), data.replay(),
and run_mission(payload). CLI --port(default8765), --capture(optionalPath),
start via .venv/bin/python simulator_server.py. Ctrl+C shutdown cleanly.

GET /api/catalog, GET /api/replay?case=ID&season=0 (each param exactly once),
POST /api/mission (application/json, length1..4096, strict finite/duplicate-key
JSON). GET / and /index.html plus exact root filenames below; no arbitrary
filesystem handler, directory listing, traversal, symlink serving or CORS.
Asset whitelist: index.html,styles.css,app.js,state.js,map.js,controls.js,
mission.js,replay.js,evidence.js,export.js,fonts/geist-latin.woff2.
No access to source code, captures or home directory through static routes.
Host allowlist127.0.0.1:actualport and localhost:actualport; absent/disallowed
Host rejected. If Origin present require matching same-origin local scheme/
host/port, otherwise403. No auth, cookies, secrets, external binding or deploy.
Route/method404/405, malformed input400, size413, media415, unexpected500
generic message. Error shape {"error":"human-readable message"}.
JSON uses allow_nan=False. Correct content types, no-store API, CSP self-only,
nosniff. Do not log posted bodies. No writes except user CLI exports.

## Browser Module Contracts (Agents02-10,14)

Native ES modules, textContent/createElement, never innerHTML with API/input.
No scientific metric arithmetic, fake data or imports from numerical code.
Only harmless display formatting/coordinate transforms. All defaults/bounds
come from catalog. Explicit source distinction: sandbox changes NEVER update
frozen evidence. Browser calls same-origin API, no remote libraries/CDNs.

index.html: title Wildfire Sweep / Mission Lab, css styles.css, module app.js.
IDs: controls,map,mission-results,replay-controls,evidence,export,status.
Mode buttons [data-mode="mission"],[data-mode="replay"], aria-pressed.
Sections data-panel="mission"/"replay" for mode visibility. Map stays visible.
aria-live status, accessible landmark headings/labels. No inlineJS/handlers.

state.js:
- createStore(initial={}) -> {getState(),patch(partial),subscribe(fn)->unsubscribe}.
  Subscriber receives new state; copies prevent caller mutation.
- createApi(baseUrl="") -> {catalog(),mission(payload),replay(caseId,season)}.
  Each returns Promise parsed JSON; non2xx rejects with server error message.

map.js: createMap(container,{onTarget,onAlert}) -> {render(view),destroy()}.
view: domain_side_km,bases,point_km,candidates,selected_base_id,
alerts(array),selected_alert_index,mode. Mission pointer/click and keyboard
arrows move clamped target (0.5km arrows); onTarget([x,y]).
Replay onAlert(index). Draw selected mission ground-track only; NEVER
fabricate routes/assigned bases in replay. SVG model coordinates, not real map.
Responsive viewBox, labelled SVG, non-color status glyphs.

controls.js: createControls(container,{onChange,onReset}) ->
{setCatalog(catalog),setValues(params),setBusy(bool),destroy()}.
onChange(partial) includes exact input keys, onReset() requests reset.
Inputs n_bases,offline_base,point x/y,wind x/y,airspeed,endurance,reserve,
launch. Advanced parameters in details. Preserve focus on update.

mission.js: createMissionPanel(container) ->
{render(result|null),setPending(bool),showError(message),destroy()}.
Show status/time/selected site, usable budget, exact per-base candidate table
and limitations, not invented season-wide success/cost numbers.

replay.js: createReplayPanel(container,{onRequest,onFrame,onAlert}) ->
{setCatalog(catalog),load(data),selectAlert(index),setBusy(bool),showError(message),reset(),destroy()}.
onRequest({case_id,season}); onFrame({alerts,current_s,selected_alert_index});
onAlert(index). Select case/season0..199, play/pause/scrub/speed. Clock seconds
within synthetic120-day season; default432000 simulated seconds per real second.
Paused initially. Display counts from captured data.counts, no recomputation.
Within displayed event list click onAlert and retain selected index.
Frames contain only alerts with alert_s <= current_s. At time0 no future
alerts appear; scrubbing changes the visible event set. Selecting an event
seeks to at least its captured alert time and persists through playback.
Replay map retains captured base markers but never draws assigned routes.

evidence.js: createEvidencePanel(container)->{render(catalog),destroy()}.
Canonical healthy/outage8 rows and6 contrasts, MC-only conditional intervals,
source manifest hash and research links. No subtracting/rederiving numbers.

export.js: createExportButton(container)->{setSnapshot(snapshot),destroy()}.
Download current complete received result + inputs/source provenance as JSON,
explicit user click, local Blob/objectURL cleanup. No invented measurements.
Disabled until snapshot present. Filename wildfire-mission/replay-UTC.json.

app.js imports all above, sole integration owner. Startup fetch catalog,
default mission request, wire map/form/reset/mode/replay/evidence/export.
Counter tokens suppress stale HTTP responses;150ms mission debounce.
On replay mode load selected initial case/season0; no fake success states.
Update map from real response only. Error/loading states accessible, no silent
fallback, all UI controls wired. New API responses alone replace results.

styles.css: sole stylesheet owner, use shared component data-slot attributes
and module classes prefixed map-/controls-/mission-/replay-/evidence-/export-.
Responsive control-rail/map/evidence layout, no dashboard card salad, no
gradients/orange/emoji, clear focus and reduced-motion. Local Geist font URL
fonts/geist-latin.woff2; preserve existing design-demos button interaction
source mechanics (36px default/40px large,6px radius,disabled opacity50%,
3px visible focus ring). Domain-specific SVG is custom scientific visualization.
Do not copy entire React starter or add dependencies.

## Other Owned Deliverables

Agent11 test_simulator_server.py: real ephemeral server/API/static/errors,
mock no model, no numerical test/rubric authorship. Reuse published capture.
Agent12 test_simulator_assets.py: actual HTML parser, imports/IDs/static route
whitelist references, no skipped/fake browser checks. Actual browser proof
separate, do not claim these static checks prove runtime UI.
Agent13 docs/local-simulator.md: install-free commands, modes, keyboard/help,
frozen provenance, semantics/limits, no empirical result recalculation.
Agent15 simulator_client.py: Python urllib CLI --url(local8765 default),
subcommands catalog, mission --point-km X Y [--bases9|25] [--wind-mps X Y]
[--offline-base N], replay --case ID --season N. Merge mission defaults from
GET catalog. Print strict JSON, HTTP errors exit2 no traceback. No math/models.
No arbitrary external URLs: require127.0.0.1/localhost HTTP, no credentials.

## Non-Goals And Verification

No new scientific findings, network optimization, real-flight control, detector
integration, hardware data, accounts, database, cloud deployment or dependencies.
No audits disguised as feature work. No changes to prior frozen/source models.
Lead owns scientific engine/data/test authorship; agents implement only owned
feature files. No agent commits/pushes, installs, deletes or forks model APIs.
Narrow checks during build; one final full software gate after integration.
Real browser screenshots desktop/mobile and non-mocked API checks required.

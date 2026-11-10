# Mission Lab: Saved Sessions And Captured Comparison

## Goal And Non-Goals

Build two bounded capabilities from reviewed research proposals: restore local
sessions without trusting saved results, and inspect a healthy/outage season on
one synchronized clock. Existing scientific logic, protocols and frozen files
stay unchanged. No new metrics, simulations, endpoints, datasets, packages,
flight integration or external requests. Research reports are not specifications.

## Tests Before Implementation

1. Mission session round trip preserves all 8 input fields and 4 source hashes;
   restoration issues a fresh POST /api/mission, never uses a stored response.
2. Replay session round trip preserves case, integer season and comparison flag;
   restoration uses GET replay and the exact saved study manifest fingerprint.
3. Reject unsupported versions/modes, unknown keys, nonfinite numbers, invalid
   ranges/indices, mismatched provenance, and files larger than 65536 bytes.
   Rejected import changes zero form/state/map values and makes zero API calls.
4. Comparison selection gives exactly 1 healthy and 1 outage case for identical
   n_bases and wind_east_mps. Unknown/ambiguous/missing partners fail visibly.
5. Lead pairing helper rejects mismatched manifest/season/domain/duration/cases,
   base geometry, alert index/time/coordinates/real flags. Null responses remain
   unreachable, not zero. No counts, rates, intervals or differences computed.
6. A real same-season healthy/outage pair renders 2 maps and exactly 1 playback
   clock. At time0 show 0 future alerts; at season end show each captured stream.
   Selecting either map selects the same original alert in both panes.
7. All DOM IDs remain unique with main, healthy and outage maps mounted.
8. Latest-request tokens prevent a slow old partner response from replacing a
   new case/season or re-enabling comparison after its checkbox is cleared.
9. Export while comparison is ready contains both actual complete received
   replay payloads and the manifest fingerprint. Export/save disabled pending
   new results; failed fetches never create fake pairs or success states.
10. Real browser at1440x1000 and390x844: save, change, restore each session mode;
    reject one modified hash without changing UI; compare, play/pause/scrub,
    select both panes, switch cases/modes; no page/console/network errors or
    horizontal overflow. Deliberately bypass one provenance/pair guard and
    prove its real assertion fails. One final Python gate after integration.
11. A successful HTTP response with changed model hashes or study manifest
    publishes 0 new results and enables 0 successful downloads. Reject replay
    case/season echoes that differ from the request. Valid responses still work.
12. A restore callback failure yields 1 visible import error and 0 unhandled
    errors. A slow older file read cannot override a newer selected session.
13. Startup preserves exactly 1 authoritative default mission POST and shows
    its result. Restore request counts start after initial loading settles;
    each restore adds only its own request(s), no intermediate default request.

## Ownership

Lead owns this contract, comparison_data.js and its data-alignment tests.
Six free-model workers edit isolated source copies, never the original repo:

1. Session component: simulator_web/session.js only.
2. Comparison component: simulator_web/comparison.js only.
3. Map support: simulator_web/map.js only.
4. App integration: simulator_web/app.js only.
5. Shell/styles/assets: simulator_web/index.html, styles.css;
   simulator_server.py STATIC_FILES only; test_simulator_assets.py whitelist only.
6. Tests/docs: simulator_web/tests/session.test.mjs; README.md Mission Lab
   section only; docs/local-simulator.md only.

No worker modifies numerical sources, protocols, captures or another scope.
No worker runs installs, shell/MCP probes, network, nested agents or full gates.
Use direct read/write tools in supplied local source workspace. Write report.md
with actual changed files and explicit untested status; do not claim test passes.
Integration and verification run separately against the actual combined code.

## Session Data Contract

Pure exports in session.js, no imports:

- makeSession(snapshot,catalog,{comparison=false}={}) -> validated plain object.
- parseSession(text,catalog) -> validated plain object, throws Error on failure.
- createSessionPanel(container,{onRestore}) -> component described below.

Session object has exactly kind,schema_version,mode,inputs,comparison,provenance:

    {
      kind:"wildfire-mission-lab-session", schema_version:1,
      mode:"mission"|"replay", inputs:{...}, comparison:false|true,
      provenance:{source_sha256:{...}} // mission only
      // replay provenance is {study_manifest_sha256:"..."} instead
    }

makeSession receives the existing export snapshot shape {mode,inputs,result,
source_provenance}; use the successful result's echoed inputs (mission), or
result.case_id/season (replay), not currently edited/unconfirmed form values.
Require result and its actual provenance to match catalog before saving.
Mission comparison must be false. Unknown keys at every schema level rejected.

Mission input keys exactly match catalog.defaults. Validate using catalog's
layouts, domain_side_km and parameter_limits, not hardcoded scientific limits:
integer n_bases in layouts, offline_base null or valid original id, point and
wind vectors exactly2 finite numbers, scalar finite bounds from metadata.
Replay inputs exactly case_id,season: existing catalog case and integer season
in [0,study.heldout_seasons). Source-hash objects compare exact keys and values,
independent of order. Both catalog and received fingerprints must be nonempty
SHA-256 hex strings; the source-hash map must contain at least 1 entry.
Replay manifest must equal catalog.study.manifest_sha256.
Numbers are numbers, never bool/string coercion. No supplied results are loaded.

parseSession rejects text longer than65536 characters before JSON parsing;
the UI additionally rejects File.size >65536 bytes before File.text(). No
eval, storage, uploads, auto-fetch, permission request or override-stale option.
Use native JSON.parse semantics; do not claim a reviver detects duplicate keys.

Panel API: setCatalog(catalog),setSnapshot(snapshot,{comparison=false}={}),
setBusy(bool),destroy(). Create Save session button plus labelled local JSON
file input and accessible status/error. Save disabled without valid successful
snapshot or while busy. Import calls onRestore(session) only AFTER complete
validation. Its message is "Session accepted; requesting fresh local results",
not a claim of successful recomputation. App owns request completion messages.
Use Blob/objectURL explicit-click download and cleanup, filename
wildfire-session-{mode}-{UTC}.json. New IDs use session- prefix.

## Comparison Data Contract (Lead)

comparison_data.js has no imports and exports:

- comparisonCases(catalog,caseId) -> {healthy,outage} case descriptors.
- pairReplays(catalog,first,second) -> {healthy,outage,cases}.

Choose roles from matching catalog n_bases/wind_east_mps, not case-id parsing.
Validate complete received payload alignment before displaying a pair. No
scientific computation, approximate matching or joining unrelated alert streams.

## Map Support Contract

Preserve createMap API, add optional idPrefix in factory options, default
"mission-map". Title/description IDs and aria references use this prefix.
Comparison instances use "comparison-healthy" and "comparison-outage".
No other DOM IDs added. Main map remains single-alert/replay compatible.

view.outcome_markers true enables captured outcome styling only in comparison.
Use recorded status classes, non-color cues (e.g. cross for unreachable,
dashed outline for late) and aria labels. Preserve real/false shape distinction,
selection and onAlert(index). Never fabricate routes or dispatch assignments.

## Comparison Component Contract

comparison.js imports createMap from ./map.js only. Export
createComparisonPanel(controlsContainer,mapContainer,{onToggle,onAlert}) with
setEnabled(bool),setPending(bool),render(pair|null,frame|null),showError(message),
destroy(). Create checkbox with label "Compare healthy / outage", status/error,
and a wrapper containing 2 labelled map figures. Programmatic setEnabled never
fires onToggle. Checkbox remains cancellable during a request.

Use only already validated pair objects. Render each case's own captured
alerts with alert_s <= frame.current_s; shared selected_alert_index. Each pane
shows its actual case id and selected captured status/response, with null shown
as Unreachable, never0. No selection shows a prompt; a future selected alert
is not displayed as already arrived. No derived rates/deltas or invented routes.
Maps pass mode:"replay",outcome_markers:true,point_km:null,candidates:[],
selected_base_id:null, and each payload's bases. Reuse the one existing main
replayPanel for transport; never instantiate a second playback controller.
IDs/classes comparison-. Two maps stack on mobile; overflow stays contained.

## App Integration Contract

Import session/comparison modules and lead helpers. Add store fields
comparisonEnabled:false,comparisonPair:null; dedicated comparisonToken.
Wrap main createMap in its own div inside existing #map, then comparison maps
can be siblings; hide primary map only while enabled valid pair is rendered.
Comparison controls append to existing #replay-controls (hidden in mission).
Never show comparison maps in mission mode.

On toggle true and a successful replay: comparisonCases chooses partner; reuse
the current complete payload, fetch only the partner at the same season, then
pairReplays validates them. On case/season/mode change invalidate comparisonToken
and clear pair before request. On toggle false invalidate and clear immediately.
Capture replayToken AND comparisonToken around partner fetch; ignore stale
responses. Pending/failure stays visibly labelled, no stale pair reuse.
When comparison is requested before replay arrives, load after primary success.
One replay frame/selection renders both panes. Both map onAlert callbacks use
the existing replayPanel.selectAlert, preserving the one clock.

Maintain a current received export snapshot, clearing it synchronously on new
requests. Ready comparison export keeps mode:"replay" and result:primary,
adds comparison:{healthy:actualPayload,outage:actualPayload}. Existing export
module needs no changes. Session setSnapshot gets comparison:true only once
validated pair is ready. Session files never store results.

Before storing/rendering each primary response, construct its actual snapshot
and call makeSession(snapshot,catalog). This binds the received source or study
fingerprint to startup metadata even if the local server restarted. A mismatch
uses the failure path and requires page refresh, never silently updates source
generation. Partner responses still pass pairReplays. Guard replay case/season
echoes against the requested values before publication.

Session onRestore is called only after parse validation. For mission restore,
set comparison off, apply echoed inputs and request a fresh immediate mission.
For replay restore, validate comparisonCases first when comparison is true,
then set mode/input selections and issue one fresh primary request, followed by
the partner if requested. Do not transiently load the default season/case first.
Preserve mission debounce, stale-response guards and accessible error handling.

## Shell, Tests And Docs

Add #session section near existing export; keep current IDs and app.js entry.
Static whitelist adds only session.js,comparison.js,comparison_data.js.
Do not expose test files or general filesystem paths. Existing asset test's
expected whitelist updates by the same3 names, no test weakening.
Use existing Geist/neutral/006bff design, visible focus, reduced motion and
prefixed classes. Do not add remote fonts/libraries or rewrite existing styles.

Native Node tests use node:test and node:assert/strict, loading standalone pure
modules through a data URL so no package.json/type/dependency change is needed.
Node tests are separate from Python discovery; document the exact optional
developer command. Test fixtures are mechanics checks, not empirical evidence.
Docs distinguish input sessions from complete result exports, fail-closed source
matching, one shared replay clock and synthetic-only evidence. No new finding.

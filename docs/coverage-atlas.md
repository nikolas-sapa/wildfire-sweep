# Coverage Atlas

The Coverage Atlas is a loopback-only, read-only explorer for one captured
spatial-coverage study. It serves captured grids and summaries from the
lead-authored `2026-11-10-coverage-atlas-v1` capture and never recomputes
them. It requires the repository's existing `.venv`; it installs no packages,
loads no remote assets, and makes no automatic external requests.

Coverage here means the fraction of equal-area cell centers an initially idle
network reaches within 900 seconds. It is not a season success rate,
ignition-risk estimate, confidence interval, forecast, detector result,
geographic map, or flight-control system.

## Start the local server

From the repository root:

```sh
.venv/bin/python simulator_server.py
```

Open [http://127.0.0.1:8765/coverage/](http://127.0.0.1:8765/coverage/). The
server binds only to `127.0.0.1`. Stop it with Ctrl+C. To choose a different
local port:

```sh
.venv/bin/python simulator_server.py --port 8766
```

The browser and CLI must use the same local port. `/coverage` and `/coverage/`
serve the atlas page; `/coverage/<file>` serves only a fixed allowlist of
atlas files (`index.html`, `styles.css`, `app.js`, `map.js`, `controls.js`,
`table.js`, `details.js`, `comparison.js`, `export.js`, `session.js`,
`api.js`, `state.js`, `legend.js`, `data_contract.js`). Everything else,
including atlas tests, raw capture archives, path traversal and directory
listings, returns not found. The atlas adds exactly two GET endpoints,
`/api/coverage/catalog` and `/api/coverage?case=<id>`; there is no POST,
generation or filesystem-path parameter. The Mission Lab at `/` is unchanged.

## Grid and outcome categories

Each case is an `80 x 80` grid of 6400 equal-area cell centers on the same
synthetic square domain as the rest of the model (area 3,808 km2; side length
is reported as `domain_side_km`). The grid is `y`-major/`x`-fast with north at positive
`y`; cell `index = row * grid_n + column`. The map draws captured cell
outcomes only, with no interpolation:

| Outcome | Meaning | Cue |
| --- | --- | --- |
| `timely` | An available base arrives within 900 seconds including launch latency | solid green |
| `late` | Served, but arrival exceeds 900 seconds | amber diagonal hatch |
| `unreachable` | No eligible base completes the round trip within the usable battery budget | gray dots |
| `weather_closed` | The case wind exceeds the 12 m/s model weather limit, so every cell is closed | dark crosshatch |

Every cell center is a separate hypothetical alert: the whole network starts
idle, one alert is evaluated, and there is no queueing or contention between
cells. Under the case's fixed wind, a base is eligible when outbound flight
time plus dwell time plus return flight time is at most
`endurance_min * 60 * (1 - reserve_fraction)`. Launch latency is added only
to arrival time for the 900-second timely threshold; it is not part of the
battery budget. Unserved cells carry no response time and no base; the
interface shows them as unavailable, never as zero. Served cells
record the original base identifier of the earliest-arriving eligible base;
outage cases keep the same original identifiers with unavailable sites marked
offline.

Click a cell to inspect it, or focus the map and move one cell with the arrow
keys, jump to the first or last cell with Home/End, and select with Enter.
The selected cell is shared across the map, paired panes and the details
panel, which also states the exact case inputs and model limits.

## Case selection, filters and paired view

The controls offer a primary case selector plus filters on the stored case
metadata: `n_bases`, `profile`, `wind_speed_mps`, `heading_deg` and outage
count. Case identifiers are opaque; filter the list rather than typing IDs.
The table shows stored summary rows only (the four outcome counts and the two
stored fractions); it computes nothing. Changing filters keeps the current
selection and labels it outside current filters when needed. The inventory
continues to show all captured cases; filters do not choose a replacement case.

The comparison selector is optional. Choosing a partner issues its own case
request and displays both captures side by side. Both panes must carry the
same capture fingerprint, grid size and domain before they render; a mismatch
shows an error instead of a pair. The comparison computes no differences or
rates; it shows captured outcomes only. Toggling comparison off clears the
secondary pane, and only the latest response is ever published, so a slower
earlier request cannot overwrite a newer selection.

## Scenario inventory

The captured study has exactly 388 cases, and the atlas shows nothing beyond
them. Per layout (9 and 25 bases, original site identifiers) and each of
eight 12 m/s headings (the direction toward which wind blows, east=0,
north=90):

- the healthy reference network and every single-site outage;
- two selected outage pairs only, sites [0, 1] and [0, center site]; these
  are not exhaustive and are not worst-pair optimization;
- four healthy stress profiles: endurance 36 min, reserve 0.35, launch
  latency 180 s, and all three combined, against the reference 46 min,
  0.25 and 60 s.

Plus one healthy calm case and one healthy 13 m/s weather-closed case per
layout. There are no other winds, headings, layouts, outage counts or stress
combinations, and no claim of all possible scenarios.

## Provenance and failure behavior

The server reads the capture at
`research_results/2026-11-10-coverage-atlas-v1` by default. A capture
directory contains exactly `scenarios.json`, `summary.csv`, `coverage.npz`
and `manifest.json`. The manifest records the study ID, grid size, domain,
900 s threshold, outcome codes, per-source and per-file SHA-256 digests, the
grid convention and the limitation list. Its own SHA-256, shown as
`capture_sha256` in the catalog and every payload, ties the displayed data to
those verified bytes.

The loader verifies manifest fields, per-file checksums, source-generation
identity, scenario registration, summary/array consistency and grid
coordinates before serving anything. If the capture is missing, corrupt or
tampered with, the atlas endpoints return a JSON 503 error and the page shows
an error state; an invalid query or unknown case ID returns 400. Nothing
generates a capture automatically: the UI, CLI and renderer never run the
scientific code, there is no fixture or fallback data, and a failed case
request keeps the last good map while clearing any stale export. If no
capture exists, the directory is absent rather than silently filled; the
lead-authored writer `coverage_capture.py --output NEW_DIR` is the only
generation path and is a separate offline step.

## Saved sessions and full export

The session panel saves and restores a small JSON file containing only the
selection and provenance:

```json
{"kind": "wildfire-coverage-session", "schema_version": 1,
 "capture_sha256": "...", "case_id": "...",
 "compare_case_id": null, "selected_cell_index": null}
```

It never contains results. Restoring validates the file against the running
catalog: the fingerprint must match exactly, both case IDs must exist, the
cell index must be in range, and the file must stay within the 65536-character
limit. Any mismatch fails closed: no request is sent and nothing changes.
A valid restore requests exactly the saved case or pair, fresh from the
server.

The export button is different: it downloads the complete received JSON
payloads (primary plus secondary when a validated pair is shown) as
`wildfire-coverage-<case_id>.json`. It stays disabled until a successful
validated response exists and clears on failed or superseded requests. The
session file stores where you were; the export stores what the server sent.

## Local CLI and renderer

The coverage client accepts only HTTP URLs for `127.0.0.1` or `localhost`,
follows no redirects, prints JSON to stdout and exits 2 with a short stderr
message on error:

```sh
.venv/bin/python coverage_client.py catalog
.venv/bin/python coverage_client.py case --case CASE_ID
.venv/bin/python coverage_client.py --base-url http://127.0.0.1:8766 catalog
```

`CASE_ID` is an identifier returned by the `catalog` command.

The renderer turns an existing capture directory into a Markdown inventory of
stored scenario inputs, counts, fractions, provenance and limitations:

```sh
.venv/bin/python render_coverage.py --capture research_results/2026-11-10-coverage-atlas-v1 --output docs/coverage-atlas-table.md
```

The output path must be new; the command refuses to overwrite and leaves
existing files untouched on failure. It reads the capture through the same
verified loader and recomputes nothing.

## Optional Node checks

The pure browser modules carry mechanics tests under `coverage_web/tests/`.
They are separate from the Python suite and use the installed native Node.js
test runner; nothing is installed or changed:

```sh
node --test coverage_web/tests/*.test.mjs
```

These checks exercise validation, session and state mechanics against small
inputs. They are not empirical evidence and do not run the model.

## Assumptions and limits

- Cell centers are an equal-area spatial approximation, not a season
  response rate; resolution differences across grid sizes are numerical
  sensitivity, not confidence intervals or convergence guarantees.
- Every cell is an independent single alert with the full network initially
  idle; there is no queueing, fleet contention or upstream detector latency.
- The network is the fixed 9- or 25-base synthetic layout with hypothetical
  aircraft; outage cases mark original sites unavailable and do not imply
  observed failure probabilities or real siting.
- Weather is one fixed uniform wind vector per case above the flat domain;
  there is no terrain, time-varying weather or forecast availability, and the
  12 m/s limit is a model assumption.
- The map is synthetic model space, not geography; base markers use
  source-verified layout coordinates and no trajectories exist.
- Nothing here is field-validated. It establishes no detector accuracy,
  real-world performance, flight approval or operating advice, and differs
  from the captured season experiments explored by Mission Lab replay, which
  include fleet contention.

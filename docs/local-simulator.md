# Local Mission Lab

Mission Lab is a loopback-only interface for exploring the existing synthetic
model and reading the frozen resilience capture. It requires the repository's
existing `.venv`; it installs no packages, loads no remote assets, and makes no
automatic external requests. Research links open only when selected.

## Start the interface

From the repository root:

```sh
.venv/bin/python simulator_server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The server binds only to
`127.0.0.1`. Stop it with Ctrl+C.

To choose a different local port:

```sh
.venv/bin/python simulator_server.py --port 8766
```

The browser and CLI must use the same local port.

## Mission sandbox

Mission mode evaluates one alert with initially idle drones. Set the network
layout, unavailable base, alert location, wind components, and advanced aircraft
or launch assumptions. The map is synthetic model space, not a geographic map.
Click or drag the target, or Tab to the map and use arrow keys to move it by
0.5 km. Tab and Shift+Tab move between controls; Enter or Space activates the
focused button. The result comes from the local mission endpoint; the interface
does not port the flight model into JavaScript.

This is not a season-wide rate. It has no queueing, upstream detector latency,
field validation, live alert source, or flight control. An unavailable base uses
its original site identifier; the layout change resets that choice.

## Frozen replay and evidence

Replay mode reads a selected case and held-out season from the captured
`research_results/2026-11-09-resilience` study. It does not run a generator,
dispatcher, or simulator. The saved season includes fleet contention, but the
capture contains no base assignments or flight trajectories. The replay map
shows captured alert locations and outcomes, not assigned routes.

Choose a case and season, then use Play/Pause or the season-time slider. Focus
the slider and use left/right arrows to scrub. Select an alert in the event
list to focus it on the map. Evidence tables display captured summary and
contrast rows directly. Monte Carlo intervals are conditional on the modeled
inputs; they are not field uncertainty.

Mission changes never update replay data or the frozen evidence. Export uses an
explicit download action and includes the complete received result, inputs, and
source provenance.

## Saved sessions

The session panel can save the current inputs to a local JSON file and load
such a file later. A saved session is a saved-input file: it records the mode,
the validated inputs, whether comparison was requested, and provenance hashes.
It never contains received results. This differs from the snapshot export,
which downloads the complete received result.

Restoring a session never reuses stored output. A mission session issues a
fresh `POST /api/mission` with the saved inputs; a replay session issues fresh
`GET /api/replay` requests for the saved case and season. The file's recorded
provenance must match the running catalog exactly before anything is applied:
the source hashes for a mission session, the study manifest fingerprint for a
replay session. Any mismatch, unsupported version or mode, unknown key,
out-of-range value, or file over 65536 bytes fails closed: the form, map and
state stay unchanged and no request is sent.

## Captured comparison

In replay mode, the "Compare healthy / outage" control pairs the selected case
with the single catalog partner that shares its layout and wind. Both panes
replay the same captured season on one shared playback clock; selecting an
alert in either pane selects the same original alert in both. A missing or
ambiguous partner, and any payload that fails alignment checks, shows an error
instead of a fabricated pair. Null responses display as unreachable, never as
zero. The comparison derives no new rates or differences; it shows captured
outcomes only.

## Local CLI

The client accepts only HTTP URLs for `127.0.0.1` or `localhost`.

```sh
.venv/bin/python simulator_client.py catalog
.venv/bin/python simulator_client.py mission --point-km 10 10
.venv/bin/python simulator_client.py mission --point-km 10 10 --bases 25 --wind-mps 8 0 --offline-base 0
.venv/bin/python simulator_client.py replay --case CASE_ID --season 0
```

`CASE_ID` is a case identifier returned by the `catalog` command. Mission
defaults come from that catalog; command-line options override only the values
provided. Successful commands print JSON. Local HTTP errors exit with status 2
and a short message.

## Optional Node checks

The pure browser modules carry mechanics tests under `simulator_web/tests/`.
They are separate from the Python suite and use the installed native Node.js
test runner. Verified locally with Node.js v26.11.1; nothing is installed or
changed:

```sh
node --test simulator_web/tests/
```

These checks exercise validation and pairing mechanics against small fixtures.
They are not empirical evidence and do not run the model.

## Scope and limits

The sandbox is a single-alert tool; it is not evidence of season-wide service.
Replay is a read-only view of saved season data and does not add routes,
assignments, rates, or confidence intervals. Neither mode establishes detector
accuracy, forecast weather availability, field performance, flight approval,
or operating advice.

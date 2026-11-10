# Coverage Atlas integration acceptance

Test plan precedes implementation of integration fixes. Supplements the frozen
build contract after independent review of the isolated implementations.

## Non-goals

- No changes to scientific configuration, model, dispatch, scenario registry,
  capture format or frozen numerical results.
- No rerun of a frozen study or overwrite of any previous render.
- No field-performance, detector-accuracy or forecast claims.
- No authentication system, cloud deployment, flight control or dependencies.
- No new scientific metrics, inferred routes or browser-side model evaluation.

## Named acceptance checks

1. Warm-reader integrity: catalog and case succeed before corruption; both
   reject missing/changed capture components after a successful warm read.
   HTTP endpoints return exactly 503, never cached 200. Restoring identical
   bytes restores 200 and identical payloads.
2. Snapshot consistency: each public adapter call uses exactly one verified
   loaded snapshot for metadata and cells. Caller mutation changes zero later
   outputs. Concurrent calls do not mix fingerprints with another snapshot.
3. Real HTTP/CLI: two fixture cases with 16 cells each match stored descriptors,
   nested summaries, coordinates, outcome codes and unserved nulls. Unknown or
   duplicate selectors return 400; non-GET methods return 405.
4. Legacy isolation: absent atlas capture leaves Mission Lab HTML, catalog and
   mission POST working. Existing scientific sources and captures change zero
   bytes.
5. Browser layouts: fresh server, desktop 1440px and mobile 390px; zero console
   errors, zero automatic external requests and zero page-level horizontal
   overflow. Inventory may scroll inside its own wrapper.
6. Map geometry: at DPR 1 and 2, an 80x80 grid selects indices 6320, 6399, 0,
   79 at top-left, top-right, bottom-left, bottom-right, and 3160 at geometric
   center. CSS borders must not distort bitmap/pointer coordinate mapping.
7. Keyboard: Home plus Enter selects 0; End plus Enter selects 6399. Arrow
   movements clamp at row/column boundaries; up moves toward positive model y.
8. Pairing: only two validated payloads may hide the single-map view. Both panes
   share one selected index. Clearing comparison leaves one active map. An old
   request cannot replace the newest requested case.
9. Failed-primary comparison: after a primary request fails, selecting a
   partner must not publish a successful pair against the stale old primary.
   Download controls remain disabled until a new successful selection.
10. Session completion: restore awaits all requested fresh payloads. One-case
    restore sends exactly one case GET; pair restore exactly two. It sends zero
    extra catalog requests. A failed request never announces successful restore.
11. Thin sessions: exactly six keys, no cells, summaries or payloads. Wrong
    fingerprint, unknown ID, index 6400 and files over 65536 bytes reject before
    issuing any case request. Valid save/restore preserves selection and index.
12. Snapshot export: parsed downloaded JSON deep-equals the actual received
    primary/secondary payloads. Zero derived result fields. Failed/pending
    requests disable export and session saving.
13. Semantic DOM: all nine mount IDs exist once; every aria-labelledby target
    survives component mounting. Zero loading placeholders remain after load.
    The selected offline site is identifiable in visible option text.
14. Capture-only rendering: Markdown uses verified stored values and metadata;
    no dispatch/study invocation. Exclusive output creation never replaces an
    existing file. No direct deletions. PNGs are copied byte-identically from
    the accepted v2 render, not regenerated.
15. Automated gates: all Python tests and both native Node test directories
    pass without silent skips. Three historical checks and render_study help
    pass. Hosted CI includes mandatory Node 22 checks for both directories.
16. Failure controls: reintroducing warm caching must fail the warm-integrity
    test; bypassing source-fingerprint equality must fail its Node regression.
    Record assertion failures, not import/setup failures, as red evidence.

## Integration decisions

- Revalidate the capture on every public reader call, no permanent cache.
  Pass its request-local snapshot explicitly to metadata serialization.
- App-owned child mount slots preserve outer section headings and remove
  initial loading placeholders. Visibility stays on the outer sections.
- Loaders return settled success booleans; session restore awaits them and
  rejects failures. Ordinary selection callbacks retain handled errors.
- Keep comparison clearing available when filters yield zero candidates.
  Retain current selected cases and label them outside current filters.
- Reuse the declared local API, store and component interfaces. Do not add
  global table-filter architecture or broaden the scenario matrix.
- Match the existing Geist presentation. Amber is warning/status only.
  Move constant map/legend layout styling into the shared CSS.

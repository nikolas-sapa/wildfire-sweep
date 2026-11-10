import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const CAPTURE_SHA256 = "f".repeat(64);
const SOURCE_SHA256 = {
  "coverage_scenarios.py": "a".repeat(64),
  "coverage_engine.py": "b".repeat(64),
  "coverage_capture.py": "c".repeat(64),
};
const CASE_A = "c9-ref-east";
const CASE_B = "c9-out0-east";
const SESSION_KEYS = [
  "capture_sha256", "case_id", "compare_case_id", "kind", "schema_version",
  "selected_cell_index",
];

const contractUrl = `data:text/javascript;base64,${
  Buffer.from(readFileSync(new URL("../data_contract.js", import.meta.url), "utf8"))
    .toString("base64")
}`;
const sessionSource = readFileSync(new URL("../session.js", import.meta.url), "utf8")
  .replace(
    /(from\s*|import\s*)(["'])\.\/data_contract\.js\2/g,
    (match, prefix) => `${prefix}${JSON.stringify(contractUrl)}`,
  );
const sessionModule = await import(
  `data:text/javascript;base64,${Buffer.from(sessionSource).toString("base64")}`,
);
const { makeSession, parseSession } = sessionModule;
const { validateCatalog, validateCase } = await import(contractUrl);

function layout(count, side) {
  const columns = Math.ceil(Math.sqrt(count));
  return Array.from({ length: count }, (_, index) => ({
    id: index,
    x_km: ((index % columns) + 1) * side / (columns + 1),
    y_km: (Math.floor(index / columns) + 1) * side / (columns + 1),
    available: true,
  }));
}

function quota(total, weights) {
  const parts = weights.map((weight) => Math.floor(total * weight));
  parts.push(total - parts[0] - parts[1] - parts[2]);
  return {
    timely: parts[0], late: parts[1], unreachable: parts[2], weather: parts[3],
  };
}

function descriptor(caseId, offlineBases, counts, gridN) {
  const total = gridN * gridN;
  return {
    case_id: caseId,
    n_bases: 9,
    wind_mps: [12, 0],
    wind_speed_mps: 12,
    heading_deg: 0,
    profile: "reference",
    offline_bases: [...offlineBases],
    airspeed_mps: 18,
    endurance_min: 46,
    reserve_fraction: 0.25,
    launch_latency_s: 60,
    summary: {
      case_id: caseId,
      unreachable_cells: counts.unreachable,
      late_cells: counts.late,
      timely_cells: counts.timely,
      weather_closed_cells: counts.weather,
      total_cells: total,
      timely_area_fraction: counts.timely / total,
      reachable_area_fraction: (counts.timely + counts.late) / total,
    },
  };
}

function cellsFor(desc, gridN, side) {
  const available = [0, 1, 2, 3].find((id) => !desc.offline_bases.includes(id));
  const plan = [
    ["timely", desc.summary.timely_cells],
    ["late", desc.summary.late_cells],
    ["unreachable", desc.summary.unreachable_cells],
    ["weather_closed", desc.summary.weather_closed_cells],
  ];
  const cells = [];
  for (const [outcome, count] of plan) {
    for (let k = 0; k < count; k += 1) {
      const index = cells.length;
      const served = outcome === "timely" || outcome === "late";
      cells.push({
        index,
        row: Math.floor(index / gridN),
        column: index % gridN,
        x_km: ((index % gridN) + 0.5) * side / gridN,
        y_km: (Math.floor(index / gridN) + 0.5) * side / gridN,
        outcome,
        response_s: served ? (outcome === "timely" ? 300 : 1200) : null,
        selected_base_id: served ? available : null,
      });
    }
  }
  return cells;
}

function payload(desc, catalog) {
  return {
    schema_version: 1,
    mode: "coverage",
    study_id: catalog.study_id,
    capture_sha256: catalog.capture_sha256,
    grid_n: catalog.grid_n,
    domain_side_km: catalog.domain_side_km,
    timely_threshold_s: catalog.timely_threshold_s,
    outcome_codes: { ...catalog.outcome_codes },
    source_sha256: { ...catalog.source_sha256 },
    grid: { ...catalog.grid },
    limitations: [...catalog.limitations],
    case: structuredClone(desc),
    bases: catalog.layouts[String(desc.n_bases)].map((item, index) => ({
      ...item,
      available: !desc.offline_bases.includes(index),
    })),
    cells: cellsFor(desc, catalog.grid_n, catalog.domain_side_km),
  };
}

function fixture({ gridN = 4, captureSha256 = CAPTURE_SHA256 } = {}) {
  const catalog = {
    schema_version: 1,
    mode: "coverage_catalog",
    study_id: "2026-11-10-coverage-atlas-v1",
    capture_sha256: captureSha256,
    grid_n: gridN,
    domain_side_km: 60,
    timely_threshold_s: 900,
    outcome_codes: { unreachable: 0, late: 1, timely: 2, weather_closed: 3 },
    source_sha256: { ...SOURCE_SHA256 },
    grid: {
      order: "y-major-x-fast", locations: "cell-centers", north: "positive-y",
    },
    limitations: [
      "Synthetic structural fixture only; not a real capture.",
      "Not field validated.",
    ],
    layouts: { "9": layout(9, 60), "25": layout(25, 60) },
    cases: [
      descriptor(CASE_A, [], quota(gridN * gridN, [0.625, 0.1875, 0.125]), gridN),
      descriptor(CASE_B, [0], quota(gridN * gridN, [0.375, 0.25, 0.3125]), gridN),
    ],
  };
  const primary = payload(catalog.cases[0], catalog);
  const secondary = payload(catalog.cases[1], catalog);
  validateCatalog(catalog);
  validateCase(primary, catalog);
  validateCase(secondary, catalog);
  return { catalog, primary, secondary };
}

function sessionFields(catalog) {
  return {
    kind: "wildfire-coverage-session",
    schema_version: 1,
    capture_sha256: catalog.capture_sha256,
    case_id: CASE_A,
    compare_case_id: null,
    selected_cell_index: null,
  };
}

test("module exposes pure session functions and the panel factory", () => {
  assert.equal(typeof makeSession, "function");
  assert.equal(typeof parseSession, "function");
  assert.equal(typeof sessionModule.createCoverageSession, "function");
});

test("single-payload session round trips case, hash and null selections", () => {
  const { catalog, primary } = fixture();
  const session = makeSession({ primary, secondary: null }, catalog);
  assert.equal(Object.getPrototypeOf(session), Object.prototype);
  assert.deepEqual(Object.keys(session).sort(), SESSION_KEYS);
  assert.equal(session.kind, "wildfire-coverage-session");
  assert.equal(session.schema_version, 1);
  assert.equal(session.capture_sha256, catalog.capture_sha256);
  assert.equal(session.case_id, CASE_A);
  assert.equal(session.compare_case_id, null);
  assert.equal(session.selected_cell_index, null);
  const parsed = parseSession(JSON.stringify(session), catalog);
  assert.equal(Object.getPrototypeOf(parsed), Object.prototype);
  assert.deepEqual(parsed, session);
});

test("two-payload session round trips both cases and selected cell", () => {
  const { catalog, primary, secondary } = fixture();
  const session = makeSession({ primary, secondary }, catalog, {
    selectedCellIndex: 15,
  });
  assert.equal(session.case_id, CASE_A);
  assert.equal(session.compare_case_id, CASE_B);
  assert.equal(session.selected_cell_index, 15);
  assert.deepEqual(parseSession(JSON.stringify(session), catalog), session);
});

test("makeSession honors only catalog-bounded cell index options", () => {
  const { catalog, primary } = fixture();
  const snapshot = { primary, secondary: null };
  for (const index of [0, 7, 15]) {
    const session = makeSession(snapshot, catalog, { selectedCellIndex: index });
    assert.equal(session.selected_cell_index, index);
  }
  assert.equal(makeSession(snapshot, catalog).selected_cell_index, null);
  assert.equal(
    makeSession(snapshot, catalog, { selectedCellIndex: null }).selected_cell_index,
    null,
  );
  for (const index of [-1, 16, 100, 1.5, "3", true, {}, NaN, Infinity]) {
    assert.throws(
      () => makeSession(snapshot, catalog, { selectedCellIndex: index }),
      String(index),
    );
  }
});

test("sessions carry thin case identity only, never received results", () => {
  const { catalog, primary, secondary } = fixture();
  for (const session of [
    makeSession({ primary, secondary: null }, catalog),
    makeSession({ primary, secondary }, catalog, { selectedCellIndex: 3 }),
  ]) {
    const text = JSON.stringify(session);
    for (const banned of [
      "cells", "bases", "summary", "result", "payload", "response_s",
      "timely_cells", "x_km", "y_km", "selected_base_id", "layouts",
      "offline_bases", "snapshot",
    ]) {
      assert.equal(text.includes(`"${banned}"`), false, banned);
    }
    assert.equal("primary" in session, false);
    assert.equal("secondary" in session, false);
    assert.equal("result" in session, false);
  }
});

test("makeSession saves only a validated received snapshot", () => {
  const { catalog, primary, secondary } = fixture();
  for (const snapshot of [
    null, undefined, {},
    { primary: null, secondary: null },
    { primary: {}, secondary: null },
    { primary: "edited", secondary: null },
    { primary, secondary: {} },
    { primary, secondary: catalog },
  ]) {
    assert.throws(() => makeSession(snapshot, catalog), String(snapshot));
  }
  const ghost = structuredClone(primary);
  ghost.case.case_id = "ghost-case";
  assert.throws(() => makeSession({ primary: ghost, secondary: null }, catalog));
  const miscounted = structuredClone(primary);
  miscounted.cells[0].outcome = "late";
  assert.throws(() => makeSession({ primary: miscounted, secondary: null }, catalog));
  const wrongHash = structuredClone(primary);
  wrongHash.capture_sha256 = "0".repeat(64);
  assert.throws(() => makeSession({ primary: wrongHash, secondary: null }, catalog));
  const wrongSource = structuredClone(primary);
  wrongSource.source_sha256["coverage_engine.py"] = "0".repeat(64);
  assert.throws(() => makeSession({ primary: wrongSource, secondary: null }, catalog));
  const ghostCompare = structuredClone(secondary);
  ghostCompare.case.case_id = "ghost-compare";
  assert.throws(() => makeSession({ primary, secondary: ghostCompare }, catalog));
  const mismatched = structuredClone(secondary);
  mismatched.capture_sha256 = "0".repeat(64);
  assert.throws(() => makeSession({ primary, secondary: mismatched }, catalog));
  const wrongMode = structuredClone(secondary);
  wrongMode.mode = "coverage_catalog";
  assert.throws(() => makeSession({ primary, secondary: wrongMode }, catalog));
  assert.throws(() => makeSession({ primary, secondary: null }));
  assert.throws(() => makeSession({ primary, secondary: null }, {}));
});

test("parseSession enforces exact keys, kind and version", () => {
  const { catalog } = fixture();
  for (const change of [
    (s) => { s.kind = "wildfire-session"; },
    (s) => { s.kind = "wildfire-coverage-sessions"; },
    (s) => { s.kind = "WILDFIRE-COVERAGE-SESSION"; },
    (s) => { s.schema_version = 2; },
    (s) => { s.schema_version = "1"; },
    (s) => { s.schema_version = null; },
    (s) => { s.extra = true; },
    (s) => { s.results = []; },
    (s) => { s.cells = []; },
    (s) => { s.payload = {}; },
    (s) => { s.snapshot = {}; },
    (s) => { delete s.kind; },
    (s) => { delete s.schema_version; },
    (s) => { delete s.capture_sha256; },
    (s) => { delete s.case_id; },
    (s) => { delete s.compare_case_id; },
    (s) => { delete s.selected_cell_index; },
  ]) {
    const session = sessionFields(catalog);
    change(session);
    assert.throws(
      () => parseSession(JSON.stringify(session), catalog),
      change.toString(),
    );
  }
});

test("malformed text, non-objects and missing catalog reject", () => {
  const { catalog } = fixture();
  for (const text of [
    "", "{", '{"kind":', "[]", "5", "null", "true", '"session"', "  ",
  ]) {
    assert.throws(() => parseSession(text, catalog), text);
  }
  for (const value of [null, undefined, 42, {}, []]) {
    assert.throws(() => parseSession(value, catalog), String(value));
  }
  const text = JSON.stringify(sessionFields(catalog));
  assert.throws(() => parseSession(text));
  assert.throws(() => parseSession(text, {}));
  assert.throws(() => parseSession(text, null));
});

test("session text longer than 65536 characters rejects", () => {
  const { catalog } = fixture();
  const session = sessionFields(catalog);
  const text = JSON.stringify(session);
  const padded = text + " ".repeat(65536 - text.length);
  assert.equal(padded.length, 65536);
  assert.deepEqual(parseSession(padded, catalog), session);
  assert.throws(() => parseSession(`${padded} `, catalog));
  assert.throws(() => parseSession(" ".repeat(70000), catalog));
});

test("capture hash must equal the catalog fingerprint exactly", () => {
  const { catalog } = fixture();
  for (const hash of [
    "", "0", "abc", "g".repeat(64), "A".repeat(64), "0".repeat(64),
    "1".repeat(64), 42, null, true, {}, [],
  ]) {
    const session = sessionFields(catalog);
    session.capture_sha256 = hash;
    assert.throws(
      () => parseSession(JSON.stringify(session), catalog),
      String(hash),
    );
  }
  assert.equal(sessionFields(catalog).capture_sha256, "f".repeat(64));
  const other = fixture({ captureSha256: "9".repeat(64) }).catalog;
  assert.throws(
    () => parseSession(JSON.stringify(sessionFields(catalog)), other),
  );
});

test("case and compare identifiers must exist in the catalog", () => {
  const { catalog } = fixture();
  for (const change of [
    (s) => { s.case_id = "ghost-case"; },
    (s) => { s.case_id = CASE_B.toUpperCase(); },
    (s) => { s.case_id = 42; },
    (s) => { s.case_id = null; },
    (s) => { s.case_id = true; },
    (s) => { s.case_id = {}; },
    (s) => { s.case_id = ""; },
    (s) => { s.compare_case_id = "ghost-case"; },
    (s) => { s.compare_case_id = 42; },
    (s) => { s.compare_case_id = true; },
    (s) => { s.compare_case_id = {}; },
    (s) => { s.compare_case_id = ""; },
  ]) {
    const session = sessionFields(catalog);
    change(session);
    assert.throws(
      () => parseSession(JSON.stringify(session), catalog),
      change.toString(),
    );
  }
  const paired = sessionFields(catalog);
  paired.compare_case_id = CASE_B;
  assert.deepEqual(parseSession(JSON.stringify(paired), catalog), paired);
});

test("selected index accepts null or an integer inside the grid", () => {
  const { catalog } = fixture();
  for (const index of [null, 0, 8, 15]) {
    const session = sessionFields(catalog);
    session.selected_cell_index = index;
    assert.deepEqual(parseSession(JSON.stringify(session), catalog), session);
  }
  for (const index of [-1, 16, 100, 1.5, "3", true, {}, []]) {
    const session = sessionFields(catalog);
    session.selected_cell_index = index;
    assert.throws(
      () => parseSession(JSON.stringify(session), catalog),
      String(index),
    );
  }
});

test("index bounds derive from the catalog grid size", () => {
  const small = fixture({ gridN: 4 }).catalog;
  const large = fixture({ gridN: 9 }).catalog;
  const session = sessionFields(large);
  session.selected_cell_index = 40;
  assert.deepEqual(parseSession(JSON.stringify(session), large), session);
  assert.throws(() => parseSession(JSON.stringify(session), small));
});

test("duplicate keys keep native JSON last-wins semantics", () => {
  const { catalog } = fixture();
  const session = sessionFields(catalog);
  const entries = Object.entries(session).map(
    ([key, value]) => `${JSON.stringify(key)}:${JSON.stringify(value)}`,
  );
  const valid = `{${entries.join(",")}}`;
  assert.deepEqual(parseSession(valid, catalog), session);
  const ghostFirst = valid.replace(
    `"case_id":${JSON.stringify(CASE_A)}`,
    `"case_id":"ghost","case_id":${JSON.stringify(CASE_A)}`,
  );
  assert.deepEqual(parseSession(ghostFirst, catalog), session);
  const ghostLast = valid.replace(
    `"case_id":${JSON.stringify(CASE_A)}`,
    `"case_id":${JSON.stringify(CASE_A)},"case_id":"ghost"`,
  );
  assert.throws(() => parseSession(ghostLast, catalog));
});

test("returned sessions are fresh objects isolated from callers", () => {
  const { catalog, primary, secondary } = fixture();
  const snapshot = { primary, secondary };
  const first = makeSession(snapshot, catalog, { selectedCellIndex: 4 });
  const second = makeSession(snapshot, catalog, { selectedCellIndex: 4 });
  assert.notStrictEqual(first, second);
  assert.notStrictEqual(first, snapshot);
  assert.deepEqual(first, second);
  first.case_id = "mutated";
  first.selected_cell_index = 99;
  assert.equal(second.case_id, CASE_A);
  assert.equal(second.selected_cell_index, 4);
  assert.equal(primary.case.case_id, CASE_A);
  assert.equal(secondary.case.case_id, CASE_B);
  const parsedA = parseSession(JSON.stringify(second), catalog);
  const parsedB = parseSession(JSON.stringify(second), catalog);
  assert.notStrictEqual(parsedA, parsedB);
  assert.deepEqual(parsedA, parsedB);
  parsedA.case_id = "mutated";
  assert.equal(parsedB.case_id, CASE_A);
  assert.equal(catalog.cases[0].case_id, CASE_A);
});

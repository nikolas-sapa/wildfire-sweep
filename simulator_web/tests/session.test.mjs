import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../session.js", import.meta.url), "utf8");
const { makeSession, parseSession } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

const HASHES = {
  "simulator_engine.py": "a".repeat(64),
  "simulator_protocol.json": "b".repeat(64),
  "research.py": "c".repeat(64),
  "sweep.py": "d".repeat(64),
};
const MANIFEST = "e".repeat(64);

function layout(count) {
  return Array.from({ length: count }, (_, index) => ({
    id: index, x_km: index + 1, y_km: 1, available: true,
  }));
}

function fixture() {
  const catalog = {
    schema_version: 1, mode: "catalog", domain_side_km: 60,
    defaults: {
      n_bases: 9, offline_base: null, point_km: [37.2, 33.6],
      wind_mps: [12, 0], airspeed_mps: 18, endurance_min: 46,
      reserve_fraction: 0.25, launch_latency_s: 60,
    },
    parameter_limits: {
      airspeed_mps: [1, 40], wind_component_mps: [-30, 30],
      endurance_min: [1, 120], reserve_fraction: [0, 0.9],
      launch_latency_s: [0, 600],
    },
    layouts: { "9": layout(9), "25": layout(25) },
    assumptions: {
      dwell_s: 60, turnaround_s: 120, max_wind_mps: 12, queueing: false,
    },
    source_sha256: { ...HASHES },
    limitations: ["Synthetic inputs only."],
    study: {
      id: "2026-11-09-resilience", manifest_sha256: MANIFEST,
      heldout_seasons: 4,
      cases: [
        { case_id: "healthy-9", n_bases: 9, wind_east_mps: 8, offline_base: null, active_bases: 9 },
        { case_id: "outage-9", n_bases: 9, wind_east_mps: 8, offline_base: 0, active_bases: 8 },
      ],
    },
  };
  const missionResult = {
    schema_version: 1, mode: "mission",
    inputs: structuredClone(catalog.defaults),
    domain_side_km: 60, point_km: [...catalog.defaults.point_km],
    bases: catalog.layouts["9"].map((base) => ({ ...base })),
    candidates: [], selected_base_id: 0, status: "served",
    response_s: 420.5, within_15min: true, usable_airborne_s: 2070,
    assumptions: { ...catalog.assumptions },
    source_sha256: { ...HASHES },
    limitations: [...catalog.limitations],
  };
  const missionSnapshot = {
    mode: "mission",
    inputs: structuredClone(missionResult.inputs),
    result: missionResult,
    source_provenance: {
      source_sha256: { ...HASHES },
      assumptions: { ...missionResult.assumptions },
      limitations: [...missionResult.limitations],
    },
  };
  const replayResult = {
    schema_version: 1, mode: "replay", case_id: "outage-9", season: 2,
    study_manifest_sha256: MANIFEST, domain_side_km: 60, season_days: 120,
    bases: catalog.layouts["9"].map((base, index) => ({
      ...base, available: index !== 0,
    })),
    counts: { case_id: "outage-9", season: 2 },
    alerts: [{
      index: 0, alert_s: 1, x_km: 2, y_km: 3, is_real: true,
      response_s: null, within_15min: false, status: "unreachable",
    }],
  };
  const replaySnapshot = {
    mode: "replay",
    inputs: { case_id: replayResult.case_id, season: replayResult.season },
    result: replayResult,
    source_provenance: { study_manifest_sha256: MANIFEST },
  };
  return { catalog, missionSnapshot, replaySnapshot };
}

function missionSession(catalog) {
  return {
    kind: "wildfire-mission-lab-session", schema_version: 1,
    mode: "mission", inputs: structuredClone(catalog.defaults),
    comparison: false,
    provenance: { source_sha256: { ...catalog.source_sha256 } },
  };
}

function replaySession(comparison = false) {
  return {
    kind: "wildfire-mission-lab-session", schema_version: 1,
    mode: "replay", inputs: { case_id: "outage-9", season: 2 },
    comparison,
    provenance: { study_manifest_sha256: MANIFEST },
  };
}

test("mission session round trip preserves all inputs and source hashes", () => {
  const { catalog, missionSnapshot } = fixture();
  const session = makeSession(missionSnapshot, catalog);
  assert.equal(Object.getPrototypeOf(session), Object.prototype);
  assert.deepEqual(Object.keys(session).sort(), [
    "comparison", "inputs", "kind", "mode", "provenance", "schema_version",
  ]);
  assert.equal(Object.keys(session.inputs).length, 8);
  assert.equal(Object.keys(session.provenance.source_sha256).length, 4);
  assert.deepEqual(session, missionSession(catalog));
  const parsed = parseSession(JSON.stringify(session), catalog);
  assert.equal(Object.getPrototypeOf(parsed), Object.prototype);
  assert.deepEqual(parsed, session);
});

test("replay session round trip preserves case, season and comparison flag", () => {
  const { catalog, replaySnapshot } = fixture();
  const plain = makeSession(replaySnapshot, catalog);
  assert.deepEqual(plain, replaySession());
  assert.deepEqual(parseSession(JSON.stringify(plain), catalog), plain);
  const paired = makeSession(replaySnapshot, catalog, { comparison: true });
  assert.equal(paired.mode, "replay");
  assert.equal(paired.comparison, true);
  assert.deepEqual(paired.inputs, { case_id: "outage-9", season: 2 });
  assert.deepEqual(parseSession(JSON.stringify(paired), catalog), paired);
});

test("sessions use the received result, not unconfirmed form values", () => {
  const { catalog, missionSnapshot, replaySnapshot } = fixture();
  missionSnapshot.inputs = {
    ...missionSnapshot.result.inputs, airspeed_mps: 20, point_km: [1, 1],
  };
  const mission = makeSession(missionSnapshot, catalog);
  assert.equal(mission.inputs.airspeed_mps, 18);
  assert.deepEqual(mission.inputs.point_km, [37.2, 33.6]);
  replaySnapshot.inputs = { case_id: "healthy-9", season: 0 };
  const replay = makeSession(replaySnapshot, catalog);
  assert.equal(replay.inputs.case_id, "outage-9");
  assert.equal(replay.inputs.season, 2);
});

test("sessions store inputs and provenance only, never received results", () => {
  const { catalog, missionSnapshot, replaySnapshot } = fixture();
  for (const session of [
    makeSession(missionSnapshot, catalog),
    makeSession(replaySnapshot, catalog),
    makeSession(replaySnapshot, catalog, { comparison: true }),
  ]) {
    assert.equal("result" in session, false);
    assert.equal("snapshot" in session, false);
    assert.equal(JSON.stringify(session).includes('"result"'), false);
  }
});

test("source-hash objects compare exact keys and values independent of order", () => {
  const { catalog } = fixture();
  const session = missionSession(catalog);
  session.provenance.source_sha256 = Object.fromEntries(
    Object.entries(HASHES).reverse(),
  );
  assert.deepEqual(parseSession(JSON.stringify(session), catalog), session);
});

test("mismatched, missing or extra mission source hashes reject", () => {
  for (const change of [
    (hashes) => { hashes["research.py"] = "0".repeat(64); },
    (hashes) => { delete hashes["research.py"]; },
    (hashes) => { hashes["extra.py"] = "f".repeat(64); },
  ]) {
    const { catalog, missionSnapshot } = fixture();
    change(missionSnapshot.result.source_sha256);
    missionSnapshot.source_provenance.source_sha256 = {
      ...missionSnapshot.result.source_sha256,
    };
    assert.throws(() => makeSession(missionSnapshot, catalog), change.toString());
    const session = missionSession(catalog);
    change(session.provenance.source_sha256);
    assert.throws(() => parseSession(JSON.stringify(session), catalog), change.toString());
  }
});

test("replay manifest fingerprint must equal the catalog manifest", () => {
  const { catalog, replaySnapshot } = fixture();
  replaySnapshot.result.study_manifest_sha256 = "0".repeat(64);
  replaySnapshot.source_provenance.study_manifest_sha256 = "0".repeat(64);
  assert.throws(() => makeSession(replaySnapshot, catalog));
  const session = replaySession();
  session.provenance.study_manifest_sha256 = "0".repeat(64);
  assert.throws(() => parseSession(JSON.stringify(session), catalog));
});

test("mission provenance rejects invalid matching catalog and result hashes", () => {
  for (const hashes of [
    {},
    { bad: "" },
    { bad: 123 },
    { bad: "g".repeat(64) },
  ]) {
    const { catalog, missionSnapshot } = fixture();
    catalog.source_sha256 = structuredClone(hashes);
    missionSnapshot.result.source_sha256 = structuredClone(hashes);
    missionSnapshot.source_provenance.source_sha256 = structuredClone(hashes);
    assert.throws(() => makeSession(missionSnapshot, catalog));
  }
});

test("replay provenance rejects invalid matching catalog and result manifests", () => {
  for (const manifest of ["", "0", 42, null, "g".repeat(64)]) {
    const { catalog, replaySnapshot } = fixture();
    catalog.study.manifest_sha256 = manifest;
    replaySnapshot.result.study_manifest_sha256 = manifest;
    replaySnapshot.source_provenance.study_manifest_sha256 = manifest;
    assert.throws(() => makeSession(replaySnapshot, catalog));
  }
});

test("wrong kind, version, mode and top-level key changes reject", () => {
  const { catalog } = fixture();
  for (const change of [
    (session) => { session.kind = "wildfire-session"; },
    (session) => { session.schema_version = 2; },
    (session) => { session.schema_version = "1"; },
    (session) => { session.mode = "status"; },
    (session) => { session.mode = "Mission"; },
    (session) => { session.extra = true; },
    (session) => { session.provenance.extra = 1; },
    (session) => { delete session.comparison; },
    (session) => { delete session.provenance; },
    (session) => { delete session.inputs; },
    (session) => { delete session.mode; },
  ]) {
    const session = missionSession(catalog);
    change(session);
    assert.throws(() => parseSession(JSON.stringify(session), catalog), change.toString());
  }
});

test("mission input keys match catalog defaults exactly", () => {
  const { catalog } = fixture();
  const base = missionSession(catalog);
  for (const key of Object.keys(base.inputs)) {
    const session = structuredClone(base);
    delete session.inputs[key];
    assert.throws(() => parseSession(JSON.stringify(session), catalog), key);
  }
  const extra = structuredClone(base);
  extra.inputs.unknown = 1;
  assert.throws(() => parseSession(JSON.stringify(extra), catalog));
});

test("mission input values validate types and metadata bounds", () => {
  const { catalog } = fixture();
  const base = missionSession(catalog);
  for (const change of [
    (inputs) => { inputs.n_bases = 16; },
    (inputs) => { inputs.n_bases = 9.5; },
    (inputs) => { inputs.n_bases = "9"; },
    (inputs) => { inputs.n_bases = true; },
    (inputs) => { inputs.offline_base = 9; },
    (inputs) => { inputs.offline_base = -1; },
    (inputs) => { inputs.offline_base = 1.5; },
    (inputs) => { inputs.offline_base = "0"; },
    (inputs) => { inputs.offline_base = true; },
    (inputs) => { inputs.point_km = [30]; },
    (inputs) => { inputs.point_km = [30, 30, 30]; },
    (inputs) => { inputs.point_km = "30,30"; },
    (inputs) => { inputs.point_km = [true, false]; },
    (inputs) => { inputs.point_km = [-0.5, 30]; },
    (inputs) => { inputs.point_km = [60.5, 30]; },
    (inputs) => { inputs.point_km = [1e999, 30]; },
    (inputs) => { inputs.wind_mps = [0]; },
    (inputs) => { inputs.wind_mps = [0, 0, 0]; },
    (inputs) => { inputs.wind_mps = [31, 0]; },
    (inputs) => { inputs.wind_mps = [0, -31]; },
    (inputs) => { inputs.wind_mps = ["8", 0]; },
    (inputs) => { inputs.wind_mps = [0, 1e999]; },
    (inputs) => { inputs.airspeed_mps = 0.5; },
    (inputs) => { inputs.airspeed_mps = 41; },
    (inputs) => { inputs.airspeed_mps = "18"; },
    (inputs) => { inputs.airspeed_mps = true; },
    (inputs) => { inputs.airspeed_mps = 1e999; },
    (inputs) => { inputs.endurance_min = 0; },
    (inputs) => { inputs.endurance_min = 121; },
    (inputs) => { inputs.endurance_min = null; },
    (inputs) => { inputs.reserve_fraction = -0.1; },
    (inputs) => { inputs.reserve_fraction = 0.95; },
    (inputs) => { inputs.reserve_fraction = "0.25"; },
    (inputs) => { inputs.launch_latency_s = -1; },
    (inputs) => { inputs.launch_latency_s = 601; },
    (inputs) => { inputs.launch_latency_s = false; },
  ]) {
    const session = structuredClone(base);
    change(session.inputs);
    assert.throws(() => parseSession(JSON.stringify(session), catalog), change.toString());
  }
});

test("metadata boundary values and layout members are accepted", () => {
  const { catalog } = fixture();
  const session = missionSession(catalog);
  session.inputs.n_bases = 25;
  session.inputs.offline_base = 24;
  session.inputs.point_km = [0, 60];
  session.inputs.wind_mps = [-30, 30];
  session.inputs.airspeed_mps = 1;
  session.inputs.endurance_min = 120;
  session.inputs.reserve_fraction = 0.9;
  session.inputs.launch_latency_s = 0;
  assert.deepEqual(parseSession(JSON.stringify(session), catalog), session);
});

test("bounds derive from catalog metadata, not hardcoded values", () => {
  const { catalog } = fixture();
  const session = missionSession(catalog);
  const smaller = structuredClone(catalog);
  smaller.domain_side_km = 30;
  assert.throws(() => parseSession(JSON.stringify(session), smaller));
  const tighter = structuredClone(catalog);
  tighter.parameter_limits.wind_component_mps = [-5, 5];
  assert.throws(() => parseSession(JSON.stringify(session), tighter));
  const fewer = structuredClone(catalog);
  delete fewer.layouts["25"];
  const layoutSession = missionSession(fewer);
  layoutSession.inputs.n_bases = 25;
  assert.throws(() => parseSession(JSON.stringify(layoutSession), fewer));
});

test("mode selects its own input and provenance schema", () => {
  const { catalog } = fixture();
  const missionCrossed = missionSession(catalog);
  missionCrossed.inputs = { case_id: "outage-9", season: 2 };
  assert.throws(() => parseSession(JSON.stringify(missionCrossed), catalog));
  const missionProvenance = missionSession(catalog);
  missionProvenance.provenance = { study_manifest_sha256: MANIFEST };
  assert.throws(() => parseSession(JSON.stringify(missionProvenance), catalog));
  const replayCrossed = replaySession();
  replayCrossed.inputs = structuredClone(catalog.defaults);
  assert.throws(() => parseSession(JSON.stringify(replayCrossed), catalog));
  const replayProvenance = replaySession();
  replayProvenance.provenance = { source_sha256: { ...HASHES } };
  assert.throws(() => parseSession(JSON.stringify(replayProvenance), catalog));
});

test("replay inputs require an existing case and integer season in range", () => {
  const { catalog } = fixture();
  const base = replaySession();
  for (const change of [
    (inputs) => { inputs.case_id = "unknown"; },
    (inputs) => { inputs.case_id = 9; },
    (inputs) => { inputs.case_id = null; },
    (inputs) => { inputs.season = -1; },
    (inputs) => { inputs.season = 4; },
    (inputs) => { inputs.season = 1.5; },
    (inputs) => { inputs.season = "2"; },
    (inputs) => { inputs.season = true; },
    (inputs) => { inputs.extra = 1; },
    (inputs) => { delete inputs.case_id; },
    (inputs) => { delete inputs.season; },
  ]) {
    const session = structuredClone(base);
    change(session.inputs);
    assert.throws(() => parseSession(JSON.stringify(session), catalog), change.toString());
  }
});

test("comparison is a boolean and never set on a mission session", () => {
  const { catalog, missionSnapshot } = fixture();
  assert.throws(() => makeSession(missionSnapshot, catalog, { comparison: true }));
  for (const value of [true, "true", 1, null, {}]) {
    const session = missionSession(catalog);
    session.comparison = value;
    assert.throws(() => parseSession(JSON.stringify(session), catalog), String(value));
  }
  for (const value of ["true", 1, null, {}, "false"]) {
    const session = replaySession();
    session.comparison = value;
    assert.throws(() => parseSession(JSON.stringify(session), catalog), String(value));
  }
});

test("text over 65536 characters rejects before JSON parsing", () => {
  const { catalog } = fixture();
  const session = missionSession(catalog);
  const text = JSON.stringify(session);
  const padded = text + " ".repeat(65536 - text.length);
  assert.equal(padded.length, 65536);
  assert.deepEqual(parseSession(padded, catalog), session);
  assert.throws(() => parseSession(`${padded} `, catalog));
  assert.throws(() => parseSession(" ".repeat(70000), catalog));
});

test("malformed text and non-object JSON reject", () => {
  const { catalog } = fixture();
  for (const text of ["{", '{"kind":', "[]", "5", "null", "true", '"mission"']) {
    assert.throws(() => parseSession(text, catalog), text);
  }
  assert.throws(() => parseSession(null, catalog));
  assert.throws(() => parseSession(undefined, catalog));
  const session = JSON.stringify(missionSession(catalog));
  assert.throws(() => parseSession(session));
});

test("provenance binds a session to the catalog that produced it", () => {
  const { catalog } = fixture();
  const mission = JSON.stringify(missionSession(catalog));
  const replay = JSON.stringify(replaySession());
  for (const change of [
    (next) => { next.source_sha256["research.py"] = "0".repeat(64); },
    (next) => { delete next.source_sha256["sweep.py"]; },
  ]) {
    const changed = structuredClone(catalog);
    change(changed);
    assert.throws(() => parseSession(mission, changed), change.toString());
  }
  for (const change of [
    (next) => { next.study.manifest_sha256 = "0".repeat(64); },
    (next) => { next.study.cases.pop(); },
    (next) => { next.study.heldout_seasons = 2; },
  ]) {
    const changed = structuredClone(catalog);
    change(changed);
    assert.throws(() => parseSession(replay, changed), change.toString());
  }
});

test("makeSession requires a snapshot with a valid received result", () => {
  const { catalog, missionSnapshot, replaySnapshot } = fixture();
  for (const next of [
    null, undefined, {},
    { ...missionSnapshot, result: null },
    { ...missionSnapshot, result: {} },
  ]) {
    assert.throws(() => makeSession(next, catalog), String(next));
  }
  for (const change of [
    (snapshot) => { snapshot.mode = "status"; snapshot.result.mode = "status"; },
    (snapshot) => { snapshot.result.schema_version = 2; },
    (snapshot) => { delete snapshot.result.inputs; },
    (snapshot) => { snapshot.result.inputs.extra = 1; },
    (snapshot) => { snapshot.result.inputs.airspeed_mps = 99; },
    (snapshot) => { snapshot.result.inputs.airspeed_mps = Infinity; },
    (snapshot) => { snapshot.result.inputs.reserve_fraction = NaN; },
    (snapshot) => { snapshot.result.inputs.n_bases = "9"; },
    (snapshot) => { snapshot.result.inputs.wind_mps = [0, 0, 0]; },
  ]) {
    const snapshot = structuredClone(missionSnapshot);
    change(snapshot);
    assert.throws(() => makeSession(snapshot, catalog), change.toString());
  }
  for (const change of [
    (snapshot) => { snapshot.result.case_id = "unknown"; },
    (snapshot) => { snapshot.result.season = 4; },
    (snapshot) => { snapshot.result.season = "2"; },
    (snapshot) => { snapshot.result.study_manifest_sha256 = "0".repeat(64); },
  ]) {
    const snapshot = structuredClone(replaySnapshot);
    change(snapshot);
    if (snapshot.source_provenance) {
      snapshot.source_provenance.study_manifest_sha256 =
        snapshot.result.study_manifest_sha256;
    }
    assert.throws(() => makeSession(snapshot, catalog), change.toString());
  }
});

test("returned sessions do not share caller-owned objects", () => {
  const { catalog, missionSnapshot } = fixture();
  const session = makeSession(missionSnapshot, catalog);
  assert.notStrictEqual(session.inputs, missionSnapshot.result.inputs);
  missionSnapshot.result.inputs.point_km[0] = -1;
  missionSnapshot.result.source_sha256["sweep.py"] = "0".repeat(64);
  assert.deepEqual(session.inputs.point_km, [37.2, 33.6]);
  assert.equal(session.provenance.source_sha256["sweep.py"], HASHES["sweep.py"]);
  session.inputs.wind_mps[0] = -99;
  assert.equal(missionSnapshot.result.inputs.wind_mps[0], 12);
  const parsed = parseSession(
    JSON.stringify(missionSession(catalog)), catalog,
  );
  parsed.inputs.point_km[0] = -1;
  parsed.provenance.source_sha256["research.py"] = "0".repeat(64);
  assert.equal(catalog.defaults.point_km[0], 37.2);
  assert.equal(catalog.source_sha256["research.py"], HASHES["research.py"]);
});

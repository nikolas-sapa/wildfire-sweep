import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../comparison_data.js", import.meta.url), "utf8");
const { comparisonCases, pairReplays } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

function fixture() {
  const catalog = { study: { manifest_sha256: "a".repeat(64), cases: [
    { case_id: "healthy", n_bases: 9, wind_east_mps: 8, offline_base: null },
    { case_id: "outage", n_bases: 9, wind_east_mps: 8, offline_base: 0 },
  ] } };
  const make = (id) => ({
    schema_version: 1, mode: "replay", case_id: id, season: 0,
    study_manifest_sha256: catalog.study.manifest_sha256,
    domain_side_km: 60, season_days: 120,
    bases: Array.from({ length: 9 }, (_, index) => ({
      id: index, x_km: index + 1, y_km: 1,
      available: id === "healthy" || index !== 0,
    })),
    counts: { case_id: id, season: 0 },
    alerts: [
      { index: 0, alert_s: 1, x_km: 2, y_km: 3, is_real: true,
        response_s: id === "healthy" ? 60 : null,
        status: id === "healthy" ? "within_15min" : "unreachable",
        within_15min: id === "healthy" },
      { index: 1, alert_s: 2, x_km: 4, y_km: 5, is_real: false,
        response_s: 1000, status: "late", within_15min: false },
    ],
  });
  return { catalog, healthy: make("healthy"), outage: make("outage") };
}

test("roles use matching catalog descriptors, not identifier parsing", () => {
  const { catalog } = fixture();
  assert.equal(comparisonCases(catalog, "healthy").outage.case_id, "outage");
  assert.equal(comparisonCases(catalog, "outage").healthy.case_id, "healthy");
  assert.throws(() => comparisonCases(catalog, "unknown"));
  catalog.study.cases.push({ ...catalog.study.cases[1], case_id: "another-outage" });
  assert.throws(() => comparisonCases(catalog, "healthy"));
});

test("pair order is deterministic and null outcomes remain unreachable", () => {
  const { catalog, healthy, outage } = fixture();
  const pair = pairReplays(catalog, outage, healthy);
  assert.deepEqual(pair.healthy, healthy);
  assert.deepEqual(pair.outage, outage);
  assert.equal(pair.outage.alerts[0].response_s, null);
  pair.healthy.alerts[0].x_km = -99;
  assert.equal(healthy.alerts[0].x_km, 2);
});

test("every incompatible provenance and shared-alert field rejects", () => {
  const changes = [
    (x) => { x.schema_version = 2; },
    (x) => { x.mode = "mission"; },
    (x) => { x.study_manifest_sha256 = "b".repeat(64); },
    (x) => { x.case_id = "unknown"; },
    (x) => { x.season = 1; },
    (x) => { x.season = true; },
    (x) => { x.domain_side_km = 61; },
    (x) => { x.season_days = 121; },
    (x) => { x.bases[0].x_km += 1; },
    (x) => { x.bases[0].id = 1; },
    (x) => { x.bases[0].available = true; },
    (x) => { x.counts.case_id = "healthy"; },
    (x) => { x.counts.season = 1; },
    (x) => { x.alerts.pop(); },
    (x) => { x.alerts[0].index = 1; },
    (x) => { x.alerts[0].alert_s += 1; },
    (x) => { x.alerts[0].x_km += 1; },
    (x) => { x.alerts[0].y_km += 1; },
    (x) => { x.alerts[0].is_real = false; },
    (x) => { x.alerts[0].response_s = Infinity; },
    (x) => { x.alerts[0].status = "within_15min"; },
    (x) => { x.alerts[1].within_15min = true; },
  ];
  for (const change of changes) {
    const { catalog, healthy, outage } = fixture();
    change(outage);
    assert.throws(() => pairReplays(catalog, healthy, outage), change.toString());
  }
});

test("different wind/layout, missing partner and duplicate cases reject", () => {
  for (const change of [
    (x) => { x.study.cases[1].wind_east_mps = 12; },
    (x) => { x.study.cases[1].n_bases = 25; },
    (x) => { x.study.cases.pop(); },
    (x) => { x.study.cases.push({ ...x.study.cases[0] }); },
  ]) {
    const { catalog, healthy, outage } = fixture();
    change(catalog);
    assert.throws(() => pairReplays(catalog, healthy, outage));
  }
});

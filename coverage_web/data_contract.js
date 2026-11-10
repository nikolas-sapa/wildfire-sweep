const HASH = /^[0-9a-f]{64}$/;
const OUTCOMES = { unreachable: 0, late: 1, timely: 2, weather_closed: 3 };
const META_KEYS = [
  "schema_version", "mode", "study_id", "capture_sha256", "grid_n", "domain_side_km",
  "timely_threshold_s", "outcome_codes", "source_sha256", "grid", "limitations",
];
const CASE_KEYS = [
  "case_id", "n_bases", "wind_mps", "wind_speed_mps", "heading_deg", "profile",
  "offline_bases", "airspeed_mps", "endurance_min", "reserve_fraction", "launch_latency_s",
  "summary",
];
const COUNT_KEYS = ["unreachable_cells", "late_cells", "timely_cells", "weather_closed_cells"];

function requireValue(condition, message) {
  if (!condition) throw new Error(`Invalid coverage data: ${message}`);
}

function object(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exact(value, keys, label) {
  requireValue(object(value) && Object.keys(value).length === keys.length
    && keys.every((key) => Object.hasOwn(value, key)), `${label} fields`);
}

function same(a, b) {
  if (a === b) return true;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length
      && a.every((value, index) => same(value, b[index]));
  }
  return object(a) && object(b) && Object.keys(a).length === Object.keys(b).length
    && Object.keys(a).every((key) => Object.hasOwn(b, key) && same(a[key], b[key]));
}

function number(value, low, high, label) {
  requireValue(typeof value === "number" && Number.isFinite(value)
    && value >= low && value <= high, label);
}

function integer(value, low, high, label) {
  number(value, low, high, label);
  requireValue(Number.isInteger(value), label);
}

function text(value, label) {
  requireValue(typeof value === "string" && value.length > 0 && value.length <= 1024, label);
}

function metadata(value, mode) {
  requireValue(value.schema_version === 1 && value.mode === mode, "version/mode");
  text(value.study_id, "study ID");
  requireValue(typeof value.capture_sha256 === "string" && HASH.test(value.capture_sha256),
    "capture fingerprint");
  integer(value.grid_n, 1, 160, "grid size");
  number(value.domain_side_km, Number.MIN_VALUE, 100000, "domain side");
  number(value.timely_threshold_s, Number.MIN_VALUE, 100000, "deadline");
  requireValue(same(value.outcome_codes, OUTCOMES), "outcome codes");
  requireValue(same(value.grid, {
    order: "y-major-x-fast", locations: "cell-centers", north: "positive-y",
  }), "grid convention");
  requireValue(object(value.source_sha256) && Object.keys(value.source_sha256).length > 0
    && Object.entries(value.source_sha256).every(([key, hash]) => key.length > 0
      && typeof hash === "string" && HASH.test(hash)), "source fingerprints");
  requireValue(Array.isArray(value.limitations) && value.limitations.length > 0
    && value.limitations.every((item) => typeof item === "string" && item.length > 0),
  "limitations");
}

function base(value, index, side) {
  exact(value, ["id", "x_km", "y_km", "available"], "base");
  requireValue(value.id === index && typeof value.available === "boolean", "base ID/availability");
  number(value.x_km, 0, side, "base x");
  number(value.y_km, 0, side, "base y");
}

function descriptor(value, catalog) {
  exact(value, CASE_KEYS, "case");
  text(value.case_id, "case ID");
  integer(value.n_bases, 1, 1000, "base count");
  requireValue(Object.hasOwn(catalog.layouts, String(value.n_bases)), "unknown layout");
  requireValue(Array.isArray(value.wind_mps) && value.wind_mps.length === 2, "wind vector");
  value.wind_mps.forEach((component) => number(component, -30, 30, "wind component"));
  number(value.wind_speed_mps, 0, 50, "wind speed");
  requireValue(Math.abs(Math.hypot(...value.wind_mps) - value.wind_speed_mps) <= 1e-12,
    "wind magnitude");
  if (value.heading_deg === null) {
    requireValue(value.wind_speed_mps === 0, "missing heading in noncalm case");
  } else {
    number(value.heading_deg, 0, 359.999999999, "heading");
  }
  requireValue(["reference", "short_endurance", "larger_reserve", "slow_launch", "combined"]
    .includes(value.profile), "profile");
  requireValue(Array.isArray(value.offline_bases), "offline IDs");
  value.offline_bases.forEach((id, index) => {
    integer(id, 0, value.n_bases - 1, "offline base");
    requireValue(index === 0 || id > value.offline_bases[index - 1], "offline ID ordering");
  });
  number(value.airspeed_mps, 1, 40, "airspeed");
  number(value.endurance_min, 1, 120, "endurance");
  number(value.reserve_fraction, 0, .9, "reserve");
  number(value.launch_latency_s, 0, 600, "launch latency");
  const summary = value.summary;
  exact(summary, ["case_id", ...COUNT_KEYS, "total_cells", "timely_area_fraction",
    "reachable_area_fraction"], "summary");
  const total = catalog.grid_n ** 2;
  requireValue(summary.case_id === value.case_id && summary.total_cells === total, "summary identity");
  COUNT_KEYS.forEach((key) => integer(summary[key], 0, total, key));
  requireValue(COUNT_KEYS.reduce((sum, key) => sum + summary[key], 0) === total,
    "summary outcome total");
  number(summary.timely_area_fraction, 0, 1, "timely area fraction");
  number(summary.reachable_area_fraction, 0, 1, "reachable area fraction");
  requireValue(summary.timely_area_fraction === summary.timely_cells / total
    && summary.reachable_area_fraction === (summary.timely_cells + summary.late_cells) / total,
  "summary fractions disagree with counts");
}

function validateCatalog(catalog) {
  exact(catalog, [...META_KEYS, "layouts", "cases"], "catalog");
  metadata(catalog, "coverage_catalog");
  requireValue(object(catalog.layouts) && Object.keys(catalog.layouts).length > 0, "layouts");
  for (const [count, bases] of Object.entries(catalog.layouts)) {
    requireValue(/^[1-9][0-9]*$/.test(count) && Array.isArray(bases)
      && bases.length === Number(count), "layout size");
    bases.forEach((item, index) => {
      base(item, index, catalog.domain_side_km);
      requireValue(item.available, "catalog layouts must include every healthy base");
    });
  }
  requireValue(Array.isArray(catalog.cases) && catalog.cases.length > 0
    && catalog.cases.length <= 388, "case inventory");
  const ids = new Set();
  for (const item of catalog.cases) {
    descriptor(item, catalog);
    requireValue(!ids.has(item.case_id), "duplicate case ID");
    ids.add(item.case_id);
  }
  return catalog;
}

function validateCase(payload, catalog) {
  validateCatalog(catalog);
  exact(payload, [...META_KEYS, "case", "bases", "cells"], "payload");
  metadata(payload, "coverage");
  for (const key of META_KEYS.filter((item) => item !== "mode")) {
    requireValue(same(payload[key], catalog[key]), `${key} differs from catalog`);
  }
  const expected = catalog.cases.find((item) => item.case_id === payload.case?.case_id);
  requireValue(expected !== undefined && same(payload.case, expected), "unknown/changed case descriptor");
  requireValue(Array.isArray(payload.bases) && payload.bases.length === expected.n_bases,
    "case base count");
  const layout = catalog.layouts[String(expected.n_bases)];
  payload.bases.forEach((item, index) => {
    base(item, index, payload.domain_side_km);
    requireValue(item.x_km === layout[index].x_km && item.y_km === layout[index].y_km
      && item.available === !expected.offline_bases.includes(index), "changed case geometry");
  });
  const total = payload.grid_n ** 2;
  requireValue(Array.isArray(payload.cells) && payload.cells.length === total, "cell count");
  const counts = Object.fromEntries(COUNT_KEYS.map((key) => [key, 0]));
  payload.cells.forEach((cell, index) => {
    exact(cell, ["index", "row", "column", "x_km", "y_km", "outcome",
      "response_s", "selected_base_id"], "cell");
    const row = Math.floor(index / payload.grid_n);
    const column = index % payload.grid_n;
    requireValue(cell.index === index && cell.row === row && cell.column === column, "cell ordering");
    number(cell.x_km, 0, payload.domain_side_km, "cell x");
    number(cell.y_km, 0, payload.domain_side_km, "cell y");
    const x = (column + .5) * payload.domain_side_km / payload.grid_n;
    const y = (row + .5) * payload.domain_side_km / payload.grid_n;
    requireValue(Math.abs(cell.x_km - x) <= 1e-9 && Math.abs(cell.y_km - y) <= 1e-9,
      "cell centers");
    requireValue(Object.hasOwn(OUTCOMES, cell.outcome), "cell outcome");
    counts[`${cell.outcome}_cells`] += 1;
    if (cell.outcome === "timely" || cell.outcome === "late") {
      number(cell.response_s, expected.launch_latency_s, Number.MAX_VALUE, "response");
      integer(cell.selected_base_id, 0, expected.n_bases - 1, "selected base ID");
      requireValue(payload.bases[cell.selected_base_id].available, "selected offline base");
      requireValue((cell.response_s <= payload.timely_threshold_s) === (cell.outcome === "timely"),
        "response deadline classification");
    } else {
      requireValue(cell.response_s === null && cell.selected_base_id === null,
        "unserved cell must preserve nulls");
    }
  });
  requireValue(COUNT_KEYS.every((key) => counts[key] === expected.summary[key]),
    "payload outcomes differ from frozen summary");
  return payload;
}

function validatePair(a, b, catalog) {
  validateCase(a, catalog);
  validateCase(b, catalog);
  requireValue(a.capture_sha256 === b.capture_sha256 && a.grid_n === b.grid_n
    && a.domain_side_km === b.domain_side_km, "incompatible pair");
  return { a, b };
}

export { validateCatalog, validateCase, validatePair };

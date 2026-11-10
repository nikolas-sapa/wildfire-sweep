function requireCondition(condition, message) {
  if (!condition) throw new Error(`Captured comparison: ${message}`);
}

function comparisonCases(catalog, caseId) {
  const cases = catalog?.study?.cases;
  requireCondition(Array.isArray(cases), "case catalog unavailable");
  requireCondition(new Set(cases.map((item) => item.case_id)).size === cases.length,
    "duplicate case identifiers");
  const selected = cases.find((item) => item.case_id === caseId);
  requireCondition(Boolean(selected), "unknown case");
  const group = cases.filter((item) => item.n_bases === selected.n_bases
    && item.wind_east_mps === selected.wind_east_mps);
  const healthy = group.filter((item) => item.offline_base === null);
  const outage = group.filter((item) => Number.isInteger(item.offline_base)
    && item.offline_base >= 0 && item.offline_base < item.n_bases);
  requireCondition(healthy.length === 1 && outage.length === 1,
    "exactly one healthy and one outage partner required");
  requireCondition(group.length === 2 && Number.isInteger(selected.n_bases)
    && selected.n_bases > 0 && Number.isFinite(selected.wind_east_mps),
  "invalid layout/wind descriptors");
  return structuredClone({ healthy: healthy[0], outage: outage[0] });
}

function validatePayload(payload, descriptor, manifest) {
  requireCondition(payload && payload.schema_version === 1 && payload.mode === "replay",
    "expected a captured replay payload");
  requireCondition(payload.case_id === descriptor.case_id, "unexpected case");
  requireCondition(payload.study_manifest_sha256 === manifest, "manifest mismatch");
  requireCondition(Number.isInteger(payload.season) && payload.season >= 0,
    "invalid season");
  requireCondition(Number.isFinite(payload.domain_side_km) && payload.domain_side_km > 0
    && Number.isFinite(payload.season_days) && payload.season_days > 0,
  "invalid captured domain");
  requireCondition(payload.counts?.case_id === payload.case_id
    && payload.counts?.season === payload.season, "mislabelled season counts");
  requireCondition(Array.isArray(payload.bases)
    && payload.bases.length === descriptor.n_bases, "invalid base layout");
  payload.bases.forEach((base, index) => {
    requireCondition(base.id === index && Number.isFinite(base.x_km)
      && Number.isFinite(base.y_km)
      && base.available === (index !== descriptor.offline_base),
    "base identifiers, coordinates or availability mismatch");
  });
  requireCondition(Array.isArray(payload.alerts), "captured alerts unavailable");
  payload.alerts.forEach((alert, index) => {
    requireCondition(alert.index === index && Number.isFinite(alert.alert_s)
      && alert.alert_s >= 0 && Number.isFinite(alert.x_km)
      && Number.isFinite(alert.y_km) && typeof alert.is_real === "boolean",
    "invalid captured alert");
    const finiteResponse = Number.isFinite(alert.response_s) && alert.response_s >= 0;
    requireCondition(alert.response_s === null || finiteResponse, "invalid captured response");
    requireCondition(alert.response_s === null ? alert.status === "unreachable"
      : ["within_15min", "late"].includes(alert.status), "invalid recorded outcome");
    requireCondition(alert.within_15min === (alert.status === "within_15min"),
      "inconsistent recorded outcome flag");
  });
}

function pairReplays(catalog, first, second) {
  const cases = comparisonCases(catalog, first?.case_id);
  const manifest = catalog.study.manifest_sha256;
  requireCondition(typeof manifest === "string" && /^[0-9a-f]{64}$/.test(manifest),
    "invalid study fingerprint");
  const healthy = first.case_id === cases.healthy.case_id ? first : second;
  const outage = first.case_id === cases.outage.case_id ? first : second;
  validatePayload(healthy, cases.healthy, manifest);
  validatePayload(outage, cases.outage, manifest);
  requireCondition(healthy !== outage && first !== second, "two distinct case payloads required");
  requireCondition(healthy.season === outage.season
    && healthy.domain_side_km === outage.domain_side_km
    && healthy.season_days === outage.season_days, "season/domain mismatch");
  requireCondition(healthy.bases.every((base, index) => {
    const other = outage.bases[index];
    return base.id === other.id && base.x_km === other.x_km && base.y_km === other.y_km;
  }), "base geometry mismatch");
  requireCondition(healthy.alerts.length === outage.alerts.length, "alert count mismatch");
  const sharedFields = ["index", "alert_s", "x_km", "y_km", "is_real"];
  requireCondition(healthy.alerts.every((alert, index) =>
    sharedFields.every((key) => alert[key] === outage.alerts[index][key])),
  "shared alert alignment mismatch");
  return structuredClone({ healthy, outage, cases });
}

export { comparisonCases, pairReplays };

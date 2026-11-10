const SESSION_KIND = "wildfire-mission-lab-session";
const SESSION_SCHEMA_VERSION = 1;
const MAX_SESSION_TEXT = 65536;
const MAX_SESSION_BYTES = 65536;

function requireCondition(condition, message) {
  if (!condition) throw new Error(`Invalid session: ${message}`);
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function requireExactKeys(value, expected, label) {
  requireCondition(isPlainObject(value), `${label} must be a plain object`);
  requireCondition(
    Object.keys(value).length === expected.length
      && expected.every((key) => Object.prototype.hasOwnProperty.call(value, key)),
    `${label} keys must be exactly: ${expected.join(", ")}`,
  );
}

function requireBoundedNumber(value, bounds, label) {
  requireCondition(
    typeof value === "number" && Number.isFinite(value),
    `${label} must be a finite number`,
  );
  requireCondition(
    Array.isArray(bounds) && bounds.length === 2
      && bounds.every((bound) => typeof bound === "number" && Number.isFinite(bound))
      && bounds[0] <= bounds[1],
    `${label} metadata bounds unavailable`,
  );
  requireCondition(
    value >= bounds[0] && value <= bounds[1],
    `${label} must be within [${bounds[0]}, ${bounds[1]}]`,
  );
}

function requireVector(value, bounds, label) {
  requireCondition(
    Array.isArray(value) && value.length === 2,
    `${label} must contain exactly two numbers`,
  );
  for (let index = 0; index < 2; index += 1) {
    requireBoundedNumber(value[index], bounds, `${label}[${index}]`);
  }
  return [value[0], value[1]];
}

function missionInputValues(inputs, catalog) {
  const defaults = catalog?.defaults;
  requireCondition(isPlainObject(defaults), "catalog input defaults unavailable");
  requireExactKeys(inputs, Object.keys(defaults), "mission inputs");
  const layouts = catalog?.layouts;
  requireCondition(isPlainObject(layouts), "catalog layouts unavailable");
  const limits = catalog?.parameter_limits;
  requireCondition(isPlainObject(limits), "catalog parameter limits unavailable");
  const side = catalog?.domain_side_km;
  requireCondition(
    typeof side === "number" && Number.isFinite(side) && side > 0,
    "catalog domain size unavailable",
  );
  const nBases = inputs.n_bases;
  requireCondition(
    Number.isInteger(nBases)
      && Object.prototype.hasOwnProperty.call(layouts, String(nBases))
      && Array.isArray(layouts[String(nBases)]),
    "n_bases must be an integer size present in catalog layouts",
  );
  const values = {};
  for (const key of Object.keys(defaults)) {
    const value = inputs[key];
    if (key === "n_bases") {
      values.n_bases = nBases;
    } else if (key === "offline_base") {
      requireCondition(
        value === null || (Number.isInteger(value) && value >= 0 && value < nBases),
        "offline_base must be null or an original base index",
      );
      values.offline_base = value;
    } else if (key === "point_km") {
      values.point_km = requireVector(value, [0, side], "point_km");
    } else if (key === "wind_mps") {
      values.wind_mps = requireVector(value, limits.wind_component_mps, "wind_mps");
    } else {
      requireCondition(
        Object.prototype.hasOwnProperty.call(limits, key),
        `unsupported mission input field ${key}`,
      );
      requireBoundedNumber(value, limits[key], key);
      values[key] = value;
    }
  }
  return values;
}

function replayInputValues(inputs, catalog) {
  requireExactKeys(inputs, ["case_id", "season"], "replay inputs");
  const study = catalog?.study;
  requireCondition(isPlainObject(study), "catalog study metadata unavailable");
  requireCondition(Array.isArray(study.cases), "catalog replay cases unavailable");
  const caseId = inputs.case_id;
  requireCondition(
    typeof caseId === "string"
      && study.cases.some((item) => item && item.case_id === caseId),
    "replay case_id must name a captured case",
  );
  requireCondition(
    Number.isInteger(study.heldout_seasons) && study.heldout_seasons > 0,
    "catalog held-out season metadata unavailable",
  );
  const season = inputs.season;
  requireCondition(
    Number.isInteger(season) && season >= 0 && season < study.heldout_seasons,
    "replay season must be an integer index within the captured study",
  );
  return { case_id: caseId, season };
}

function missionProvenance(provenance, catalog) {
  requireExactKeys(provenance, ["source_sha256"], "mission provenance");
  const expected = catalog?.source_sha256;
  requireCondition(isPlainObject(expected), "catalog source hashes unavailable");
  const hashes = provenance.source_sha256;
  requireCondition(isPlainObject(hashes), "source_sha256 must be a plain object");
  const expectedKeys = Object.keys(expected);
  requireCondition(
    expectedKeys.length > 0
      && expectedKeys.every((key) => typeof expected[key] === "string"
        && /^[0-9a-f]{64}$/.test(expected[key])),
    "catalog source hashes must be nonempty lowercase SHA-256 values",
  );
  requireCondition(
    Object.keys(hashes).length === expectedKeys.length
      && expectedKeys.every((key) => Object.prototype.hasOwnProperty.call(hashes, key)
        && hashes[key] === expected[key]),
    "source_sha256 must match the local model source hashes",
  );
  return { source_sha256: { ...hashes } };
}

function replayProvenance(provenance, catalog) {
  requireExactKeys(provenance, ["study_manifest_sha256"], "replay provenance");
  const manifest = catalog?.study?.manifest_sha256;
  requireCondition(
    typeof manifest === "string" && /^[0-9a-f]{64}$/.test(manifest),
    "catalog study fingerprint must be a lowercase SHA-256 value",
  );
  requireCondition(
    provenance.study_manifest_sha256 === manifest,
    "study_manifest_sha256 must match the frozen study fingerprint",
  );
  return { study_manifest_sha256: manifest };
}

function validateSession(candidate, catalog) {
  requireExactKeys(
    candidate,
    ["kind", "schema_version", "mode", "inputs", "comparison", "provenance"],
    "session",
  );
  requireCondition(candidate.kind === SESSION_KIND, "unsupported session kind");
  requireCondition(
    candidate.schema_version === SESSION_SCHEMA_VERSION,
    "unsupported session schema version",
  );
  const mode = candidate.mode;
  requireCondition(mode === "mission" || mode === "replay", "unsupported session mode");
  const comparison = candidate.comparison;
  requireCondition(
    comparison === true || comparison === false,
    "comparison flag must be a boolean",
  );
  requireCondition(
    mode === "replay" || comparison === false,
    "mission sessions cannot request comparison",
  );
  const inputs = mode === "mission"
    ? missionInputValues(candidate.inputs, catalog)
    : replayInputValues(candidate.inputs, catalog);
  const provenance = mode === "mission"
    ? missionProvenance(candidate.provenance, catalog)
    : replayProvenance(candidate.provenance, catalog);
  return {
    kind: SESSION_KIND,
    schema_version: SESSION_SCHEMA_VERSION,
    mode,
    inputs,
    comparison,
    provenance,
  };
}

function makeSession(snapshot, catalog, { comparison = false } = {}) {
  requireCondition(
    comparison === true || comparison === false,
    "comparison option must be a boolean",
  );
  requireCondition(isPlainObject(snapshot), "a received result snapshot is required");
  const mode = snapshot.mode;
  requireCondition(
    mode === "mission" || mode === "replay",
    "snapshot mode must be mission or replay",
  );
  const result = snapshot.result;
  requireCondition(
    isPlainObject(result)
      && result.schema_version === SESSION_SCHEMA_VERSION
      && result.mode === mode,
    "snapshot must carry a successful received result",
  );
  requireCondition(
    mode === "replay" || comparison === false,
    "mission sessions cannot request comparison",
  );
  const inputs = mode === "mission"
    ? missionInputValues(result.inputs, catalog)
    : replayInputValues({ case_id: result.case_id, season: result.season }, catalog);
  const provenance = mode === "mission"
    ? missionProvenance({ source_sha256: result.source_sha256 }, catalog)
    : replayProvenance(
      { study_manifest_sha256: result.study_manifest_sha256 },
      catalog,
    );
  return {
    kind: SESSION_KIND,
    schema_version: SESSION_SCHEMA_VERSION,
    mode,
    inputs,
    comparison,
    provenance,
  };
}

function parseSession(text, catalog) {
  requireCondition(typeof text === "string", "session content must be text");
  requireCondition(
    text.length <= MAX_SESSION_TEXT,
    "session content exceeds 65536 characters",
  );
  let candidate;
  try {
    candidate = JSON.parse(text);
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new Error("Invalid session: content is not valid JSON");
    }
    throw error;
  }
  return validateSession(candidate, catalog);
}

function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function createSessionPanel(container, { onRestore = () => {} } = {}) {
  const content = element("div", "session-content");

  const saveButton = element("button", "app-button app-button-secondary", "Save session");
  saveButton.type = "button";
  saveButton.id = "session-save";
  saveButton.setAttribute("data-slot", "button");
  saveButton.disabled = true;

  const fileLabel = element("label", "session-file-label", "Restore session file");
  fileLabel.htmlFor = "session-file";
  const fileInput = document.createElement("input");
  fileInput.id = "session-file";
  fileInput.name = "session-file";
  fileInput.type = "file";
  fileInput.accept = "application/json,.json";
  fileInput.className = "session-file";
  fileInput.setAttribute("data-slot", "input");
  fileLabel.append(fileInput);

  const status = element(
    "p",
    "session-status",
    "Session files store inputs only; restoring requests fresh local results.",
  );
  status.id = "session-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");

  const actions = element("div", "session-actions");
  actions.append(saveButton, fileLabel);
  content.append(actions, status);
  container.querySelector(".session-loading")?.remove();
  container.append(content);

  let catalog = null;
  let snapshot = null;
  let comparison = false;
  let busy = false;
  let destroyed = false;
  let importToken = 0;
  const objectUrls = new Map();

  function releaseUrl(url) {
    const timer = objectUrls.get(url);
    if (timer !== undefined) window.clearTimeout(timer);
    URL.revokeObjectURL(url);
    objectUrls.delete(url);
  }

  function showStatus(message) {
    status.textContent = String(message);
    status.classList.remove("session-error");
    status.setAttribute("role", "status");
  }

  function showError(message) {
    status.textContent = String(message);
    status.classList.add("session-error");
    status.setAttribute("role", "alert");
  }

  function snapshotUsable() {
    if (!catalog || !snapshot) return false;
    try {
      makeSession(snapshot, catalog, { comparison });
      return true;
    } catch {
      return false;
    }
  }

  function refresh() {
    saveButton.disabled = busy || !snapshotUsable();
    fileInput.disabled = busy;
    content.setAttribute("aria-busy", String(busy));
  }

  function save() {
    let session;
    try {
      session = makeSession(snapshot, catalog, { comparison });
    } catch (error) {
      showError(error.message);
      return;
    }
    const text = JSON.stringify(session, null, 2);
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const filename = `wildfire-session-${session.mode}-${timestamp}.json`;
    const blob = new Blob([text], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    container.append(link);
    link.click();
    link.remove();
    objectUrls.set(url, window.setTimeout(() => releaseUrl(url), 0));
    showStatus(`Session saved as ${filename}.`);
  }

  async function importFile(file, token) {
    let session;
    try {
      const text = await file.text();
      if (destroyed || token !== importToken) return;
      session = parseSession(text, catalog);
    } catch (error) {
      if (!destroyed && token === importToken) showError(error.message);
      return;
    } finally {
      if (token === importToken) fileInput.value = "";
    }
    if (destroyed || token !== importToken) return;
    try {
      await onRestore(session);
      if (destroyed || token !== importToken) return;
      showStatus("Session accepted; requesting fresh local results");
    } catch (error) {
      if (!destroyed && token === importToken) {
        showError(error instanceof Error ? error.message : String(error));
      }
    }
  }

  function handleFile() {
    const token = ++importToken;
    const file = fileInput.files?.[0];
    if (!file) return;
    if (file.size > MAX_SESSION_BYTES) {
      fileInput.value = "";
      showError("Session file exceeds the 65536 byte limit.");
      return;
    }
    void importFile(file, token);
  }

  saveButton.addEventListener("click", save);
  fileInput.addEventListener("change", handleFile);

  refresh();

  return {
    setCatalog(nextCatalog) {
      catalog = nextCatalog;
      refresh();
    },
    setSnapshot(nextSnapshot, { comparison: nextComparison = false } = {}) {
      snapshot = isPlainObject(nextSnapshot) ? nextSnapshot : null;
      comparison = nextComparison === true;
      refresh();
    },
    setBusy(nextBusy) {
      busy = Boolean(nextBusy);
      refresh();
    },
    destroy() {
      destroyed = true;
      importToken += 1;
      saveButton.removeEventListener("click", save);
      fileInput.removeEventListener("change", handleFile);
      for (const url of [...objectUrls.keys()]) releaseUrl(url);
      content.remove();
    },
  };
}

export { makeSession, parseSession, createSessionPanel };

import { validateCase, validateCatalog, validatePair } from "./data_contract.js";

const SESSION_KIND = "wildfire-coverage-session";
const SESSION_SCHEMA_VERSION = 1;
const SESSION_KEYS = [
  "kind", "schema_version", "capture_sha256",
  "case_id", "compare_case_id", "selected_cell_index",
];
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

function catalogCaseId(value, catalog, label) {
  requireCondition(
    typeof value === "string" && value.length > 0,
    `${label} must be a nonempty case ID`,
  );
  const match = catalog.cases.find((item) => item.case_id === value);
  requireCondition(match !== undefined, `${label} must name a captured case`);
  return match.case_id;
}

function cellIndex(value, gridN, label) {
  if (value === null) return null;
  requireCondition(
    Number.isInteger(value) && value >= 0 && value < gridN * gridN,
    `${label} must be null or an integer index within the grid`,
  );
  return value;
}

function sessionObject(caseId, compareId, selected, captureSha256) {
  return {
    kind: SESSION_KIND,
    schema_version: SESSION_SCHEMA_VERSION,
    capture_sha256: captureSha256,
    case_id: caseId,
    compare_case_id: compareId,
    selected_cell_index: selected,
  };
}

function makeSession(snapshot, catalog, { selectedCellIndex = null } = {}) {
  requireCondition(
    isPlainObject(snapshot),
    "a received result snapshot is required",
  );
  const primary = validateCase(snapshot.primary, catalog);
  let compareId = null;
  if (snapshot.secondary !== null && snapshot.secondary !== undefined) {
    const pair = validatePair(primary, snapshot.secondary, catalog);
    compareId = pair.b.case.case_id;
  }
  const selected = cellIndex(
    selectedCellIndex, primary.grid_n, "selected_cell_index option",
  );
  return sessionObject(
    primary.case.case_id, compareId, selected, primary.capture_sha256,
  );
}

function validateSession(candidate, catalog) {
  const checked = validateCatalog(catalog);
  requireExactKeys(candidate, SESSION_KEYS, "session");
  requireCondition(candidate.kind === SESSION_KIND, "unsupported session kind");
  requireCondition(
    candidate.schema_version === SESSION_SCHEMA_VERSION,
    "unsupported session schema version",
  );
  requireCondition(
    candidate.capture_sha256 === checked.capture_sha256,
    "capture_sha256 must match the catalog fingerprint",
  );
  const caseId = catalogCaseId(candidate.case_id, checked, "case_id");
  const compareId = candidate.compare_case_id === null
    ? null
    : catalogCaseId(candidate.compare_case_id, checked, "compare_case_id");
  const selected = cellIndex(
    candidate.selected_cell_index, checked.grid_n, "selected_cell_index",
  );
  return sessionObject(caseId, compareId, selected, checked.capture_sha256);
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

function filenamePart(value) {
  const part = String(value).replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 120);
  return part.length > 0 ? part : "case";
}

function createCoverageSession(container, { onRestore = () => {} } = {}) {
  const content = element("div", "cov-session-content");

  const saveButton = element(
    "button", "cov-button cov-button-primary", "Save session",
  );
  saveButton.type = "button";
  saveButton.id = "cov-session-save";
  saveButton.disabled = true;

  const fileLabel = element(
    "label", "cov-session-file-label", "Restore session file",
  );
  fileLabel.htmlFor = "cov-session-file";
  const fileInput = document.createElement("input");
  fileInput.id = "cov-session-file";
  fileInput.name = "cov-session-file";
  fileInput.type = "file";
  fileInput.accept = "application/json,.json";
  fileInput.className = "cov-session-file";
  fileLabel.append(fileInput);

  const status = element(
    "p",
    "cov-session-status",
    "Session files store case selections only; restoring requests fresh local results.",
  );
  status.id = "cov-session-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");

  const actions = element("div", "cov-session-actions");
  actions.append(saveButton, fileLabel);
  content.append(actions, status);
  container.querySelector(".cov-session-loading")?.remove();
  container.append(content);

  let catalog = null;
  let snapshot = null;
  let selectedCellIndex = null;
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
    status.classList.remove("cov-error");
    status.setAttribute("role", "status");
  }

  function showError(message) {
    status.textContent = String(message);
    status.classList.add("cov-error");
    status.setAttribute("role", "alert");
  }

  function snapshotUsable() {
    if (!catalog || !snapshot) return false;
    try {
      makeSession(snapshot, catalog, { selectedCellIndex });
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
      session = makeSession(snapshot, catalog, { selectedCellIndex });
    } catch (error) {
      showError(error.message);
      return;
    }
    const text = JSON.stringify(session, null, 2);
    const filename = `wildfire-coverage-session-${filenamePart(session.case_id)}.json`;
    let url = null;
    let link = null;
    try {
      const blob = new Blob([text], { type: "application/json" });
      url = URL.createObjectURL(blob);
      link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.hidden = true;
      container.append(link);
      link.click();
      link.remove();
      objectUrls.set(url, window.setTimeout(() => releaseUrl(url), 0));
      showStatus(`Session saved as ${filename}.`);
    } catch {
      try {
        link?.remove();
      } catch {}
      if (url !== null) {
        try {
          releaseUrl(url);
        } catch {}
      }
      showError("Session download could not be started.");
    }
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
      showStatus("Restoring session with fresh local results...");
      await onRestore(session);
      if (destroyed || token !== importToken) return;
      showStatus("Session restored with fresh results.");
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
    setSnapshot(nextSnapshot, options = {}) {
      snapshot = isPlainObject(nextSnapshot) ? nextSnapshot : null;
      selectedCellIndex = isPlainObject(options)
          && options.selectedCellIndex !== undefined
        ? options.selectedCellIndex
        : null;
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

export { makeSession, parseSession, createCoverageSession };

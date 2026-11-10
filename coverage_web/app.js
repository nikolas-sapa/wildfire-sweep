import { createCoverageApi } from "./api.js";
import { createCoverageStore } from "./state.js";
import { createCoverageMap } from "./map.js";
import { createCoverageControls } from "./controls.js";
import { createCoverageTable } from "./table.js";
import { createCoverageDetails } from "./details.js";
import { createCoverageComparison } from "./comparison.js";
import { createCoverageLegend } from "./legend.js";
import { createCoverageExport } from "./export.js";
import { createCoverageSession } from "./session.js";
import { validateCatalog, validateCase, validatePair } from "./data_contract.js";

const elements = {
  controls: document.getElementById("cov-controls"),
  map: document.getElementById("cov-map"),
  compare: document.getElementById("cov-compare"),
  table: document.getElementById("cov-table"),
  details: document.getElementById("cov-details"),
  legend: document.getElementById("cov-legend"),
  export: document.getElementById("cov-export"),
  session: document.getElementById("cov-session"),
  status: document.getElementById("cov-status"),
};
if (Object.values(elements).some((element) => !element)) {
  throw new Error("Coverage Atlas page is missing a required element.");
}

const mounts = {
  controls: elements.controls.querySelector('[data-cov-mount="controls"]'),
  map: elements.map.querySelector('[data-cov-mount="map"]'),
  compare: elements.compare.querySelector('[data-cov-mount="compare"]'),
  table: elements.table.querySelector('[data-cov-mount="table"]'),
  details: elements.details.querySelector('[data-cov-mount="details"]'),
  legend: elements.legend.querySelector('[data-cov-mount="legend"]'),
  export: elements.export.querySelector('[data-cov-mount="export"]'),
  session: elements.session.querySelector('[data-cov-mount="session"]'),
};
if (Object.values(mounts).some((element) => !element)) {
  throw new Error("Coverage Atlas page is missing a component mount.");
}

const api = createCoverageApi();
const store = createCoverageStore({
  catalog: null,
  selectedCaseId: null,
  compareCaseId: null,
  primary: null,
  secondary: null,
  selectedCellIndex: null,
  primaryToken: 0,
  partnerToken: 0,
  primaryPending: false,
  partnerPending: false,
  primaryFailed: false,
  partnerFailed: false,
});

let controls = null;
let map = null;
let comparison = null;
let table = null;
let details = null;
let legend = null;
let exportPanel = null;
let sessionPanel = null;
let primaryToken = 0;
let partnerToken = 0;
let primaryController = null;
let partnerController = null;
let pendingCellIndex = null;
let renderedSelectionKey = "";
let renderedPayloadKey = "";

function setStatus(message, state = "ready") {
  elements.status.textContent = message;
  elements.status.dataset.state = state;
}

function describeError(error) {
  return error instanceof Error ? error.message : String(error);
}

function isAbort(error) {
  return Boolean(error) && typeof error === "object" && error.name === "AbortError";
}

function publishSnapshots(state) {
  const primaryReady = state.primary !== null
    && !state.primaryPending
    && !state.primaryFailed
    && state.primary.case.case_id === state.selectedCaseId;
  const pairReady = state.compareCaseId === null
    || (state.secondary !== null
      && !state.partnerPending
      && !state.partnerFailed
      && state.secondary.case.case_id === state.compareCaseId);
  const snapshot = primaryReady && pairReady
    ? {
        primary: state.primary,
        secondary: state.compareCaseId === null ? null : state.secondary,
      }
    : null;
  exportPanel?.setSnapshot(snapshot);
  sessionPanel?.setSnapshot(snapshot, { selectedCellIndex: state.selectedCellIndex });
}

function applyBusy(state) {
  const pending = state.primaryPending || state.partnerPending;
  controls?.setBusy(state.primaryPending);
  map?.setBusy(state.primaryPending);
  comparison?.setBusy(state.compareCaseId !== null && pending);
  exportPanel?.setBusy(pending);
  sessionPanel?.setBusy(pending);
}

function render(state) {
  const catalog = state.catalog;
  if (!catalog || !controls || !map || !comparison || !table || !details) return;
  publishSnapshots(state);
  applyBusy(state);
  const pairReady = state.primary !== null
    && state.primary.case.case_id === state.selectedCaseId
    && !state.primaryPending
    && !state.primaryFailed
    && state.compareCaseId !== null
    && state.secondary !== null
    && state.secondary.case.case_id === state.compareCaseId
    && !state.partnerPending
    && !state.partnerFailed;
  elements.map.hidden = pairReady;
  elements.compare.hidden = state.compareCaseId === null;
  const selectionKey = JSON.stringify([
    catalog.capture_sha256,
    state.selectedCaseId,
    state.compareCaseId,
  ]);
  if (selectionKey !== renderedSelectionKey) {
    renderedSelectionKey = selectionKey;
    controls.setSelection({
      case_id: state.selectedCaseId,
      compare_case_id: state.compareCaseId,
    });
    table.render(catalog, state.selectedCaseId);
  }
  const payloadKey = JSON.stringify([
    state.primary?.case?.case_id ?? null,
    state.secondary?.case?.case_id ?? null,
    state.selectedCellIndex,
    state.compareCaseId,
    state.primaryFailed,
    state.partnerFailed,
  ]);
  if (payloadKey === renderedPayloadKey) return;
  renderedPayloadKey = payloadKey;
  if (state.primary !== null) {
    map.render(state.primary, state.selectedCellIndex);
  }
  if (!state.primaryFailed) {
    details.render(state.primary, state.selectedCellIndex);
  }
  if (pairReady) {
    comparison.render(state.primary, state.secondary, state.selectedCellIndex);
  }
}

function selectCell(index) {
  const { catalog } = store.getState();
  if (!catalog) return;
  const cellCount = catalog.grid_n * catalog.grid_n;
  if (!Number.isInteger(index) || index < 0 || index >= cellCount) return;
  store.patch({ selectedCellIndex: index });
}

function invalidatePartner() {
  partnerToken += 1;
  if (partnerController !== null) {
    partnerController.abort();
    partnerController = null;
  }
}

function selectCase(caseId, { compareCaseId, cellIndex = null } = {}) {
  const state = store.getState();
  const catalog = state.catalog;
  if (!catalog || typeof caseId !== "string" || caseId === "") {
    return Promise.resolve(false);
  }
  if (!catalog.cases.some((item) => item.case_id === caseId)) {
    return Promise.resolve(false);
  }
  const token = ++primaryToken;
  if (primaryController !== null) {
    primaryController.abort();
    primaryController = null;
  }
  const controller = new AbortController();
  primaryController = controller;
  invalidatePartner();
  const nextCompare = compareCaseId === undefined ? state.compareCaseId : compareCaseId;
  pendingCellIndex = Number.isInteger(cellIndex) ? cellIndex : null;
  store.patch({
    selectedCaseId: caseId,
    compareCaseId: nextCompare,
    secondary: null,
    selectedCellIndex: null,
    primaryToken: token,
    partnerToken,
    primaryPending: true,
    primaryFailed: false,
    partnerPending: false,
    partnerFailed: false,
  });
  if (nextCompare !== null) comparison?.render(null, null);
  setStatus(`Loading coverage case ${caseId}...`, "loading");
  return loadPrimary(catalog, caseId, token, controller);
}

async function loadPrimary(catalog, caseId, token, controller) {
  try {
    const payload = await api.case(caseId, { signal: controller.signal });
    if (token !== primaryToken || store.getState().selectedCaseId !== caseId) return false;
    if (payload?.case?.case_id !== caseId) {
      throw new Error("Coverage response did not match the requested case ID.");
    }
    validateCase(payload, catalog);
    const cellIndex = pendingCellIndex;
    pendingCellIndex = null;
    store.patch({
      primary: payload,
      primaryPending: false,
      selectedCellIndex: cellIndex,
    });
    setStatus(`Coverage case loaded: ${payload.case.case_id}.`);
    const current = store.getState();
    if (current.compareCaseId !== null) {
      return await requestPartner(current.compareCaseId);
    }
    return true;
  } catch (error) {
    if (token !== primaryToken || isAbort(error)) return false;
    pendingCellIndex = null;
    store.patch({ primaryPending: false, primaryFailed: true });
    details.showError(describeError(error));
    setStatus(
      "Coverage case request failed; the last successful map is retained.",
      "error",
    );
    return false;
  }
}

async function requestPartner(caseId) {
  const state = store.getState();
  const catalog = state.catalog;
  if (
    !catalog
    || state.primary === null
    || state.primaryPending
    || state.primaryFailed
    || state.primary.case.case_id !== state.selectedCaseId
    || state.compareCaseId !== caseId
  ) {
    return false;
  }
  const token = ++partnerToken;
  if (partnerController !== null) partnerController.abort();
  const controller = new AbortController();
  partnerController = controller;
  store.patch({
    secondary: null,
    partnerToken: token,
    partnerPending: true,
    partnerFailed: false,
  });
  comparison?.render(null, null);
  setStatus(`Loading comparison case ${caseId}...`, "loading");
  try {
    const payload = await api.case(caseId, { signal: controller.signal });
    if (token !== partnerToken) return false;
    if (payload?.case?.case_id !== caseId) {
      throw new Error("Comparison response did not match the requested case ID.");
    }
    const current = store.getState();
    if (
      current.primary === null
      || current.primaryPending
      || current.primaryFailed
      || current.primary.case.case_id !== current.selectedCaseId
      || current.compareCaseId !== caseId
    ) {
      return false;
    }
    const pair = validatePair(current.primary, payload, catalog);
    store.patch({ secondary: pair.b, partnerPending: false });
    setStatus(
      `Comparison loaded: ${pair.a.case.case_id} + ${pair.b.case.case_id}.`,
    );
    return true;
  } catch (error) {
    if (token !== partnerToken || isAbort(error)) return false;
    store.patch({ partnerPending: false, partnerFailed: true });
    comparison.showError(describeError(error));
    setStatus(
      "Comparison request failed; the last successful map is retained.",
      "error",
    );
    return false;
  }
}

function handleCompare(caseIdOrNull) {
  const state = store.getState();
  const catalog = state.catalog;
  if (!catalog) return;
  const compareCaseId = typeof caseIdOrNull === "string" && caseIdOrNull !== ""
    ? caseIdOrNull
    : null;
  if (
    compareCaseId !== null
    && !catalog.cases.some((item) => item.case_id === compareCaseId)
  ) {
    return;
  }
  invalidatePartner();
  store.patch({
    compareCaseId,
    secondary: null,
    partnerToken,
    partnerPending: false,
    partnerFailed: false,
  });
  comparison?.render(null, null);
  if (compareCaseId === null) {
    setStatus("Comparison cleared.");
    return;
  }
  if (state.primaryFailed) return;
  if (
    state.primary === null
    || state.primaryPending
    || state.primary.case.case_id !== state.selectedCaseId
  ) {
    setStatus("Comparison will load after the primary case arrives.", "loading");
    return;
  }
  void requestPartner(compareCaseId);
}

async function restoreSession(session) {
  const { catalog } = store.getState();
  if (!catalog) {
    throw new Error("Session restore requires a loaded coverage catalog.");
  }
  if (session?.capture_sha256 !== catalog.capture_sha256) {
    throw new Error("Session capture fingerprint does not match the loaded catalog.");
  }
  const caseIds = new Set(catalog.cases.map((item) => item.case_id));
  if (!caseIds.has(session.case_id)) {
    throw new Error("Session names an unknown coverage case.");
  }
  const compareCaseId = session.compare_case_id ?? null;
  if (compareCaseId !== null && !caseIds.has(compareCaseId)) {
    throw new Error("Session names an unknown comparison case.");
  }
  const cellIndex = session.selected_cell_index ?? null;
  const cellCount = catalog.grid_n * catalog.grid_n;
  if (
    cellIndex !== null
    && (!Number.isInteger(cellIndex) || cellIndex < 0 || cellIndex >= cellCount)
  ) {
    throw new Error("Session selected cell is outside the capture grid.");
  }
  const restored = await selectCase(session.case_id, { compareCaseId, cellIndex });
  if (!restored) {
    throw new Error("Session restore could not load all selected coverage cases.");
  }
}

function setStartupFailure(error) {
  const message = describeError(error);
  for (const component of [controls, map, comparison]) {
    try {
      component?.setBusy(false);
    } catch {}
  }
  for (const panel of [exportPanel, sessionPanel]) {
    try {
      panel?.setSnapshot(null);
      panel?.setBusy(true);
    } catch {}
  }
  for (const element of [elements.export, elements.session]) {
    for (const button of element.querySelectorAll("button")) {
      button.disabled = true;
    }
  }
  try {
    details?.showError(message);
  } catch {}
  setStatus(`Coverage Atlas could not start: ${message}`, "error");
}

async function initialize() {
  setStatus("Loading the coverage catalog...", "loading");
  try {
    for (const mount of Object.values(mounts)) mount.replaceChildren();
    controls = createCoverageControls(mounts.controls, {
      onCase: (caseId) => selectCase(caseId),
      onCompare: handleCompare,
    });
    map = createCoverageMap(mounts.map, { onCell: selectCell });
    comparison = createCoverageComparison(mounts.compare, { onCell: selectCell });
    table = createCoverageTable(mounts.table, {
      onCase: (caseId) => selectCase(caseId),
    });
    details = createCoverageDetails(mounts.details);
    legend = createCoverageLegend(mounts.legend);
    exportPanel = createCoverageExport(mounts.export);
    sessionPanel = createCoverageSession(mounts.session, {
      onRestore: restoreSession,
    });
    store.subscribe((state) => {
      try {
        render(state);
      } catch (error) {
        setStartupFailure(error);
      }
    });
    details.render(null, null);
    exportPanel.setSnapshot(null);
    sessionPanel.setSnapshot(null);
    map.setBusy(true);
    controls.setBusy(true);
    exportPanel.setBusy(true);
    sessionPanel.setBusy(true);

    const catalog = validateCatalog(await api.catalog());
    controls.setCatalog(catalog);
    comparison.setCatalog(catalog);
    sessionPanel.setCatalog(catalog);
    legend.render(catalog);
    store.patch({ catalog });
    const loaded = await selectCase(catalog.cases[0].case_id, { compareCaseId: null });
    if (!loaded) throw new Error("The initial coverage case could not be loaded.");
  } catch (error) {
    setStartupFailure(error);
  }
}

void initialize();

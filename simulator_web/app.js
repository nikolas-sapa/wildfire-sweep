import { createApi, createStore } from "./state.js";
import { createMap } from "./map.js";
import { createControls } from "./controls.js";
import { createMissionPanel } from "./mission.js";
import { createReplayPanel } from "./replay.js";
import { createEvidencePanel } from "./evidence.js";
import { createExportButton } from "./export.js";
import { createSessionPanel, makeSession } from "./session.js";
import { createComparisonPanel } from "./comparison.js";
import { comparisonCases, pairReplays } from "./comparison_data.js";

const elements = {
  controls: document.getElementById("controls"),
  map: document.getElementById("map"),
  mission: document.getElementById("mission-results"),
  replay: document.getElementById("replay-controls"),
  evidence: document.getElementById("evidence"),
  export: document.getElementById("export"),
  session: document.getElementById("session"),
  status: document.getElementById("status"),
};
if (Object.values(elements).some((element) => !element)) {
  throw new Error("Mission Lab page is missing a required element.");
}

const api = createApi();
const store = createStore({
  mode: "mission",
  catalog: null,
  parameters: null,
  missionResult: null,
  replayResult: null,
  replayFrame: null,
  selectedCase: null,
  selectedSeason: 0,
  selectedAlertIndex: null,
  comparisonEnabled: false,
  comparisonPair: null,
});
let missionToken = 0;
let replayToken = 0;
let comparisonToken = 0;
let missionTimer = null;
let missionPending = false;
let replayPending = false;
let comparisonPending = false;
let currentSnapshot = null;
let emittedSnapshot = { base: undefined, pairKey: undefined, suppressed: undefined };

function setStatus(message, state = "ready") {
  elements.status.textContent = message;
  elements.status.dataset.state = state;
}

function validateResponseSnapshot(snapshot, catalog) {
  try {
    makeSession(snapshot, catalog);
  } catch (error) {
    if (/source_sha256|study_manifest_sha256/.test(error.message)) {
      throw new Error("Result provenance changed. Refresh Mission Lab before continuing.");
    }
    throw error;
  }
}

function selectAlert(index) {
  const current = store.getState();
  if (current.mode !== "replay" || !current.replayResult) return;
  replayPanel.selectAlert(index);
}

const missionPanel = createMissionPanel(elements.mission);
const replayPanel = createReplayPanel(elements.replay, {
  onRequest: ({ case_id, season }) => requestReplay(case_id, season),
  onFrame: (frame) => {
    store.patch({
      replayFrame: frame,
      selectedAlertIndex: frame.selected_alert_index,
    });
  },
  onAlert: selectAlert,
});
const controls = createControls(elements.controls, {
  onChange: (partial) => scheduleMission(partial),
  onReset: resetMission,
});

elements.map.querySelector(".map-loading")?.remove();
const primaryMapMount = document.createElement("div");
const comparisonMapMount = document.createElement("div");
comparisonMapMount.hidden = true;
elements.map.append(primaryMapMount, comparisonMapMount);

const map = createMap(primaryMapMount, {
  onTarget: (point) => {
    const current = store.getState();
    if (current.mode !== "mission" || !current.parameters) return;
    const parameters = { ...current.parameters, point_km: point };
    controls.setValues(parameters);
    scheduleMission(parameters);
  },
  onAlert: selectAlert,
});
const evidencePanel = createEvidencePanel(elements.evidence);
const exportButton = createExportButton(elements.export);
const sessionPanel = createSessionPanel(elements.session, {
  onRestore: restoreSession,
});
const comparisonPanel = createComparisonPanel(elements.replay, comparisonMapMount, {
  onToggle: toggleComparison,
  onAlert: selectAlert,
});
const modeButtons = [...document.querySelectorAll("[data-mode]")];
const panels = [...document.querySelectorAll("[data-panel]")];

function updateSessionBusy() {
  sessionPanel.setBusy(missionPending || replayPending || comparisonPending);
}

function invalidateComparison() {
  comparisonToken += 1;
  comparisonPending = false;
  updateSessionBusy();
  comparisonPanel.setPending(false);
}

function updateSnapshots(state) {
  const enabled = state.mode === "replay" && state.comparisonEnabled;
  const pair = enabled ? state.comparisonPair : null;
  const suppressed = currentSnapshot !== null && enabled && pair === null;
  const pairKey = pair === null
    ? null
    : `${pair.healthy.case_id}|${pair.outage.case_id}|${pair.healthy.season}`;
  if (
    emittedSnapshot.base === currentSnapshot &&
    emittedSnapshot.pairKey === pairKey &&
    emittedSnapshot.suppressed === suppressed
  ) {
    return;
  }
  emittedSnapshot = { base: currentSnapshot, pairKey, suppressed };
  let snapshot = suppressed ? null : currentSnapshot;
  if (snapshot !== null && pair !== null) {
    snapshot = {
      ...snapshot,
      comparison: { healthy: pair.healthy, outage: pair.outage },
    };
  }
  exportButton.setSnapshot(snapshot);
  sessionPanel.setSnapshot(snapshot, { comparison: pair !== null });
}

function renderMap(state) {
  const catalog = state.catalog;
  if (!catalog) return;
  if (state.mode === "replay") {
    const replay = state.replayResult;
    const frame = state.replayFrame;
    if (replay) {
      map.render({
        domain_side_km: replay.domain_side_km,
        bases: replay.bases,
        point_km: null,
        candidates: [],
        selected_base_id: null,
        alerts: frame?.alerts || [],
        selected_alert_index: state.selectedAlertIndex ?? frame?.selected_alert_index,
        mode: "replay",
      });
      return;
    }
    map.render({
      domain_side_km: catalog.domain_side_km,
      bases: [],
      point_km: null,
      candidates: [],
      selected_base_id: null,
      alerts: [],
      selected_alert_index: null,
      mode: "replay",
    });
    return;
  }
  if (state.missionResult) {
    map.render({ ...state.missionResult, mode: "mission" });
    return;
  }
  map.render({
    domain_side_km: catalog.domain_side_km,
    bases: catalog.layouts[String(catalog.defaults.n_bases)],
    point_km: catalog.defaults.point_km,
    candidates: [],
    selected_base_id: null,
    alerts: [],
    selected_alert_index: null,
    mode: "mission",
  });
}

function render(state) {
  for (const button of modeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode));
  }
  for (const panel of panels) {
    panel.hidden = panel.dataset.panel !== state.mode;
  }
  renderMap(state);
  const activePair = state.mode === "replay" && state.comparisonEnabled
    ? state.comparisonPair
    : null;
  primaryMapMount.hidden = activePair !== null;
  comparisonMapMount.hidden = activePair === null;
  comparisonPanel.render(activePair, activePair === null ? null : state.replayFrame);
  updateSnapshots(state);
}

store.subscribe(render);

async function sendMission(parameters, token) {
  if (token !== missionToken) return;
  missionPanel.setPending(true);
  try {
    const result = await api.mission(parameters);
    if (token !== missionToken) return;
    const snapshot = {
      mode: "mission",
      inputs: result.inputs,
      result,
      source_provenance: {
        source_sha256: result.source_sha256,
        assumptions: result.assumptions,
        limitations: result.limitations,
      },
    };
    validateResponseSnapshot(snapshot, store.getState().catalog);
    store.patch({ missionResult: result });
    controls.setValues(result.inputs);
    missionPanel.render(result);
    missionPanel.setPending(false);
    missionPending = false;
    updateSessionBusy();
    currentSnapshot = snapshot;
    updateSnapshots(store.getState());
    setStatus(`Mission response received: ${result.status}.`);
  } catch (error) {
    if (token !== missionToken) return;
    missionPanel.showError(error.message);
    missionPanel.setPending(false);
    missionPending = false;
    updateSessionBusy();
    currentSnapshot = null;
    updateSnapshots(store.getState());
    setStatus(
      "Mission request failed. The map retains its last successful response.",
      "error",
    );
  }
}

function scheduleMission(partial, immediate = false) {
  const current = store.getState();
  if (!current.catalog || !current.parameters) return;
  const parameters = { ...current.parameters, ...partial };
  const token = ++missionToken;
  if (missionTimer !== null) window.clearTimeout(missionTimer);
  missionPending = true;
  updateSessionBusy();
  currentSnapshot = null;
  store.patch({ parameters });
  missionPanel.setPending(true);
  setStatus("Requesting a single-alert mission result...", "loading");
  if (immediate) {
    missionTimer = null;
    void sendMission(parameters, token);
  } else {
    missionTimer = window.setTimeout(() => {
      missionTimer = null;
      void sendMission(parameters, token);
    }, 150);
  }
}

function resetMission() {
  const current = store.getState();
  if (!current.catalog) return;
  controls.setValues(current.catalog.defaults);
  scheduleMission(current.catalog.defaults);
}

async function loadComparison() {
  const current = store.getState();
  const catalog = current.catalog;
  const primary = current.replayResult;
  if (current.mode !== "replay" || !current.comparisonEnabled || !primary || !catalog) {
    return;
  }
  let cases;
  try {
    cases = comparisonCases(catalog, primary.case_id);
  } catch (error) {
    comparisonPanel.showError(error.message);
    setStatus("Captured comparison is unavailable for this case.", "error");
    return;
  }
  const partnerId = primary.case_id === cases.healthy.case_id
    ? cases.outage.case_id
    : cases.healthy.case_id;
  const token = ++comparisonToken;
  const replaySnapshot = replayToken;
  comparisonPending = true;
  updateSessionBusy();
  comparisonPanel.setPending(true);
  setStatus("Loading the captured partner season for comparison...", "loading");
  try {
    const partner = await api.replay(partnerId, primary.season);
    if (token !== comparisonToken || replaySnapshot !== replayToken) return;
    const pair = pairReplays(catalog, primary, partner);
    store.patch({ comparisonPair: pair });
    comparisonPending = false;
    updateSessionBusy();
    comparisonPanel.setPending(false);
    setStatus(
      `Captured comparison loaded: ${pair.cases.healthy.case_id} / ${pair.cases.outage.case_id}, season ${pair.healthy.season}.`,
    );
  } catch (error) {
    if (token !== comparisonToken || replaySnapshot !== replayToken) return;
    store.patch({ comparisonPair: null });
    comparisonPending = false;
    updateSessionBusy();
    comparisonPanel.setPending(false);
    comparisonPanel.showError(error.message);
    setStatus("Captured comparison request failed.", "error");
  }
}

function toggleComparison(enabled) {
  const current = store.getState();
  if (current.mode !== "replay" || !current.catalog) {
    comparisonPanel.setEnabled(false);
    return;
  }
  invalidateComparison();
  store.patch({
    comparisonEnabled: Boolean(enabled),
    comparisonPair: null,
  });
  if (!enabled) {
    setStatus("Captured comparison cleared.");
    return;
  }
  if (current.replayResult) {
    void loadComparison();
    return;
  }
  setStatus("Captured comparison will load after the replay arrives.", "loading");
}

async function requestReplay(caseId, season) {
  if (!caseId || !Number.isInteger(season)) return;
  const token = ++replayToken;
  invalidateComparison();
  replayPending = true;
  updateSessionBusy();
  currentSnapshot = null;
  store.patch({
    selectedCase: caseId,
    selectedSeason: season,
    replayResult: null,
    replayFrame: null,
    selectedAlertIndex: null,
    comparisonPair: null,
  });
  replayPanel.setBusy(true);
  setStatus("Loading the selected captured case and season...", "loading");
  try {
    const result = await api.replay(caseId, season);
    if (token !== replayToken) return;
    if (result.case_id !== caseId || result.season !== season) {
      throw new Error("Replay response did not match the requested case and season. Refresh Mission Lab.");
    }
    const snapshot = {
      mode: "replay",
      inputs: { case_id: result.case_id, season: result.season },
      result,
      source_provenance: {
        study_manifest_sha256: result.study_manifest_sha256,
      },
    };
    validateResponseSnapshot(snapshot, store.getState().catalog);
    store.patch({ replayResult: result });
    replayPanel.load(result);
    replayPending = false;
    updateSessionBusy();
    currentSnapshot = snapshot;
    updateSnapshots(store.getState());
    setStatus(`Captured replay loaded: ${result.case_id}, season ${result.season}.`);
    if (store.getState().comparisonEnabled) void loadComparison();
  } catch (error) {
    if (token !== replayToken) return;
    replayPanel.showError(error.message);
    replayPending = false;
    updateSessionBusy();
    currentSnapshot = null;
    updateSnapshots(store.getState());
    setStatus("Captured replay request failed.", "error");
  }
}

function restoreSession(session) {
  const current = store.getState();
  if (!current.catalog) {
    throw new Error("Session restore requires loaded catalog metadata.");
  }
  if (session.mode === "replay") {
    restoreReplaySession(session);
    return;
  }
  restoreMissionSession(session);
}

function restoreMissionSession(session) {
  invalidateComparison();
  store.patch({ comparisonEnabled: false, comparisonPair: null });
  comparisonPanel.setEnabled(false);
  if (store.getState().mode !== "mission") setMode("mission", { autoload: false });
  const activeControl = document.activeElement;
  if (activeControl instanceof HTMLElement && elements.controls.contains(activeControl)) {
    activeControl.blur();
  }
  controls.setValues(session.inputs);
  scheduleMission(session.inputs, true);
}

function restoreReplaySession(session) {
  const { catalog } = store.getState();
  const caseId = session.inputs.case_id;
  const season = session.inputs.season;
  if (session.comparison) {
    comparisonCases(catalog, caseId);
  }
  store.patch({
    comparisonEnabled: Boolean(session.comparison),
    comparisonPair: null,
    selectedCase: caseId,
    selectedSeason: season,
  });
  comparisonPanel.setEnabled(Boolean(session.comparison));
  if (store.getState().mode !== "replay") setMode("replay", { autoload: false });
  void requestReplay(caseId, season);
}

function setMode(mode, { autoload = true } = {}) {
  if (mode !== "mission" && mode !== "replay") return;
  const current = store.getState();
  if (current.mode === mode) return;
  if (missionTimer !== null) window.clearTimeout(missionTimer);
  missionTimer = null;
  missionToken += 1;
  missionPending = false;
  invalidateComparison();
  store.patch({ mode, comparisonPair: null });
  if (mode === "replay" && current.catalog) {
    missionPanel.setPending(false);
    if (autoload) {
      const caseId = current.selectedCase || current.catalog.study.cases[0].case_id;
      void requestReplay(caseId, current.selectedSeason || 0);
    }
  } else if (mode === "mission") {
    replayToken += 1;
    replayPending = false;
    updateSessionBusy();
    replayPanel.reset();
    replayPanel.setBusy(false);
    if (autoload && current.parameters) {
      scheduleMission(current.parameters);
    }
  }
}

for (const button of modeButtons) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}

async function initialize() {
  setStatus("Loading local model metadata and frozen study...", "loading");
  try {
    const catalog = await api.catalog();
    controls.setCatalog(catalog);
    controls.setValues(catalog.defaults);
    replayPanel.setCatalog(catalog);
    sessionPanel.setCatalog(catalog);
    evidencePanel.render(catalog);
    const firstCase = catalog.study.cases[0]?.case_id || null;
    store.patch({
      catalog,
      parameters: catalog.defaults,
      selectedCase: firstCase,
      selectedSeason: 0,
    });
    if (!firstCase) throw new Error("Frozen study has no replay cases.");
    setStatus("Local model metadata and frozen evidence loaded.");
    scheduleMission(catalog.defaults, true);
  } catch (error) {
    missionPanel.showError(error.message);
    replayPanel.showError(error.message);
    evidencePanel.render(null);
    setStatus(`Mission Lab could not start: ${error.message}`, "error");
  }
}

void initialize();

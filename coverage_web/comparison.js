import { createCoverageMap } from "./map.js";
import { validatePair } from "./data_contract.js";

function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function createCoverageComparison(container, { onCell = () => {} } = {}) {
  const root = element("div", "cov-comparison");
  const status = element("p", "cov-pair-status");
  status.setAttribute("role", "status");
  status.hidden = true;
  const error = element("p", "cov-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  const grid = element("div", "cov-pair-grid");
  grid.hidden = true;

  function createPane() {
    const pane = element("figure", "cov-pane");
    const caption = element("figcaption", "cov-pane-title");
    const mapHost = element("div", "cov-pane-map");
    pane.append(caption, mapHost);
    return { pane, caption, mapHost };
  }

  const primaryPane = createPane();
  const secondaryPane = createPane();
  grid.append(primaryPane.pane, secondaryPane.pane);
  root.append(status, error, grid);
  container.append(root);

  const primaryMap = createCoverageMap(primaryPane.mapHost, {
    onCell,
    idPrefix: "cov-compare-primary",
  });
  const secondaryMap = createCoverageMap(secondaryPane.mapHost, {
    onCell,
    idPrefix: "cov-compare-secondary",
  });

  let catalog = null;
  let busy = false;
  let pair = null;
  let statusText = "";

  function setStatus(text) {
    if (text === statusText) return;
    statusText = text;
    status.textContent = text;
    status.hidden = text === "";
  }

  function updateVisibility() {
    grid.hidden = pair === null;
  }

  function readyText() {
    return `Showing captured cases ${pair.a.case.case_id} and ${pair.b.case.case_id}.`;
  }

  function renderPane(pane, map, label, payload, selectedCellIndex) {
    pane.caption.textContent = `${label} case: ${payload.case.case_id}`;
    map.render(payload, selectedCellIndex);
  }

  function showError(message) {
    busy = false;
    root.removeAttribute("aria-busy");
    primaryMap.setBusy(false);
    secondaryMap.setBusy(false);
    pair = null;
    updateVisibility();
    setStatus("");
    error.textContent = String(message);
    error.hidden = false;
  }

  function render(primary, secondary, selectedCellIndex = null) {
    if (!primary || !secondary) {
      pair = null;
      if (!busy) setStatus("");
      updateVisibility();
      return;
    }
    if (!catalog) {
      showError("A validated coverage catalog is required before cases can be compared.");
      return;
    }
    let validated;
    try {
      validated = validatePair(primary, secondary, catalog);
    } catch (failure) {
      showError(failure instanceof Error ? failure.message : String(failure));
      return;
    }
    error.hidden = true;
    error.textContent = "";
    pair = validated;
    updateVisibility();
    const index = Number.isInteger(selectedCellIndex) ? selectedCellIndex : null;
    renderPane(primaryPane, primaryMap, "Primary", pair.a, index);
    renderPane(secondaryPane, secondaryMap, "Comparison", pair.b, index);
    if (!busy) setStatus(readyText());
    updateVisibility();
  }

  function setCatalog(nextCatalog) {
    catalog = nextCatalog ?? null;
  }

  function setBusy(nextBusy) {
    busy = Boolean(nextBusy);
    primaryMap.setBusy(busy);
    secondaryMap.setBusy(busy);
    if (busy) {
      root.setAttribute("aria-busy", "true");
      error.hidden = true;
      error.textContent = "";
      setStatus("Loading paired coverage cases...");
      return;
    }
    root.removeAttribute("aria-busy");
    setStatus(pair !== null ? readyText() : "");
  }

  function destroy() {
    primaryMap.destroy();
    secondaryMap.destroy();
    root.remove();
    catalog = null;
    pair = null;
  }

  return { render, setBusy, setCatalog, showError, destroy };
}

export { createCoverageComparison };

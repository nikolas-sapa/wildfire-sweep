import { createMap } from "./map.js";

function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function createComparisonPanel(
  controlsContainer,
  mapContainer,
  { onToggle = () => {}, onAlert = () => {} } = {},
) {
  const controls = element("div", "comparison-controls");
  const toggleLabel = element("label", "comparison-toggle");
  toggleLabel.htmlFor = "comparison-toggle";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.id = "comparison-toggle";
  checkbox.name = "comparison-toggle";
  checkbox.className = "comparison-checkbox";
  toggleLabel.append(
    checkbox,
    element("span", "comparison-toggle-text", "Compare healthy / outage"),
  );
  const status = element("p", "comparison-status");
  status.setAttribute("role", "status");
  status.hidden = true;
  const error = element("p", "comparison-error");
  error.setAttribute("role", "alert");
  error.hidden = true;
  controls.append(toggleLabel, status, error);
  controlsContainer.append(controls);

  const pairWrapper = element("div", "comparison-pair");
  pairWrapper.hidden = true;
  const pairGrid = element("div", "comparison-maps");
  const legend = element(
    "p",
    "comparison-legend",
    "Legend: circle = real alert; diamond = false alert; dashed outline = late; cross = unreachable.",
  );

  function createPane(modifier) {
    const pane = element("figure", `comparison-pane ${modifier}`);
    const caption = element("figcaption", "comparison-pane-title");
    const mapHost = element("div", "comparison-map");
    const details = element("p", "comparison-selection");
    pane.append(caption, mapHost, details);
    return { pane, caption, mapHost, details };
  }

  const healthyPane = createPane("comparison-pane-healthy");
  const outagePane = createPane("comparison-pane-outage");
  pairGrid.append(healthyPane.pane, outagePane.pane);
  pairWrapper.append(pairGrid, legend);
  mapContainer.append(pairWrapper);

  const healthyMap = createMap(healthyPane.mapHost, {
    onAlert,
    idPrefix: "comparison-healthy",
  });
  const outageMap = createMap(outagePane.mapHost, {
    onAlert,
    idPrefix: "comparison-outage",
  });

  let enabled = false;
  let pending = false;
  let pair = null;
  let frame = null;
  let statusText = "";

  function readyText() {
    return `Showing captured healthy case ${pair.healthy.case_id} and outage case ${pair.outage.case_id}.`;
  }

  function setStatus(text) {
    if (text === statusText) return;
    statusText = text;
    status.textContent = text;
    status.hidden = text === "";
  }

  function updateVisibility() {
    pairWrapper.hidden = !(enabled && pair !== null);
  }

  function describeAlert(payload, index, currentS) {
    const alert = (payload.alerts || []).find((item) => item.index === index);
    if (!alert) {
      return "The selected alert is not part of this captured case.";
    }
    if (alert.alert_s > currentS) {
      return `Alert ${index + 1} has not been reached at the current shared time.`;
    }
    const response = alert.response_s === null
      ? "Unreachable"
      : `${alert.response_s.toFixed(1)} s`;
    return `Alert ${index + 1} at ${Math.floor(alert.alert_s)} s: ${alert.status}, response ${response}`;
  }

  function renderPane(pane, map, label, payload, currentS, selectedIndex) {
    pane.caption.textContent = `${label} case: ${payload.case_id}`;
    const visibleAlerts = (payload.alerts || []).filter(
      (alert) => Number(alert.alert_s) <= currentS,
    );
    map.render({
      mode: "replay",
      outcome_markers: true,
      domain_side_km: payload.domain_side_km,
      bases: payload.bases || [],
      point_km: null,
      candidates: [],
      selected_base_id: null,
      alerts: visibleAlerts,
      selected_alert_index: selectedIndex,
    });
    pane.details.textContent = selectedIndex === null
      ? "Select a captured alert to inspect its recorded outcome."
      : describeAlert(payload, selectedIndex, currentS);
  }

  function render(nextPair = null, nextFrame = null) {
    pair = nextPair && typeof nextPair === "object" ? nextPair : null;
    frame = nextFrame && typeof nextFrame === "object" ? nextFrame : null;
    if (
      !pair
      || typeof pair.healthy !== "object"
      || typeof pair.outage !== "object"
      || pair.healthy === null
      || pair.outage === null
    ) {
      pair = null;
      if (!pending) setStatus("");
      updateVisibility();
      return;
    }
    error.hidden = true;
    error.textContent = "";
    const currentS = Number.isFinite(Number(frame?.current_s))
      ? Number(frame.current_s)
      : 0;
    const selectedIndex = Number.isInteger(frame?.selected_alert_index)
      ? frame.selected_alert_index
      : null;
    renderPane(
      healthyPane,
      healthyMap,
      "Healthy",
      pair.healthy,
      currentS,
      selectedIndex,
    );
    renderPane(
      outagePane,
      outageMap,
      "Outage",
      pair.outage,
      currentS,
      selectedIndex,
    );
    if (!pending) setStatus(readyText());
    updateVisibility();
  }

  function setEnabled(nextEnabled) {
    enabled = Boolean(nextEnabled);
    checkbox.checked = enabled;
    if (!enabled) {
      pair = null;
      frame = null;
      error.hidden = true;
      error.textContent = "";
    }
    updateVisibility();
    if (!pending) setStatus(enabled && pair ? readyText() : "");
  }

  function setPending(nextPending) {
    pending = Boolean(nextPending);
    if (pending) {
      controls.setAttribute("aria-busy", "true");
      error.hidden = true;
      error.textContent = "";
      setStatus("Loading the paired captured case and season...");
      return;
    }
    controls.removeAttribute("aria-busy");
    setStatus(pair !== null ? readyText() : "");
  }

  function showError(message) {
    pending = false;
    controls.removeAttribute("aria-busy");
    pair = null;
    frame = null;
    updateVisibility();
    setStatus("");
    error.textContent = String(message);
    error.hidden = false;
  }

  function handleToggle() {
    enabled = checkbox.checked;
    if (!enabled) {
      pair = null;
      frame = null;
      error.hidden = true;
      error.textContent = "";
      setStatus("");
    }
    updateVisibility();
    onToggle(enabled);
  }

  checkbox.addEventListener("change", handleToggle);

  return {
    setEnabled,
    setPending,
    render,
    showError,
    destroy() {
      checkbox.removeEventListener("change", handleToggle);
      healthyMap.destroy();
      outageMap.destroy();
      controls.remove();
      pairWrapper.remove();
    },
  };
}

export { createComparisonPanel };

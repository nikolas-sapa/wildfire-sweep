const SECONDS_PER_DAY = 86400;
const DEFAULT_PLAYBACK_SPEED = 432000;

function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function createReplayPanel(container, { onRequest = () => {}, onFrame = () => {}, onAlert = () => {} } = {}) {
  const content = element("div", "replay-content");
  const caseLabel = element("label", "replay-label", "Captured case");
  caseLabel.htmlFor = "replay-case";
  const caseSelect = document.createElement("select");
  caseSelect.id = "replay-case";
  caseSelect.className = "replay-select";
  caseSelect.setAttribute("data-slot", "input");
  caseLabel.append(caseSelect);

  const seasonLabel = element("label", "replay-label", "Season index");
  seasonLabel.htmlFor = "replay-season";
  const seasonInput = document.createElement("input");
  seasonInput.id = "replay-season";
  seasonInput.type = "number";
  seasonInput.min = "0";
  seasonInput.step = "1";
  seasonInput.value = "0";
  seasonInput.className = "replay-input";
  seasonInput.setAttribute("data-slot", "input");
  seasonLabel.append(seasonInput);

  const requestButton = element("button", "app-button", "Load season");
  requestButton.type = "button";
  requestButton.setAttribute("data-slot", "button");
  requestButton.setAttribute("data-size", "large");

  const playButton = element("button", "app-button app-button-secondary", "Play");
  playButton.type = "button";
  playButton.setAttribute("data-slot", "button");
  playButton.id = "replay-play";
  playButton.setAttribute("aria-label", "Play replay");
  playButton.setAttribute("aria-pressed", "false");

  const resetButton = element("button", "app-button app-button-secondary", "Reset");
  resetButton.type = "button";
  resetButton.setAttribute("data-slot", "button");

  const speedLabel = element("label", "replay-label", "Playback speed");
  speedLabel.htmlFor = "replay-speed";
  const speedSelect = document.createElement("select");
  speedSelect.id = "replay-speed";
  speedSelect.className = "replay-select";
  speedSelect.setAttribute("data-slot", "input");
  for (const [value, label] of [
    ["216000", "0.5x"],
    ["432000", "1x"],
    ["864000", "2x"],
  ]) {
    const option = element("option", "", label);
    option.value = value;
    speedSelect.append(option);
  }
  speedSelect.value = String(DEFAULT_PLAYBACK_SPEED);
  speedLabel.append(speedSelect);

  const timeLabel = element("label", "replay-label", "Season time (simulated seconds)");
  timeLabel.htmlFor = "replay-scrub";
  const scrubber = document.createElement("input");
  scrubber.id = "replay-scrub";
  scrubber.type = "range";
  scrubber.min = "0";
  scrubber.max = "0";
  scrubber.step = "any";
  scrubber.value = "0";
  scrubber.className = "replay-scrubber";
  scrubber.setAttribute("data-slot", "input");
  timeLabel.append(scrubber);
  const timeValue = element("output", "replay-time", "0 s");
  timeValue.id = "replay-time";

  const fields = element("div", "replay-fields");
  fields.append(caseLabel, seasonLabel, requestButton);
  const transport = element("div", "replay-transport");
  transport.append(playButton, resetButton, speedLabel);
  const counts = element("dl", "replay-counts");
  counts.id = "replay-counts";
  const events = element("div", "replay-events");
  events.id = "replay-alerts";
  const eventHeading = element("h3", "replay-subheading", "Captured alerts");
  const playback = element("div", "replay-playback");
  playback.append(timeLabel, timeValue);
  content.append(fields, transport, counts, playback, eventHeading, events);
  container.querySelector(".replay-loading")?.remove();
  container.append(content);

  let cases = [];
  let data = null;
  let seasonCount = 0;
  let currentSeconds = 0;
  let selectedIndex = null;
  let speed = DEFAULT_PLAYBACK_SPEED;
  let durationSeconds = 0;
  let playing = false;
  let animationFrame = null;
  let lastFrameTime = 0;
  let lastPublishedTime = 0;

  function emitFrame() {
    if (!data) return;
    onFrame({
      alerts: data.alerts.filter((alert) => alert.alert_s <= currentSeconds),
      current_s: currentSeconds,
      selected_alert_index: selectedIndex,
    });
  }

  function selectAlert(index) {
    const alert = data?.alerts?.find((item) => item.index === index);
    if (!alert) return;
    selectedIndex = index;
    currentSeconds = Math.max(currentSeconds, alert.alert_s);
    scrubber.value = String(currentSeconds);
    timeValue.textContent = `${Math.floor(currentSeconds)} s`;
    renderEvents();
    emitFrame();
  }

  function setPlayState(nextPlaying) {
    playing = nextPlaying;
    playButton.textContent = playing ? "Pause" : "Play";
    playButton.setAttribute("aria-label", playing ? "Pause replay" : "Play replay");
    playButton.setAttribute("aria-pressed", String(playing));
  }

  function stopPlayback() {
    setPlayState(false);
    if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    animationFrame = null;
    lastFrameTime = 0;
  }

  function tick(now) {
    if (!playing || !data) return;
    if (lastFrameTime === 0) lastFrameTime = now;
    const elapsed = (now - lastFrameTime) / 1000;
    currentSeconds = Math.min(
      durationSeconds,
      currentSeconds + elapsed * speed,
    );
    lastFrameTime = now;
    scrubber.value = String(currentSeconds);
    timeValue.textContent = `${Math.floor(currentSeconds)} s`;
    if (now - lastPublishedTime >= 100 || currentSeconds >= durationSeconds) {
      emitFrame();
      lastPublishedTime = now;
    }
    if (currentSeconds >= durationSeconds) {
      stopPlayback();
      emitFrame();
      return;
    }
    animationFrame = requestAnimationFrame(tick);
  }

  function play() {
    if (!data || playing) return;
    if (currentSeconds >= durationSeconds) currentSeconds = 0;
    setPlayState(true);
    lastFrameTime = 0;
    lastPublishedTime = 0;
    animationFrame = requestAnimationFrame(tick);
  }

  function requestSelectedSeason() {
    if (!caseSelect.value || seasonInput.value === "") return;
    const season = Number(seasonInput.value);
    if (!Number.isInteger(season) || season < 0 || season >= seasonCount) {
      seasonInput.setAttribute("aria-invalid", "true");
      return;
    }
    seasonInput.removeAttribute("aria-invalid");
    stopPlayback();
    setBusy(true);
    onRequest({ case_id: caseSelect.value, season });
  }

  function renderCounts() {
    counts.replaceChildren();
    for (const [key, value] of Object.entries(data?.counts || {})) {
      const row = element("div", "replay-count");
      row.append(
        element("dt", "", key.replaceAll("_", " ")),
        element("dd", "", value === null ? "n/a" : String(value)),
      );
      counts.append(row);
    }
  }

  function renderEvents() {
    events.replaceChildren();
    for (const alert of data?.alerts || []) {
      const button = element(
        "button",
        `replay-event${alert.index === selectedIndex ? " replay-event-selected" : ""}`,
      );
      button.type = "button";
      button.setAttribute("data-slot", "button");
      button.setAttribute("data-variant", "secondary");
      button.setAttribute("aria-pressed", String(alert.index === selectedIndex));
      button.setAttribute(
        "aria-label",
        `Select captured alert ${alert.index + 1}, ${alert.status}`,
      );
      const details = element("span", "replay-event-details");
      details.append(
        element("strong", "", `Alert ${alert.index + 1}`),
        element("span", "", `${Math.floor(alert.alert_s)} s`),
      );
      button.append(details, element("span", "replay-event-status", String(alert.status)));
      button.addEventListener("click", () => {
        onAlert(alert.index);
      });
      events.append(button);
    }
  }

  function setCatalog(catalog) {
    const study = catalog?.study;
    cases = Array.isArray(study?.cases) ? study.cases : [];
    seasonCount = Number(study?.heldout_seasons);
    if (!Number.isInteger(seasonCount) || seasonCount < 1) {
      throw new Error("Frozen catalog has no held-out seasons.");
    }
    caseSelect.replaceChildren();
    for (const item of cases) {
      const option = element("option", "", item.case_id);
      option.value = item.case_id;
      caseSelect.append(option);
    }
    if (cases.length === 0) {
      throw new Error("Frozen catalog has no replay cases.");
    }
    seasonInput.max = String(seasonCount - 1);
    caseSelect.value = cases[0].case_id;
  }

  function load(nextData) {
    stopPlayback();
    data = nextData;
    currentSeconds = 0;
    selectedIndex = null;
    const seasonDays = Number(data.season_days);
    if (!Number.isFinite(seasonDays) || seasonDays <= 0) {
      throw new Error("Replay response has an invalid season duration.");
    }
    durationSeconds = seasonDays * SECONDS_PER_DAY;
    scrubber.max = String(durationSeconds);
    scrubber.value = "0";
    seasonInput.value = String(data.season);
    caseSelect.value = data.case_id;
    timeValue.textContent = "0 s";
    renderCounts();
    renderEvents();
    setBusy(false);
    emitFrame();
  }

  function setBusy(busy) {
    content.setAttribute("aria-busy", String(Boolean(busy)));
    let pending = content.querySelector(".replay-pending");
    if (busy && !pending) {
      pending = element("p", "replay-pending", "Loading the selected captured season...");
      pending.setAttribute("role", "status");
      content.prepend(pending);
    } else if (!busy) {
      pending?.remove();
    }
    content.querySelectorAll("input, select, button").forEach((control) => {
      control.disabled = Boolean(busy);
    });
  }

  function showError(message) {
    stopPlayback();
    setBusy(false);
    const error = element("p", "replay-error", String(message));
    error.setAttribute("role", "alert");
    events.replaceChildren(error);
  }

  function reset() {
    stopPlayback();
    currentSeconds = 0;
    selectedIndex = null;
    timeValue.textContent = "0 s";
    scrubber.value = "0";
    renderEvents();
    emitFrame();
  }

  function handleScrub() {
    stopPlayback();
    currentSeconds = Number(scrubber.value);
    timeValue.textContent = `${Math.floor(currentSeconds)} s`;
    emitFrame();
  }

  function handleSpeedChange() {
    speed = Number(speedSelect.value);
  }

  function handlePlay() {
    if (playing) stopPlayback();
    else play();
  }

  playButton.addEventListener("click", handlePlay);
  resetButton.addEventListener("click", reset);
  requestButton.addEventListener("click", requestSelectedSeason);
  caseSelect.addEventListener("change", requestSelectedSeason);
  seasonInput.addEventListener("change", requestSelectedSeason);
  scrubber.addEventListener("input", handleScrub);
  speedSelect.addEventListener("change", handleSpeedChange);

  return {
    setCatalog,
    load,
    setBusy,
    showError,
    reset,
    selectAlert,
    destroy() {
      stopPlayback();
      playButton.removeEventListener("click", handlePlay);
      resetButton.removeEventListener("click", reset);
      requestButton.removeEventListener("click", requestSelectedSeason);
      caseSelect.removeEventListener("change", requestSelectedSeason);
      seasonInput.removeEventListener("change", requestSelectedSeason);
      scrubber.removeEventListener("input", handleScrub);
      speedSelect.removeEventListener("change", handleSpeedChange);
      content.remove();
    },
  };
}

export { createReplayPanel };

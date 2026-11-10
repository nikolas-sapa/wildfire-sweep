function node(name, className, text = "") {
  const element = document.createElement(name);
  if (className) element.className = className;
  if (text !== "") element.textContent = text;
  return element;
}

function valueText(value, unit = "") {
  if (value === null || value === undefined) return "Unreachable";
  const number = Number(value);
  if (!Number.isFinite(number)) return "Unavailable";
  return `${number.toFixed(1)}${unit}`;
}

function flagText(value) {
  if (value === true) return "Pass";
  if (value === false) return "Fail";
  return "n/a";
}

function addValue(parent, label, value) {
  const row = node("div", "mission-value");
  row.append(node("dt", "", label), node("dd", "", value));
  parent.append(row);
}

function createMissionPanel(container) {
  const content = node("div", "mission-content");
  container.querySelector(".mission-loading")?.remove();
  container.append(content);

  function render(result) {
    content.replaceChildren();
    container.removeAttribute("aria-busy");
    if (!result) {
      content.append(node("p", "mission-loading", "Waiting for a local mission result."));
      return;
    }
    const summary = node("dl", "mission-summary");
    addValue(summary, "Dispatch status", String(result.status));
    addValue(summary, "Alert-to-arrival", valueText(result.response_s, " s"));
    addValue(
      summary,
      "Selected base",
      result.selected_base_id === null ? "No eligible base" : `Base ${result.selected_base_id}`,
    );
    addValue(
      summary,
      "Within 15 minutes",
      result.within_15min === true ? "Yes" : "No",
    );
    addValue(summary, "Usable airborne budget", valueText(result.usable_airborne_s, " s"));
    content.append(summary);

    const candidates = node("div", "mission-candidates");
    candidates.append(node("h3", "mission-subheading", "Per-base candidates"));
    const table = node("table", "mission-candidate-table");
    const head = node("thead");
    const headerRow = node("tr");
    for (const label of [
      "Base",
      "Outbound",
      "Return",
      "Airborne",
      "Arrival",
      "Flight",
      "Battery",
      "Eligible",
      "Reason",
    ]) {
      headerRow.append(node("th", "", label));
    }
    head.append(headerRow);
    const body = node("tbody");
    for (const candidate of result.candidates || []) {
      const row = node("tr");
      const reasons = {
        offline: "Base unavailable",
        weather: "Wind limit",
        flight: "Flight-time limit",
        battery: "Battery reserve",
        eligible: "Eligible",
      };
      const reason = reasons[candidate.reason] || String(candidate.reason || "Not eligible");
      for (const value of [
        String(candidate.base_id),
        valueText(candidate.outbound_s, " s"),
        valueText(candidate.return_s, " s"),
        valueText(candidate.airborne_s, " s"),
        valueText(candidate.arrival_s, " s"),
        flagText(candidate.flight_ok),
        flagText(candidate.battery_ok),
        flagText(candidate.eligible),
        reason,
      ]) {
        row.append(node("td", "", value));
      }
      body.append(row);
    }
    table.append(head, body);
    candidates.append(table);
    content.append(candidates);

    if (Array.isArray(result.limitations) && result.limitations.length) {
      const limits = node("ul", "mission-limitations");
      for (const limitation of result.limitations) {
        limits.append(node("li", "", String(limitation)));
      }
      content.append(limits);
    }
  }

  function setPending(pending) {
    if (pending) {
      container.setAttribute("aria-busy", "true");
      let message = content.querySelector(".mission-pending");
      if (!message) {
        message = node("p", "mission-pending", "Requesting a new local mission result...");
        message.setAttribute("role", "status");
        content.prepend(message);
      }
    } else {
      container.removeAttribute("aria-busy");
      content.querySelector(".mission-pending")?.remove();
    }
  }

  function showError(message) {
    container.removeAttribute("aria-busy");
    content.replaceChildren();
    const error = node("p", "mission-error", String(message));
    error.setAttribute("role", "alert");
    content.append(error);
  }

  return {
    render,
    setPending,
    showError,
    destroy() {
      content.remove();
      container.removeAttribute("aria-busy");
    },
  };
}

export { createMissionPanel };

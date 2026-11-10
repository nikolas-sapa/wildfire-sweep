function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function text(value, fallback = "Unavailable") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : fallback;
  }
  return String(value);
}

function unitText(value, unit) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
  return `${value}${unit}`;
}

function outcomeText(value) {
  if (typeof value !== "string" || value === "") return "Unavailable";
  return value.replaceAll("_", " ");
}

function addItem(list, label, value) {
  const item = element("div", "cov-detail-item");
  item.append(element("dt", "", label), element("dd", "", value));
  list.append(item);
}

function createSection(title) {
  const section = element("section", "cov-detail-section");
  section.append(element("h3", "cov-detail-heading", title));
  const list = element("dl", "cov-detail-list");
  section.append(list);
  return { section, list };
}

function usablePayload(payload) {
  return payload !== null
    && typeof payload === "object"
    && payload.case !== null
    && typeof payload.case === "object"
    && Array.isArray(payload.cells);
}

function createCoverageDetails(container) {
  const root = element("div", "cov-details");
  root.setAttribute("role", "region");
  root.setAttribute("aria-label", "Coverage details");

  const empty = element(
    "p",
    "cov-status",
    "Select a case to inspect its stored coverage details.",
  );
  empty.setAttribute("role", "status");

  const error = element("p", "cov-error");
  error.setAttribute("role", "alert");
  error.hidden = true;

  const detail = element("div", "cov-detail");
  detail.setAttribute("role", "group");
  detail.setAttribute("aria-label", "Stored case and cell values");
  detail.hidden = true;

  root.append(empty, error, detail);
  container.append(root);

  function render(payload = null, selectedCellIndex = null) {
    detail.replaceChildren();
    if (payload === null || payload === undefined) {
      detail.hidden = true;
      error.hidden = true;
      empty.hidden = false;
      return;
    }
    if (!usablePayload(payload)) {
      detail.hidden = true;
      empty.hidden = true;
      error.textContent = "The received coverage payload is incomplete.";
      error.hidden = false;
      return;
    }
    empty.hidden = true;
    error.hidden = true;
    detail.hidden = false;

    const descriptor = payload.case;
    const summary = descriptor.summary;
    const offline = Array.isArray(descriptor.offline_bases)
      ? descriptor.offline_bases
      : [];

    detail.append(element(
      "p",
      "cov-detail-note",
      "Stored capture values only. Coordinates are model-space cell centers, "
        + "not a real map; unavailable values are never shown as zero.",
    ));

    const caseSection = createSection("Selected case");
    addItem(caseSection.list, "Case ID", text(descriptor.case_id));
    addItem(caseSection.list, "Profile", text(descriptor.profile));
    addItem(caseSection.list, "Bases", text(descriptor.n_bases));
    addItem(
      caseSection.list,
      "Offline bases",
      offline.length ? offline.map((id) => text(id)).join(", ") : "None",
    );
    const wind = Array.isArray(descriptor.wind_mps)
      && descriptor.wind_mps.length === 2
      ? `${text(descriptor.wind_mps[0])}, ${text(descriptor.wind_mps[1])} m/s`
      : "Unavailable";
    addItem(caseSection.list, "Wind (east, north)", wind);
    addItem(
      caseSection.list,
      "Wind speed",
      unitText(descriptor.wind_speed_mps, " m/s"),
    );
    addItem(
      caseSection.list,
      "Heading",
      descriptor.heading_deg === null
        ? "Calm"
        : descriptor.heading_deg === undefined
          ? "Unavailable"
          : `${text(descriptor.heading_deg)} deg`,
    );
    detail.append(caseSection.section);

    const modelSection = createSection("Model parameters");
    addItem(modelSection.list, "Airspeed", unitText(descriptor.airspeed_mps, " m/s"));
    addItem(modelSection.list, "Endurance", unitText(descriptor.endurance_min, " min"));
    addItem(modelSection.list, "Reserve fraction", text(descriptor.reserve_fraction));
    addItem(
      modelSection.list,
      "Launch latency",
      unitText(descriptor.launch_latency_s, " s"),
    );
    addItem(
      modelSection.list,
      "Timely threshold",
      unitText(payload.timely_threshold_s, " s"),
    );
    addItem(modelSection.list, "Domain side", unitText(payload.domain_side_km, " km"));
    addItem(
      modelSection.list,
      "Grid",
      Number.isFinite(payload.grid_n)
        ? `${payload.grid_n} x ${payload.grid_n} cell centers`
        : "Unavailable",
    );
    addItem(modelSection.list, "Study", text(payload.study_id));
    addItem(modelSection.list, "Capture SHA-256", text(payload.capture_sha256));
    detail.append(modelSection.section);

    const summarySection = createSection("Stored outcome summary");
    const summaryFields = [
      ["Timely cells", summary?.timely_cells],
      ["Late cells", summary?.late_cells],
      ["Unreachable cells", summary?.unreachable_cells],
      ["Weather-closed cells", summary?.weather_closed_cells],
      ["Total cells", summary?.total_cells],
      ["Timely area fraction", summary?.timely_area_fraction],
      ["Reachable area fraction", summary?.reachable_area_fraction],
    ];
    for (const [label, value] of summaryFields) {
      addItem(summarySection.list, label, text(value));
    }
    detail.append(summarySection.section);

    const baseSection = createSection("Available bases");
    if (!Array.isArray(payload.bases)) {
      addItem(baseSection.list, "Available base IDs", "Unavailable");
    } else {
      const available = payload.bases
        .filter((base) => base && base.available === true)
        .map((base) => text(base.id));
      addItem(
        baseSection.list,
        "Available base IDs",
        available.length ? available.join(", ") : "None",
      );
    }
    detail.append(baseSection.section);

    const cellSection = createSection("Selected cell");
    if (selectedCellIndex === null || selectedCellIndex === undefined) {
      cellSection.section.append(element(
        "p",
        "cov-detail-note",
        "Select a cell on the map to inspect its stored outcome.",
      ));
    } else {
      const cell = Number.isInteger(selectedCellIndex)
        ? payload.cells[selectedCellIndex]
        : undefined;
      if (!cell || cell.index !== selectedCellIndex) {
        cellSection.section.append(element(
          "p",
          "cov-detail-note",
          "The selected cell is not part of the received payload.",
        ));
      } else {
        addItem(cellSection.list, "Index", text(cell.index));
        addItem(cellSection.list, "Row", text(cell.row));
        addItem(cellSection.list, "Column", text(cell.column));
        addItem(cellSection.list, "Center east", unitText(cell.x_km, " km"));
        addItem(cellSection.list, "Center north", unitText(cell.y_km, " km"));
        addItem(cellSection.list, "Outcome", outcomeText(cell.outcome));
        addItem(cellSection.list, "Response", unitText(cell.response_s, " s"));
        addItem(
          cellSection.list,
          "Selected base",
          cell.selected_base_id === null || cell.selected_base_id === undefined
            ? "Unavailable"
            : `Base ${text(cell.selected_base_id)}`,
        );
      }
    }
    detail.append(cellSection.section);
  }

  function showError(message) {
    detail.replaceChildren();
    detail.hidden = true;
    empty.hidden = true;
    error.textContent = String(message);
    error.hidden = false;
  }

  return {
    render,
    showError,
    destroy() {
      root.remove();
    },
  };
}

export { createCoverageDetails };

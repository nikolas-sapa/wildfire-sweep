function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function display(value) {
  return value === null || value === undefined ? "" : String(value);
}

function formatPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return `${(100 * value).toFixed(2)}%`;
}

function formatHeading(value) {
  return value === null || value === undefined ? "Calm" : display(value);
}

function formatOffline(bases) {
  return Array.isArray(bases) && bases.length > 0 ? bases.join(", ") : "None";
}

function headerCell(text) {
  const cell = element("th", "", text);
  cell.scope = "col";
  return cell;
}

function numberCell(value) {
  return element("td", "cov-table-num", display(value));
}

function createCoverageTable(container, { onCase = () => {} } = {}) {
  const wrap = element("div", "cov-table-wrap");
  wrap.setAttribute("role", "region");
  wrap.setAttribute("aria-label", "Captured coverage cases");
  wrap.tabIndex = 0;
  const table = element("table", "cov-table");
  table.append(element(
    "caption",
    "",
    "Captured coverage cases with stored scenario inputs and outcome counts",
  ));
  const head = element("thead");
  const headRow = element("tr");
  for (const label of [
    "Case",
    "Bases",
    "Profile",
    "Heading (deg)",
    "Wind (m/s)",
    "Offline bases",
    "Timely cells",
    "Late cells",
    "Unreachable cells",
    "Weather-closed cells",
    "Total cells",
    "Timely area",
    "Reachable area",
  ]) {
    headRow.append(headerCell(label));
  }
  head.append(headRow);
  const body = element("tbody");
  table.append(head, body);
  const empty = element(
    "p",
    "cov-table-empty",
    "No cases match the current filters.",
  );
  empty.setAttribute("role", "status");
  empty.hidden = true;
  wrap.append(table, empty);
  container.append(wrap);

  let catalog = null;
  let selectedCaseId = null;
  let filterIds = null;

  function renderRows() {
    const active = document.activeElement;
    const focusedRow = active instanceof Element && body.contains(active)
      ? active.closest("tr[data-case-id]")
      : null;
    const focusedCaseId = focusedRow?.dataset.caseId ?? null;
    const scrollTop = wrap.scrollTop;
    body.replaceChildren();
    const all = Array.isArray(catalog?.cases) ? catalog.cases : [];
    const cases = filterIds === null
      ? all
      : all.filter((item) => filterIds.has(item.case_id));
    empty.hidden = cases.length !== 0;
    for (const item of cases) {
      const summary = item.summary || {};
      const selected = item.case_id === selectedCaseId;
      const row = element("tr", selected ? "cov-row-selected" : "");
      row.dataset.caseId = item.case_id;
      const heading = element("th");
      heading.scope = "row";
      const button = element(
        "button",
        "cov-button cov-table-select",
        display(item.case_id),
      );
      button.type = "button";
      button.setAttribute("aria-pressed", selected ? "true" : "false");
      button.setAttribute("aria-label", `Select case ${display(item.case_id)}`);
      heading.append(button);
      row.append(
        heading,
        numberCell(item.n_bases),
        element("td", "", display(item.profile)),
        element("td", "", formatHeading(item.heading_deg)),
        numberCell(item.wind_speed_mps),
        element("td", "", formatOffline(item.offline_bases)),
        numberCell(summary.timely_cells),
        numberCell(summary.late_cells),
        numberCell(summary.unreachable_cells),
        numberCell(summary.weather_closed_cells),
        numberCell(summary.total_cells),
        element("td", "cov-table-num", formatPercent(summary.timely_area_fraction)),
        element("td", "cov-table-num", formatPercent(summary.reachable_area_fraction)),
      );
      body.append(row);
    }
    wrap.scrollTop = scrollTop;
    if (focusedCaseId !== null) {
      const focusedButton = [...body.querySelectorAll("button.cov-table-select")]
        .find((button) => button.closest("tr[data-case-id]")?.dataset.caseId === focusedCaseId);
      focusedButton?.focus({ preventScroll: true });
    }
  }

  function handleClick(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const row = target.closest("tr[data-case-id]");
    if (row === null || !body.contains(row)) return;
    onCase(row.dataset.caseId);
  }

  body.addEventListener("click", handleClick);

  return {
    render(nextCatalog, nextSelectedCaseId = null) {
      catalog = nextCatalog;
      selectedCaseId = nextSelectedCaseId;
      renderRows();
    },
    setFilter(caseIdsOrNull) {
      filterIds = Array.isArray(caseIdsOrNull) ? new Set(caseIdsOrNull) : null;
      renderRows();
    },
    destroy() {
      body.removeEventListener("click", handleClick);
      wrap.remove();
    },
  };
}

export { createCoverageTable };

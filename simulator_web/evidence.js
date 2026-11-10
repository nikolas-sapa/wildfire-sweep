const RESEARCH_BASE = "https://github.com/nikolas-sapa/wildfire-sweep";
const RESEARCH_LINKS = [
  ["Methods", `${RESEARCH_BASE}/blob/main/docs/2026-11-09-resilience-study.md`],
  ["Protocol", `${RESEARCH_BASE}/blob/main/resilience_protocol.json`],
  ["Frozen capture", `${RESEARCH_BASE}/tree/main/research_results/2026-11-09-resilience`],
];

function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function displayValue(value) {
  if (value === null || value === undefined) return "n/a";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function renderTable(rows, className, heading) {
  const section = element("section", "evidence-section");
  section.append(element("h3", "evidence-subheading", heading));
  if (!Array.isArray(rows) || rows.length === 0) {
    section.append(element("p", "evidence-note", "No captured rows are available."));
    return section;
  }
  const columns = Object.keys(rows[0]);
  const wrapper = element("div", "evidence-table-wrap");
  const table = element("table", className);
  const head = element("thead");
  const headerRow = element("tr");
  for (const column of columns) {
    headerRow.append(element("th", "", column.replaceAll("_", " ")));
  }
  head.append(headerRow);
  const body = element("tbody");
  for (const rowData of rows) {
    const row = element("tr");
    for (const column of columns) {
      row.append(element("td", "", displayValue(rowData[column])));
    }
    body.append(row);
  }
  table.append(head, body);
  wrapper.append(table);
  section.append(wrapper);
  return section;
}

function createEvidencePanel(container) {
  const content = element("div", "evidence-content");
  container.querySelector(".evidence-loading")?.remove();
  container.append(content);

  function render(catalog) {
    content.replaceChildren();
    const study = catalog?.study;
    if (!study || !Array.isArray(study.summary) || !Array.isArray(study.contrasts)) {
      content.append(element("p", "evidence-error", "Frozen evidence is unavailable."));
      return;
    }
    content.append(
      element(
        "p",
        "evidence-note",
        "Captured values only. Monte Carlo intervals describe sampling uncertainty conditional on the model inputs; they are not field uncertainty.",
      ),
      renderTable(study.summary, "evidence-table", "Captured scenario summary"),
      renderTable(study.contrasts, "evidence-table", "Captured paired contrasts"),
    );

    const provenance = element("dl", "evidence-provenance");
    provenance.append(
      element("dt", "", "Study"),
      element("dd", "", String(study.id)),
      element("dt", "", "Manifest SHA-256"),
      element("dd", "evidence-hash", String(study.manifest_sha256)),
    );
    content.append(provenance);

    const links = element("nav", "evidence-links");
    links.setAttribute("aria-label", "Research sources");
    for (const [label, href] of RESEARCH_LINKS) {
      const link = element("a", "", label);
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      links.append(link);
    }
    content.append(links);

    if (Array.isArray(study.limitations) && study.limitations.length) {
      const limitations = element("ul", "evidence-limitations");
      for (const item of study.limitations) {
        limitations.append(element("li", "", String(item)));
      }
      content.append(limitations);
    }
  }

  return {
    render,
    destroy() {
      content.remove();
    },
  };
}

export { createEvidencePanel };

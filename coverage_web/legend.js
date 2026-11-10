import { validateCatalog } from "./data_contract.js";

const OUTCOME_INFO = {
  unreachable: {
    name: "Unreachable",
    cue: "dotted",
    describe: () => "no available base can serve the cell; response and base stay null, never zero.",
  },
  late: {
    name: "Late",
    cue: "diagonal hatch",
    describe: (deadlineS) => `served, but first arrival after the ${deadlineS} s deadline.`,
  },
  timely: {
    name: "Timely",
    cue: "solid",
    describe: (deadlineS) => `served, first arrival in ${deadlineS} s or less.`,
  },
  weather_closed: {
    name: "Weather closed",
    cue: "crosshatch",
    describe: () => "wind above the model limit; every cell is unserved and stays null.",
  },
};

function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function createCoverageLegend(container) {
  const content = element("div", "cov-legend-content");
  container.append(content);

  function outcomeItem(outcome, deadlineS) {
    const info = OUTCOME_INFO[outcome];
    const item = element("li", "cov-legend-item");
    item.dataset.outcome = outcome;
    const swatch = element("span", "cov-legend-swatch");
    swatch.dataset.outcome = outcome;
    swatch.setAttribute("aria-hidden", "true");
    const text = element("span", "cov-legend-text");
    text.append(
      element("span", "cov-legend-name", info.name),
      " ",
      element("span", "cov-legend-cue", `(${info.cue})`),
      ": ",
      element("span", "cov-legend-desc", info.describe(deadlineS)),
    );
    item.append(swatch, text);
    return item;
  }

  function subheading(text) {
    return element("p", "cov-legend-subheading", text);
  }

  function noteList(className, entries) {
    const list = element("ul", className);
    for (const entry of entries) {
      list.append(element("li", `${className}-item`, entry));
    }
    return list;
  }

  function readNotes(catalog) {
    const block = element("div", "cov-legend-notes-block");
    block.append(
      subheading("How to read the map"),
      noteList("cov-legend-notes", [
        `North is up; stored grid north is ${catalog.grid.north}.`,
        `Each case stores ${catalog.grid_n} x ${catalog.grid_n} equal-area cells; ` +
          `a cell's value is the outcome at its own center point (${catalog.grid.locations}), ` +
          "an approximation of the area around it.",
        "Each cell is an independent single alert evaluated with the available drones " +
          "initially idle; there is no queueing.",
        "Null means unavailable, never zero: unserved cells carry no response time " +
          "or selected base.",
        "A blue outline marks the selected cell.",
        "Captured synthetic output; not field-validated and not a season probability " +
          "or success rate.",
      ]),
    );
    return block;
  }

  function limitationBlock(catalog) {
    const block = element("div", "cov-legend-limitations-block");
    block.append(
      subheading("Limitations stored with the capture"),
      noteList("cov-legend-limitations", catalog.limitations),
    );
    return block;
  }

  function render(catalog) {
    const valid = validateCatalog(catalog);
    content.replaceChildren();
    const list = element("ul", "cov-legend-list");
    const outcomes = Object.entries(valid.outcome_codes)
      .sort((left, right) => left[1] - right[1])
      .map(([name]) => name);
    for (const outcome of outcomes) {
      list.append(outcomeItem(outcome, valid.timely_threshold_s));
    }
    content.append(list, readNotes(valid), limitationBlock(valid));
  }

  return {
    render,
    destroy() {
      content.remove();
    },
  };
}

export { createCoverageLegend };

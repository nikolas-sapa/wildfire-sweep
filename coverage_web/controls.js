let instanceCount = 0;

const CARDINALS = new Map([
  [0, "E"],
  [45, "NE"],
  [90, "N"],
  [135, "NW"],
  [180, "W"],
  [225, "SW"],
  [270, "S"],
  [315, "SE"],
]);

function numberText(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
}

function profileText(profile) {
  return String(profile).split("_").join(" ");
}

function headingText(headingDeg) {
  if (headingDeg === null) return "calm";
  const cardinal = CARDINALS.get(headingDeg);
  return cardinal === undefined
    ? `${numberText(headingDeg)} deg`
    : `${numberText(headingDeg)} deg (${cardinal})`;
}

function outageCountText(count) {
  return count === 1 ? "1 outage" : `${count} outages`;
}

function outageText(descriptor) {
  const offline = Array.isArray(descriptor.offline_bases)
    ? descriptor.offline_bases
    : [];
  if (offline.length === 0) return "no outages";
  return `${outageCountText(offline.length)}: ${offline.join(", ")}`;
}

function windText(descriptor) {
  if (descriptor.heading_deg === null) return "calm";
  return `${numberText(descriptor.wind_speed_mps)} m/s at ${headingText(descriptor.heading_deg)}`;
}

function outageCount(descriptor) {
  return Array.isArray(descriptor.offline_bases) ? descriptor.offline_bases.length : 0;
}

function caseLabel(descriptor) {
  if (!descriptor || typeof descriptor.case_id !== "string") return "Unknown case";
  if (typeof descriptor.n_bases !== "number"
    || typeof descriptor.wind_speed_mps !== "number"
    || (descriptor.heading_deg !== null && typeof descriptor.heading_deg !== "number")
    || typeof descriptor.profile !== "string") {
    return descriptor.case_id;
  }
  return `${descriptor.n_bases} bases | ${windText(descriptor)} | `
    + `${profileText(descriptor.profile)} | ${outageText(descriptor)}`;
}

const FILTER_FIELDS = [
  {
    key: "n_bases",
    label: "Fleet layout",
    allLabel: "All layouts",
    value: (descriptor) => descriptor.n_bases,
    token: (value) => String(value),
    optionText: (value) => `${numberText(value)} bases`,
    order: (left, right) => left - right,
  },
  {
    key: "profile",
    label: "Profile",
    allLabel: "All profiles",
    value: (descriptor) => descriptor.profile,
    token: (value) => String(value),
    optionText: (value) => profileText(value),
    order: null,
  },
  {
    key: "wind_speed_mps",
    label: "Wind speed",
    allLabel: "All wind speeds",
    value: (descriptor) => descriptor.wind_speed_mps,
    token: (value) => String(value),
    optionText: (value) => (value === 0 ? "0 m/s (calm)" : `${numberText(value)} m/s`),
    order: (left, right) => left - right,
  },
  {
    key: "heading_deg",
    label: "Heading",
    allLabel: "All headings",
    value: (descriptor) => descriptor.heading_deg,
    token: (value) => (value === null ? "calm" : String(value)),
    optionText: (value) => (value === null ? "Calm" : headingText(value)),
    order: (left, right) => (left === null ? -1 : right === null ? 1 : left - right),
  },
  {
    key: "outage_count",
    label: "Outages",
    allLabel: "All outage counts",
    value: (descriptor) => outageCount(descriptor),
    token: (value) => String(value),
    optionText: (value) => outageCountText(value),
    order: (left, right) => left - right,
  },
];

function selectField(id, labelText) {
  const wrapper = document.createElement("div");
  wrapper.className = "cov-field";
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = labelText;
  const select = document.createElement("select");
  select.id = id;
  select.name = id;
  select.className = "cov-select";
  wrapper.append(label, select);
  return { wrapper, select };
}

function setOptions(select, options, currentValue) {
  select.replaceChildren();
  let present = false;
  for (const item of options) {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    if (item.disabled === true) option.disabled = true;
    select.append(option);
    if (item.value === currentValue) present = true;
  }
  select.value = present ? currentValue : (options.length > 0 ? options[0].value : "");
}

function createCoverageControls(container, { onCase = () => {}, onCompare = () => {} } = {}) {
  const instance = ++instanceCount;

  const form = document.createElement("form");
  form.className = "cov-controls-form";
  form.noValidate = true;
  form.setAttribute("aria-label", "Coverage case selection");

  const caseFieldset = document.createElement("fieldset");
  const caseLegend = document.createElement("legend");
  caseLegend.textContent = "Cases";
  const primaryField = selectField(`cov-controls-${instance}-primary`, "Primary case");
  const compareField = selectField(
    `cov-controls-${instance}-compare`,
    "Comparison case (optional)",
  );
  caseFieldset.append(caseLegend, primaryField.wrapper, compareField.wrapper);

  const filterFieldset = document.createElement("fieldset");
  const filterLegend = document.createElement("legend");
  filterLegend.textContent = "Filter case list";
  const filterFields = [];
  for (const definition of FILTER_FIELDS) {
    const field = selectField(
      `cov-controls-${instance}-filter-${definition.key}`,
      definition.label,
    );
    filterFields.push({ definition, select: field.select });
    filterFieldset.append(field.wrapper);
  }
  form.append(caseFieldset, filterFieldset);
  container.append(form);

  let catalog = null;
  let caseIndex = new Map();
  const filters = {
    n_bases: "",
    profile: "",
    wind_speed_mps: "",
    heading_deg: "",
    outage_count: "",
  };
  let selection = { case_id: null, compare_case_id: null };
  let busy = false;

  function filteredCases() {
    if (!catalog || !Array.isArray(catalog.cases)) return [];
    return catalog.cases.filter((descriptor) => descriptor && FILTER_FIELDS.every(
      ({ key, value, token }) => filters[key] === "" || token(value(descriptor)) === filters[key],
    ));
  }

  function syncFilterFields() {
    for (const { definition, select } of filterFields) {
      const seen = new Map();
      if (catalog && Array.isArray(catalog.cases)) {
        for (const descriptor of catalog.cases) {
          if (!descriptor) continue;
          const raw = definition.value(descriptor);
          const key = definition.token(raw);
          if (!seen.has(key)) seen.set(key, raw);
        }
      }
      let entries = [...seen.entries()];
      if (definition.order) {
        entries = entries.sort((left, right) => definition.order(left[1], right[1]));
      }
      const options = [{ value: "", label: definition.allLabel }];
      for (const [tokenValue, raw] of entries) {
        options.push({ value: tokenValue, label: definition.optionText(raw) });
      }
      if (filters[definition.key] !== "" && !seen.has(filters[definition.key])) {
        filters[definition.key] = "";
      }
      setOptions(select, options, filters[definition.key]);
    }
  }

  function retainedOption(caseId, filteredIds) {
    if (caseId === null || filteredIds.has(caseId)) return null;
    const descriptor = caseIndex.get(caseId);
    return {
      value: caseId,
      label: descriptor
        ? `${caseLabel(descriptor)} (outside current filters)`
        : `${caseId} (unavailable)`,
    };
  }

  function syncCaseOptions() {
    const filtered = filteredCases();
    const filteredIds = new Set(filtered.map((descriptor) => descriptor.case_id));

    const primaryOptions = [];
    if (filtered.length === 0) {
      primaryOptions.push({
        value: "",
        label: catalog ? "No cases match the current filters" : "Catalog unavailable",
        disabled: true,
      });
    } else {
      if (selection.case_id === null) {
        primaryOptions.push({ value: "", label: "Select a case", disabled: true });
      }
      for (const descriptor of filtered) {
        primaryOptions.push({ value: descriptor.case_id, label: caseLabel(descriptor) });
      }
    }
    const retainedPrimary = retainedOption(selection.case_id, filteredIds);
    if (retainedPrimary) primaryOptions.push(retainedPrimary);
    setOptions(primaryField.select, primaryOptions, selection.case_id ?? "");

    const compareOptions = [{ value: "", label: "No comparison" }];
    for (const descriptor of filtered) {
      compareOptions.push({ value: descriptor.case_id, label: caseLabel(descriptor) });
    }
    const retainedCompare = retainedOption(selection.compare_case_id, filteredIds);
    if (retainedCompare) compareOptions.push(retainedCompare);
    setOptions(compareField.select, compareOptions, selection.compare_case_id ?? "");

    applyDisabled();
  }

  function applyDisabled() {
    const noCases = filteredCases().length === 0;
    caseFieldset.disabled = busy;
    filterFieldset.disabled = busy;
    primaryField.select.disabled = busy || !catalog || noCases;
    compareField.select.disabled = busy || !catalog;
    form.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function handleChange(event) {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    if (target === primaryField.select) {
      const next = target.value;
      if (next === "" || next === selection.case_id) {
        syncCaseOptions();
        return;
      }
      selection = { ...selection, case_id: next };
      syncCaseOptions();
      onCase(next);
      return;
    }
    if (target === compareField.select) {
      const next = target.value === "" ? null : target.value;
      if (next === selection.compare_case_id) return;
      selection = { ...selection, compare_case_id: next };
      syncCaseOptions();
      onCompare(next);
      return;
    }
    for (const { definition, select } of filterFields) {
      if (target === select) {
        filters[definition.key] = select.value;
        syncCaseOptions();
        return;
      }
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
  }

  form.addEventListener("change", handleChange);
  form.addEventListener("submit", handleSubmit);

  syncFilterFields();
  syncCaseOptions();

  return {
    setCatalog(nextCatalog) {
      catalog = nextCatalog && typeof nextCatalog === "object" && Array.isArray(nextCatalog.cases)
        ? nextCatalog
        : null;
      caseIndex = new Map();
      if (catalog) {
        for (const descriptor of catalog.cases) {
          if (descriptor && typeof descriptor.case_id === "string") {
            caseIndex.set(descriptor.case_id, descriptor);
          }
        }
      }
      syncFilterFields();
      syncCaseOptions();
    },
    setSelection(nextSelection) {
      const caseId = nextSelection && typeof nextSelection.case_id === "string"
        ? nextSelection.case_id
        : null;
      const compareId = nextSelection && typeof nextSelection.compare_case_id === "string"
        ? nextSelection.compare_case_id
        : null;
      selection = { case_id: caseId, compare_case_id: compareId };
      syncCaseOptions();
    },
    setBusy(nextBusy) {
      busy = Boolean(nextBusy);
      applyDisabled();
    },
    destroy() {
      form.removeEventListener("change", handleChange);
      form.removeEventListener("submit", handleSubmit);
      form.remove();
    },
  };
}

export { createCoverageControls };

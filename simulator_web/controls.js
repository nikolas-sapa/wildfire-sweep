function numberInput(id, labelText, bounds, step) {
  const wrapper = document.createElement("div");
  wrapper.className = "controls-field";
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = labelText;
  const input = document.createElement("input");
  input.id = id;
  input.name = id;
  input.type = "number";
  input.step = String(step);
  input.className = "controls-input";
  input.setAttribute("data-slot", "input");
  if (bounds) {
    input.min = String(bounds[0]);
    input.max = String(bounds[1]);
  }
  wrapper.append(label, input);
  return { wrapper, input };
}

function selectField(id, labelText) {
  const wrapper = document.createElement("div");
  wrapper.className = "controls-field";
  const label = document.createElement("label");
  label.htmlFor = id;
  label.textContent = labelText;
  const select = document.createElement("select");
  select.id = id;
  select.name = id;
  select.className = "controls-select";
  select.setAttribute("data-slot", "input");
  wrapper.append(label, select);
  return { wrapper, select };
}

function readNumber(input) {
  if (input.value.trim() === "") return null;
  const value = Number(input.value);
  return Number.isFinite(value) ? value : null;
}

function setInputValue(input, value) {
  if (document.activeElement === input || value === undefined) return;
  input.value = value === null ? "" : String(value);
}

function createControls(container, { onChange = () => {}, onReset = () => {} } = {}) {
  const form = document.createElement("form");
  form.className = "controls-form";
  form.noValidate = true;
  const fieldset = document.createElement("fieldset");
  fieldset.className = "controls-fieldset";
  const layoutField = selectField("controls-layout", "Fleet layout");
  const offlineField = selectField("controls-offline-base", "Unavailable base");
  const pointEast = numberInput("controls-point-east", "East (km)", null, 0.1);
  const pointNorth = numberInput("controls-point-north", "North (km)", null, 0.1);
  const windEast = numberInput("controls-wind-east", "East wind (m/s)", null, 0.1);
  const windNorth = numberInput("controls-wind-north", "North wind (m/s)", null, 0.1);
  const airspeed = numberInput("controls-airspeed", "Airspeed (m/s)", null, 0.1);
  const endurance = numberInput("controls-endurance", "Endurance (min)", null, 0.1);
  const reserve = numberInput("controls-reserve", "Reserve fraction", null, 0.01);
  const launch = numberInput("controls-launch", "Launch latency (s)", null, 1);
  const pointPair = document.createElement("div");
  pointPair.className = "controls-pair";
  pointPair.append(pointEast.wrapper, pointNorth.wrapper);
  const windPair = document.createElement("div");
  windPair.className = "controls-pair";
  windPair.append(windEast.wrapper, windNorth.wrapper);
  const advanced = document.createElement("details");
  advanced.className = "controls-advanced";
  const advancedSummary = document.createElement("summary");
  advancedSummary.textContent = "Advanced aircraft and launch assumptions";
  const advancedFields = document.createElement("div");
  advancedFields.className = "controls-advanced-fields";
  advancedFields.append(airspeed.wrapper, endurance.wrapper, reserve.wrapper, launch.wrapper);
  advanced.append(advancedSummary, advancedFields);
  const resetButton = document.createElement("button");
  resetButton.type = "button";
  resetButton.className = "app-button app-button-secondary";
  resetButton.setAttribute("data-slot", "button");
  resetButton.textContent = "Reset assumptions";
  const actions = document.createElement("div");
  actions.className = "controls-actions";
  actions.append(resetButton);
  fieldset.append(
    layoutField.wrapper,
    offlineField.wrapper,
    pointPair,
    windPair,
    advanced,
    actions,
  );
  form.append(fieldset);
  container.querySelector(".controls-loading")?.remove();
  container.append(form);

  let catalog = null;
  let values = {};

  function setOptions(select, options, selectedValue) {
    const previousValue = select.value;
    const activeValue = document.activeElement === select ? previousValue : selectedValue;
    select.replaceChildren();
    for (const optionData of options) {
      const option = document.createElement("option");
      option.value = optionData.value;
      option.textContent = optionData.label;
      select.append(option);
    }
    select.value = activeValue === null ? "" : String(activeValue);
  }

  function updateOfflineOptions(selectedValue = values.offline_base ?? null) {
    const layout = catalog?.layouts?.[String(values.n_bases)];
    const options = [{ value: "", label: "None" }];
    for (const base of layout || []) {
      options.push({ value: String(base.id), label: `Base ${base.id}` });
    }
    setOptions(offlineField.select, options, selectedValue);
  }

  function applyBounds(input, bounds) {
    if (!bounds) return;
    input.min = String(bounds[0]);
    input.max = String(bounds[1]);
  }

  function setCatalog(nextCatalog) {
    catalog = nextCatalog;
    const layouts = catalog.layouts || {};
    const layoutKeys = Object.keys(layouts).sort((left, right) => Number(left) - Number(right));
    setOptions(
      layoutField.select,
      layoutKeys.map((key) => ({ value: key, label: `${key} bases` })),
      values.n_bases ?? catalog.defaults?.n_bases,
    );
    const limits = catalog.parameter_limits || {};
    const domain = Number(catalog.domain_side_km);
    if (Number.isFinite(domain) && domain > 0) {
      applyBounds(pointEast.input, [0, domain]);
      applyBounds(pointNorth.input, [0, domain]);
    }
    applyBounds(windEast.input, limits.wind_component_mps);
    applyBounds(windNorth.input, limits.wind_component_mps);
    applyBounds(airspeed.input, limits.airspeed_mps);
    applyBounds(endurance.input, limits.endurance_min);
    applyBounds(reserve.input, limits.reserve_fraction);
    applyBounds(launch.input, limits.launch_latency_s);
    updateOfflineOptions();
    setValues({ ...catalog.defaults, ...values });
  }

  function setValues(nextValues) {
    values = { ...values, ...nextValues };
    setInputValue(layoutField.select, values.n_bases);
    updateOfflineOptions(values.offline_base ?? null);
    setInputValue(offlineField.select, values.offline_base ?? null);
    setInputValue(pointEast.input, values.point_km?.[0]);
    setInputValue(pointNorth.input, values.point_km?.[1]);
    setInputValue(windEast.input, values.wind_mps?.[0]);
    setInputValue(windNorth.input, values.wind_mps?.[1]);
    setInputValue(airspeed.input, values.airspeed_mps);
    setInputValue(endurance.input, values.endurance_min);
    setInputValue(reserve.input, values.reserve_fraction);
    setInputValue(launch.input, values.launch_latency_s);
  }

  function handleInput(event) {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target === pointEast.input || target === pointNorth.input) {
      const point = [readNumber(pointEast.input), readNumber(pointNorth.input)];
      values = { ...values, point_km: point };
      onChange({ point_km: point });
      return;
    }
    if (target === windEast.input || target === windNorth.input) {
      const wind = [readNumber(windEast.input), readNumber(windNorth.input)];
      values = { ...values, wind_mps: wind };
      onChange({ wind_mps: wind });
      return;
    }
    const fields = new Map([
      [airspeed.input, "airspeed_mps"],
      [endurance.input, "endurance_min"],
      [reserve.input, "reserve_fraction"],
      [launch.input, "launch_latency_s"],
    ]);
    const key = fields.get(target);
    if (key) {
      const value = readNumber(target);
      values = { ...values, [key]: value };
      onChange({ [key]: value });
    }
  }

  function handleChange(event) {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    if (target === layoutField.select) {
      const nBases = Number(layoutField.select.value);
      values = { ...values, n_bases: nBases, offline_base: null };
      updateOfflineOptions(null);
      setInputValue(offlineField.select, null);
      onChange({ n_bases: nBases, offline_base: null });
      return;
    }
    if (target === offlineField.select) {
      const offlineBase = offlineField.select.value === ""
        ? null
        : Number(offlineField.select.value);
      values = { ...values, offline_base: offlineBase };
      onChange({ offline_base: offlineBase });
    }
  }

  function handleReset() {
    onReset();
  }

  function handleSubmit(event) {
    event.preventDefault();
  }

  form.addEventListener("input", handleInput);
  form.addEventListener("change", handleChange);
  form.addEventListener("submit", handleSubmit);
  resetButton.addEventListener("click", handleReset);

  return {
    setCatalog,
    setValues,
    setBusy(busy) {
      fieldset.disabled = Boolean(busy);
    },
    destroy() {
      form.removeEventListener("input", handleInput);
      form.removeEventListener("change", handleChange);
      form.removeEventListener("submit", handleSubmit);
      resetButton.removeEventListener("click", handleReset);
      form.remove();
    },
  };
}

export { createControls };

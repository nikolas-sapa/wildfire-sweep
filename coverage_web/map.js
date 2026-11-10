const OUTCOME_FILLS = {
  timely: "#47a447",
  late: "#f5a623",
  unreachable: "#7d7d7d",
  weather_closed: "#171717",
};
const OUTCOME_MARKS = {
  late: "rgba(23, 23, 23, 0.45)",
  unreachable: "rgba(23, 23, 23, 0.55)",
  weather_closed: "rgba(255, 255, 255, 0.55)",
};
const OUTCOME_ORDER = ["timely", "late", "unreachable", "weather_closed"];
const SELECTION = "#006bff";
const BASE_FILL = "#fafafa";
const BASE_EDGE = "#171717";
const BASE_HALO = "rgba(250, 250, 250, 0.9)";
const LABEL_TEXT = "#fafafa";
const LABEL_HALO = "rgba(23, 23, 23, 0.8)";
const PATTERN_TILE = 8;

let mapCounter = 0;

function cellFromPoint(x, y, width, height, gridN) {
  if (!Number.isFinite(x) || !Number.isFinite(y)
      || !Number.isFinite(width) || !Number.isFinite(height)
      || width <= 0 || height <= 0
      || !Number.isSafeInteger(gridN) || gridN < 1 || gridN > 160) {
    return null;
  }
  if (x < 0 || y < 0 || x >= width || y >= height) {
    return null;
  }
  const column = Math.min(gridN - 1, Math.floor((x / width) * gridN));
  const screenRow = Math.min(gridN - 1, Math.floor((y / height) * gridN));
  const row = gridN - 1 - screenRow;
  return row * gridN + column;
}

function createCoverageMap(
  container,
  { onCell = () => {}, idPrefix = "cov-map" } = {},
) {
  mapCounter += 1;
  const prefix = `${idPrefix}-${mapCounter}`;
  const view = document.createElement("div");
  view.className = "cov-map-view";
  view.id = `${prefix}-view`;
  const canvas = document.createElement("canvas");
  canvas.className = "cov-canvas";
  canvas.id = `${prefix}-canvas`;
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Coverage outcome map");
  const live = document.createElement("p");
  live.className = "cov-map-live";
  live.id = `${prefix}-live`;
  live.setAttribute("role", "status");
  live.setAttribute("aria-live", "polite");
  live.setAttribute("aria-atomic", "true");
  live.textContent = "No coverage case loaded.";
  canvas.setAttribute("aria-describedby", live.id);
  view.append(canvas, live);
  container.append(view);

  const context = canvas.getContext("2d");
  let payload = null;
  let cells = [];
  let gridN = 0;
  let selected = null;
  let cursor = null;
  let busy = false;
  let viewWidth = 0;
  let viewHeight = 0;
  let patterns = null;
  let observer = null;
  let media = null;

  function makePattern(drawTile) {
    if (!context) return null;
    const tile = document.createElement("canvas");
    tile.width = PATTERN_TILE;
    tile.height = PATTERN_TILE;
    const tileContext = tile.getContext("2d");
    if (!tileContext) return null;
    drawTile(tileContext, PATTERN_TILE);
    return context.createPattern(tile, "repeat");
  }

  function buildPatterns() {
    patterns = {
      late: makePattern((graphics, size) => {
        graphics.strokeStyle = OUTCOME_MARKS.late;
        graphics.lineWidth = 1.2;
        graphics.beginPath();
        graphics.moveTo(0, size);
        graphics.lineTo(size, 0);
        graphics.stroke();
      }),
      unreachable: makePattern((graphics, size) => {
        graphics.fillStyle = OUTCOME_MARKS.unreachable;
        graphics.beginPath();
        graphics.arc(size / 2, size / 2, 1.1, 0, Math.PI * 2);
        graphics.fill();
      }),
      weather_closed: makePattern((graphics, size) => {
        graphics.strokeStyle = OUTCOME_MARKS.weather_closed;
        graphics.lineWidth = 1;
        graphics.beginPath();
        graphics.moveTo(0, size);
        graphics.lineTo(size, 0);
        graphics.moveTo(0, 0);
        graphics.lineTo(size, size);
        graphics.stroke();
      }),
    };
  }

  function cellRect(index) {
    const row = Math.floor(index / gridN);
    const column = index % gridN;
    const x0 = Math.round((column * viewWidth) / gridN);
    const x1 = Math.round(((column + 1) * viewWidth) / gridN);
    const y0 = Math.round(((gridN - 1 - row) * viewHeight) / gridN);
    const y1 = Math.round(((gridN - row) * viewHeight) / gridN);
    return [x0, y0, x1 - x0, y1 - y0];
  }

  function outline(index, dashed) {
    const [x, y, width, height] = cellRect(index);
    context.save();
    context.strokeStyle = SELECTION;
    context.lineWidth = 2;
    if (dashed) context.setLineDash([4, 3]);
    context.strokeRect(x + 1, y + 1, Math.max(0, width - 2), Math.max(0, height - 2));
    context.restore();
  }

  function drawBases() {
    const side = payload.domain_side_km;
    if (!Number.isFinite(side) || side <= 0 || !Array.isArray(payload.bases)) return;
    const size = Math.max(7, Math.min(viewWidth, viewHeight) * 0.02);
    const edge = Math.max(1, size * 0.16);
    context.lineJoin = "round";
    context.font = `${Math.max(9, size * 0.9)}px "Geist Sans", system-ui, sans-serif`;
    context.textBaseline = "middle";
    for (const base of payload.bases) {
      if (!Number.isFinite(base.x_km) || !Number.isFinite(base.y_km)) continue;
      const x = (base.x_km / side) * viewWidth;
      const y = viewHeight - (base.y_km / side) * viewHeight;
      context.beginPath();
      context.arc(x, y, size / 2, 0, Math.PI * 2);
      if (base.available) {
        context.fillStyle = BASE_FILL;
        context.fill();
      }
      context.strokeStyle = BASE_HALO;
      context.lineWidth = edge + 1.6;
      context.stroke();
      context.strokeStyle = BASE_EDGE;
      context.lineWidth = edge;
      context.stroke();
      if (!base.available) {
        const reach = size * 0.28;
        context.beginPath();
        context.moveTo(x - reach, y - reach);
        context.lineTo(x + reach, y + reach);
        context.moveTo(x - reach, y + reach);
        context.lineTo(x + reach, y - reach);
        context.stroke();
      }
      const label = String(base.id);
      const labelX = x + size * 0.72;
      const labelY = y - size * 0.66;
      context.lineWidth = 3;
      context.strokeStyle = LABEL_HALO;
      context.strokeText(label, labelX, labelY);
      context.fillStyle = LABEL_TEXT;
      context.fillText(label, labelX, labelY);
    }
  }

  function draw() {
    if (!context) return;
    context.clearRect(0, 0, viewWidth, viewHeight);
    if (!payload || gridN < 1 || viewWidth <= 0 || viewHeight <= 0) return;
    if (!patterns) buildPatterns();
    const paths = {
      timely: new Path2D(),
      late: new Path2D(),
      unreachable: new Path2D(),
      weather_closed: new Path2D(),
    };
    for (const cell of cells) {
      const path = paths[cell.outcome];
      if (!path) continue;
      const [x, y, width, height] = cellRect(cell.index);
      path.rect(x, y, width, height);
    }
    for (const outcome of OUTCOME_ORDER) {
      const path = paths[outcome];
      context.fillStyle = OUTCOME_FILLS[outcome];
      context.fill(path);
      const pattern = patterns ? patterns[outcome] : null;
      if (pattern) {
        context.fillStyle = pattern;
        context.fill(path);
      }
    }
    drawBases();
    if (selected !== null) outline(selected, false);
    if (cursor !== null && cursor !== selected) outline(cursor, true);
  }

  function describe(index) {
    const cell = cells[index];
    if (!cell) return `cell ${index}`;
    const parts = [
      `cell ${index}`,
      `row ${cell.row + 1} of ${gridN}`,
      `column ${cell.column + 1} of ${gridN}`,
      `center ${cell.x_km} km east, ${cell.y_km} km north`,
      `outcome ${cell.outcome}`,
    ];
    if (cell.response_s === null || cell.response_s === undefined) {
      parts.push("no stored response");
    } else {
      parts.push(`response ${cell.response_s} seconds`);
    }
    if (cell.selected_base_id === null || cell.selected_base_id === undefined) {
      parts.push("no assigned base");
    } else {
      parts.push(`assigned base ${cell.selected_base_id}`);
    }
    return parts.join(", ");
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const dpr = globalThis.devicePixelRatio || 1;
    viewWidth = rect.width;
    viewHeight = rect.height;
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    if (context) context.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function handlePointerDown(event) {
    if (!payload || busy) return;
    const rect = canvas.getBoundingClientRect();
    const index = cellFromPoint(
      event.clientX - rect.left,
      event.clientY - rect.top,
      rect.width,
      rect.height,
      gridN,
    );
    if (index === null) return;
    if (typeof canvas.focus === "function") canvas.focus({ preventScroll: true });
    cursor = index;
    live.textContent = `Selected ${describe(index)}`;
    draw();
    onCell(index);
  }

  function handleKeyDown(event) {
    if (!payload || busy) return;
    const key = event.key;
    const handled = key === "ArrowUp" || key === "ArrowDown" || key === "ArrowLeft"
      || key === "ArrowRight" || key === "Home" || key === "End" || key === "Enter";
    if (!handled) return;
    event.preventDefault();
    const total = gridN * gridN;
    if (key === "Enter") {
      if (cursor !== null) {
        live.textContent = `Selected ${describe(cursor)}`;
        draw();
        onCell(cursor);
      }
      return;
    }
    const origin = cursor ?? selected ?? 0;
    let row = Math.floor(origin / gridN);
    let column = origin % gridN;
    if (key === "Home") {
      cursor = 0;
    } else if (key === "End") {
      cursor = total - 1;
    } else {
      if (key === "ArrowUp") row = Math.min(gridN - 1, row + 1);
      else if (key === "ArrowDown") row = Math.max(0, row - 1);
      else if (key === "ArrowLeft") column = Math.max(0, column - 1);
      else if (key === "ArrowRight") column = Math.min(gridN - 1, column + 1);
      cursor = row * gridN + column;
    }
    live.textContent = `Focused ${describe(cursor)}`;
    draw();
  }

  function onDprChange() {
    watchDpr();
    resize();
  }

  function watchDpr() {
    if (media && typeof media.removeEventListener === "function") {
      media.removeEventListener("change", onDprChange);
    }
    if (typeof matchMedia === "function") {
      media = matchMedia(`(resolution: ${globalThis.devicePixelRatio || 1}dppx)`);
      if (typeof media.addEventListener === "function") {
        media.addEventListener("change", onDprChange);
      }
    } else {
      media = null;
    }
  }

  function render(nextPayload, selectedCellIndex = null) {
    payload = nextPayload && typeof nextPayload === "object" ? nextPayload : null;
    cells = payload && Array.isArray(payload.cells) ? payload.cells : [];
    gridN = payload && Number.isInteger(payload.grid_n) ? payload.grid_n : 0;
    const total = gridN * gridN;
    selected = Number.isInteger(selectedCellIndex)
      && selectedCellIndex >= 0 && selectedCellIndex < total
      ? selectedCellIndex
      : null;
    cursor = selected;
    if (payload) {
      const descriptor = payload.case && typeof payload.case === "object" ? payload.case : {};
      const summary = descriptor.summary && typeof descriptor.summary === "object"
        ? descriptor.summary
        : null;
      const counts = summary
        ? `, ${summary.timely_cells} timely, ${summary.late_cells} late,`
          + ` ${summary.unreachable_cells} unreachable, ${summary.weather_closed_cells} weather closed`
        : "";
      canvas.setAttribute(
        "aria-label",
        `Coverage outcome map, case ${descriptor.case_id ?? "unknown"},`
          + ` ${gridN} by ${gridN} cells${counts}. Arrow keys move, Enter selects.`,
      );
      live.textContent = selected === null
        ? "No cell selected."
        : `Selected ${describe(selected)}`;
    } else {
      canvas.setAttribute("aria-label", "Coverage outcome map, no case loaded");
      live.textContent = "No coverage case loaded.";
    }
    resize();
  }

  function setBusy(next) {
    busy = next === true;
    view.setAttribute("aria-busy", String(busy));
    canvas.setAttribute("aria-busy", String(busy));
  }

  function handleWindowResize() {
    resize();
  }

  canvas.addEventListener("pointerdown", handlePointerDown);
  canvas.addEventListener("keydown", handleKeyDown);
  if (typeof ResizeObserver === "function") {
    observer = new ResizeObserver(() => resize());
    observer.observe(canvas);
  }
  if (typeof window !== "undefined") {
    window.addEventListener("resize", handleWindowResize);
  }
  watchDpr();
  resize();

  function destroy() {
    canvas.removeEventListener("pointerdown", handlePointerDown);
    canvas.removeEventListener("keydown", handleKeyDown);
    if (observer) observer.disconnect();
    if (media && typeof media.removeEventListener === "function") {
      media.removeEventListener("change", onDprChange);
    }
    if (typeof window !== "undefined") {
      window.removeEventListener("resize", handleWindowResize);
    }
    view.remove();
  }

  return { render, setBusy, destroy };
}

export { cellFromPoint, createCoverageMap };

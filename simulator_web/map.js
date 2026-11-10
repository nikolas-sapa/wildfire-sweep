const SVG_NS = "http://www.w3.org/2000/svg";
const WIDTH = 640;
const HEIGHT = 480;
const PLOT = { left: 120, top: 40, size: 400 };
const KEY_STEP_KM = 0.5;

function svgElement(name, attributes = {}, text = "") {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, String(value));
  }
  if (text) node.textContent = text;
  return node;
}

function clamp(value, low, high) {
  return Math.min(Math.max(value, low), high);
}

function createMap(
  container,
  { onTarget = () => {}, onAlert = () => {}, idPrefix = "mission-map" } = {},
) {
  const titleId = `${idPrefix}-title`;
  const descriptionId = `${idPrefix}-description`;
  const svg = svgElement("svg", {
    class: "map-svg",
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
    role: "group",
    tabindex: "0",
    "aria-labelledby": `${titleId} ${descriptionId}`,
  });
  let view = {};
  let dragging = false;

  function pointToPixel(point, side) {
    return [
      PLOT.left + (point[0] / side) * PLOT.size,
      PLOT.top + PLOT.size - (point[1] / side) * PLOT.size,
    ];
  }

  function drawGrid(side) {
    svg.append(
      svgElement("rect", {
        class: "map-frame",
        x: PLOT.left,
        y: PLOT.top,
        width: PLOT.size,
        height: PLOT.size,
      }),
    );
    for (let tick = 0; tick <= 4; tick += 1) {
      const fraction = tick / 4;
      const x = PLOT.left + fraction * PLOT.size;
      const y = PLOT.top + fraction * PLOT.size;
      if (tick > 0 && tick < 4) {
        svg.append(
          svgElement("line", {
            class: "map-grid-line",
            x1: x,
            y1: PLOT.top,
            x2: x,
            y2: PLOT.top + PLOT.size,
          }),
          svgElement("line", {
            class: "map-grid-line",
            x1: PLOT.left,
            y1: y,
            x2: PLOT.left + PLOT.size,
            y2: y,
          }),
        );
      }
      const value = (side * fraction).toFixed(0);
      svg.append(
        svgElement(
          "text",
          { class: "map-axis", x, y: PLOT.top + PLOT.size + 20, "text-anchor": "middle" },
          value,
        ),
        svgElement(
          "text",
          {
            class: "map-axis",
            x: PLOT.left - 12,
            y: PLOT.top + PLOT.size - fraction * PLOT.size + 4,
            "text-anchor": "end",
          },
          value,
        ),
      );
    }
    svg.append(
      svgElement(
        "text",
        {
          class: "map-axis",
          x: PLOT.left + PLOT.size / 2,
          y: HEIGHT - 12,
          "text-anchor": "middle",
        },
        "East (km)",
      ),
      svgElement(
        "text",
        {
          class: "map-axis",
          x: 18,
          y: PLOT.top + PLOT.size / 2,
          "text-anchor": "middle",
          transform: `rotate(-90 18 ${PLOT.top + PLOT.size / 2})`,
        },
        "North (km)",
      ),
    );
  }

  function drawBases(bases, side) {
    for (const base of bases || []) {
      const [x, y] = pointToPixel([base.x_km, base.y_km], side);
      const available = base.available !== false;
      const marker = svgElement("g", {
        class: `map-base-marker${available ? "" : " map-base-marker-offline"}`,
        role: "img",
        "aria-label": `Base ${base.id}${available ? ", available" : ", unavailable"}`,
      });
      marker.append(
        svgElement("circle", {
          class: `map-base${available ? " map-base-available" : " map-base-unavailable"}`,
          cx: x,
          cy: y,
          r: 7,
        }),
        svgElement(
          "text",
          { class: "map-base-label", x: x + 10, y: y - 8 },
          String(base.id),
        ),
      );
      if (!available) {
        marker.append(
          svgElement("line", {
            class: "map-base-cross",
            x1: x - 3,
            y1: y - 3,
            x2: x + 3,
            y2: y + 3,
          }),
          svgElement("line", {
            class: "map-base-cross",
            x1: x - 3,
            y1: y + 3,
            x2: x + 3,
            y2: y - 3,
          }),
        );
      }
      svg.append(marker);
    }
  }

  function drawTarget(point, bases, candidates, selectedBaseId, side) {
    if (!Array.isArray(point) || point.length !== 2) return;
    const selected = (bases || []).find((base) => base.id === selectedBaseId);
    if (selected && (candidates || []).some((candidate) => candidate.base_id === selectedBaseId)) {
      const [baseX, baseY] = pointToPixel([selected.x_km, selected.y_km], side);
      const [targetX, targetY] = pointToPixel(point, side);
      svg.append(
        svgElement("line", {
          class: "map-track",
          x1: baseX,
          y1: baseY,
          x2: targetX,
          y2: targetY,
        }),
      );
    }
    const [x, y] = pointToPixel(point, side);
    svg.append(
      svgElement("circle", { class: "map-target", cx: x, cy: y, r: 10 }),
      svgElement("circle", { class: "map-target-core", cx: x, cy: y, r: 3 }),
    );
  }

  function drawAlerts(alerts, selectedIndex, side) {
    const outcomeMarkers = view.outcome_markers === true;
    for (const alert of alerts || []) {
      const [x, y] = pointToPixel([alert.x_km, alert.y_km], side);
      const selected = alert.index === selectedIndex;
      const status = outcomeMarkers && typeof alert.status === "string"
        ? alert.status
        : null;
      const marker = svgElement("g", {
        class: `map-alert-marker${status ? ` map-alert-status-${status}` : ""}`,
        role: "button",
        tabindex: "0",
        "data-map-alert": alert.index,
        "aria-pressed": selected ? "true" : "false",
        "aria-label": `Select captured alert ${alert.index + 1}, ${status ? `recorded outcome ${status}` : alert.status}`,
      });
      const shape = alert.is_real ? "circle" : "rect";
      const size = selected ? 11 : 7;
      const attributes = shape === "circle"
        ? { cx: x, cy: y, r: size }
        : { x: x - size, y: y - size, width: size * 2, height: size * 2, transform: `rotate(45 ${x} ${y})` };
      marker.append(
        svgElement(shape, {
          ...attributes,
          class: `map-alert ${alert.is_real ? "map-alert-real" : "map-alert-false"}${selected ? " map-alert-selected" : ""}`,
        }),
      );
      if (status === "unreachable") {
        marker.append(
          svgElement("line", {
            class: "map-alert-cross",
            x1: x - size,
            y1: y - size,
            x2: x + size,
            y2: y + size,
            stroke: "#596575",
            "stroke-width": 1.5,
          }),
          svgElement("line", {
            class: "map-alert-cross",
            x1: x - size,
            y1: y + size,
            x2: x + size,
            y2: y - size,
            stroke: "#596575",
            "stroke-width": 1.5,
          }),
        );
      } else if (status === "late") {
        const outlineAttributes = shape === "circle"
          ? { cx: x, cy: y, r: size + 4 }
          : {
              x: x - size - 4,
              y: y - size - 4,
              width: (size + 4) * 2,
              height: (size + 4) * 2,
              transform: `rotate(45 ${x} ${y})`,
            };
        marker.append(
          svgElement(shape, {
            ...outlineAttributes,
            class: "map-alert-outline",
            fill: "none",
            stroke: "#596575",
            "stroke-width": 1.5,
            "stroke-dasharray": "3 2",
          }),
        );
      }
      marker.addEventListener("click", () => onAlert(alert.index));
      marker.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onAlert(alert.index);
        }
      });
      svg.append(marker);
    }
  }

  function render(nextView = {}) {
    view = nextView;
    svg.replaceChildren();
    const title = svgElement("title", { id: titleId }, "Synthetic model-space map");
    const description = svgElement(
      "desc",
      { id: descriptionId },
      view.mode === "replay"
        ? "Captured alert locations. No base assignments or flight routes are shown."
        : "Synthetic base locations and the current alert target.",
    );
    svg.append(title, description);
    const side = Number(view.domain_side_km);
    if (!Number.isFinite(side) || side <= 0) {
      svg.setAttribute("aria-label", "Waiting for model-space metadata");
      return;
    }
    svg.setAttribute(
      "aria-label",
      view.mode === "replay"
        ? "Captured season alert locations in synthetic model space"
        : "Mission bases and target in synthetic model space",
    );
    drawGrid(side);
    drawBases(view.bases, side);
    if (view.mode === "replay") {
      drawAlerts(view.alerts, view.selected_alert_index, side);
    } else {
      drawTarget(
        view.point_km,
        view.bases,
        view.candidates,
        view.selected_base_id,
        side,
      );
    }
  }

  function targetFromPointer(event) {
    const side = Number(view.domain_side_km);
    if (!Number.isFinite(side) || side <= 0) return;
    const screenTransform = svg.getScreenCTM();
    if (!screenTransform) return;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    let localPoint;
    try {
      localPoint = point.matrixTransform(screenTransform.inverse());
    } catch {
      return;
    }
    const x = localPoint.x;
    const y = localPoint.y;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    if (
      x < PLOT.left ||
      x > PLOT.left + PLOT.size ||
      y < PLOT.top ||
      y > PLOT.top + PLOT.size
    ) {
      return;
    }
    const east = clamp(((x - PLOT.left) / PLOT.size) * side, 0, side);
    const north = clamp(((PLOT.top + PLOT.size - y) / PLOT.size) * side, 0, side);
    onTarget([east, north]);
  }

  function handlePointerDown(event) {
    if (view.mode === "replay") return;
    dragging = true;
    if (typeof svg.setPointerCapture === "function") {
      svg.setPointerCapture(event.pointerId);
    }
    targetFromPointer(event);
  }

  function handlePointerMove(event) {
    if (dragging) targetFromPointer(event);
  }

  function handlePointerUp() {
    dragging = false;
  }

  function handleKeyDown(event) {
    if (view.mode === "replay" || !Array.isArray(view.point_km)) return;
    const offsets = {
      ArrowLeft: [-KEY_STEP_KM, 0],
      ArrowRight: [KEY_STEP_KM, 0],
      ArrowDown: [0, -KEY_STEP_KM],
      ArrowUp: [0, KEY_STEP_KM],
    };
    const offset = offsets[event.key];
    if (!offset) return;
    event.preventDefault();
    const side = Number(view.domain_side_km);
    onTarget([
      clamp(Number(view.point_km[0]) + offset[0], 0, side),
      clamp(Number(view.point_km[1]) + offset[1], 0, side),
    ]);
  }

  svg.addEventListener("pointerdown", handlePointerDown);
  svg.addEventListener("pointermove", handlePointerMove);
  svg.addEventListener("pointerup", handlePointerUp);
  svg.addEventListener("pointercancel", handlePointerUp);
  svg.addEventListener("keydown", handleKeyDown);
  container.querySelector(".map-loading")?.remove();
  container.append(svg);

  return {
    render,
    destroy() {
      svg.removeEventListener("pointerdown", handlePointerDown);
      svg.removeEventListener("pointermove", handlePointerMove);
      svg.removeEventListener("pointerup", handlePointerUp);
      svg.removeEventListener("pointercancel", handlePointerUp);
      svg.removeEventListener("keydown", handleKeyDown);
      svg.remove();
    },
  };
}

export { createMap };

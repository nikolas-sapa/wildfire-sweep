const EXPORT_CASE_ID_LIMIT = 120;

function element(name, className, text = "") {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exportFileName(caseId) {
  if (typeof caseId !== "string") return null;
  const cleaned = caseId
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^\.+/, "")
    .slice(0, EXPORT_CASE_ID_LIMIT)
    .replace(/[.-]+$/, "");
  return cleaned === "" ? null : `wildfire-coverage-${cleaned}.json`;
}

function createCoverageExport(container) {
  const actions = element("div", "cov-export-actions");
  const button = element(
    "button",
    "cov-button cov-button-primary",
    "Download snapshot JSON",
  );
  button.type = "button";
  button.disabled = true;
  actions.append(button);

  const status = element(
    "p",
    "cov-status",
    "Export becomes available after a successful result.",
  );
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  container.append(actions, status);

  let busy = false;
  let destroyed = false;
  let snapshotText = null;
  let filename = null;
  const objectUrls = new Map();

  function releaseUrl(url) {
    const timer = objectUrls.get(url);
    if (timer !== undefined) window.clearTimeout(timer);
    URL.revokeObjectURL(url);
    objectUrls.delete(url);
  }

  function showStatus(message) {
    status.textContent = String(message);
    status.classList.remove("cov-error");
    status.setAttribute("role", "status");
  }

  function showError(message) {
    status.textContent = String(message);
    status.classList.add("cov-error");
    status.setAttribute("role", "alert");
  }

  function refresh() {
    button.disabled = busy || destroyed || snapshotText === null;
    actions.setAttribute("aria-busy", String(busy));
  }

  function download() {
    if (snapshotText === null || filename === null) return;
    let url = null;
    let link = null;
    try {
      const blob = new Blob([snapshotText], { type: "application/json" });
      url = URL.createObjectURL(blob);
      link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.hidden = true;
      container.append(link);
      link.click();
      link.remove();
      objectUrls.set(url, window.setTimeout(() => releaseUrl(url), 0));
      showStatus(`Download started: ${filename}`);
    } catch {
      try {
        link?.remove();
      } catch {}
      if (url !== null) {
        try {
          releaseUrl(url);
        } catch {}
      }
      showError("Download could not be started.");
    }
  }

  function setSnapshot(snapshot) {
    if (destroyed) return;
    snapshotText = null;
    filename = null;
    if (snapshot === null || snapshot === undefined) {
      showStatus("Export becomes available after a successful result.");
    } else if (!isRecord(snapshot)) {
      showError("Received snapshot is not a JSON object.");
    } else {
      const name = exportFileName(snapshot.primary?.case?.case_id);
      if (name === null) {
        showError("Received snapshot has no usable primary case identifier.");
      } else {
        try {
          snapshotText = JSON.stringify(snapshot, null, 2);
        } catch {
          snapshotText = null;
        }
        if (snapshotText === null) {
          showError("Received snapshot could not be serialized.");
        } else {
          filename = name;
          showStatus("Ready to download the exact received JSON snapshot.");
        }
      }
    }
    refresh();
  }

  function setBusy(nextBusy) {
    if (destroyed) return;
    busy = Boolean(nextBusy);
    refresh();
  }

  button.addEventListener("click", download);
  refresh();

  return {
    setSnapshot,
    setBusy,
    destroy() {
      destroyed = true;
      button.removeEventListener("click", download);
      for (const url of [...objectUrls.keys()]) releaseUrl(url);
      actions.remove();
      status.remove();
    },
  };
}

export { createCoverageExport };

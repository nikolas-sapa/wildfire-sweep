function createExportButton(container) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "export-button app-button app-button-large";
  button.setAttribute("data-slot", "button");
  button.setAttribute("data-size", "large");
  button.disabled = true;
  button.textContent = "Download received snapshot";
  container.append(button);

  let snapshotText = null;
  let snapshotMode = "mission";
  const objectUrls = new Map();

  function releaseUrl(url) {
    const timer = objectUrls.get(url);
    if (timer !== undefined) window.clearTimeout(timer);
    URL.revokeObjectURL(url);
    objectUrls.delete(url);
  }

  function download() {
    if (!snapshotText) return;
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const blob = new Blob([snapshotText], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `wildfire-mission-${snapshotMode}-${timestamp}.json`;
    link.hidden = true;
    container.append(link);
    link.click();
    link.remove();
    objectUrls.set(url, window.setTimeout(() => releaseUrl(url), 0));
  }

  function setSnapshot(snapshot) {
    snapshotText = null;
    if (snapshot && typeof snapshot === "object") {
      snapshotMode = snapshot.mode === "replay" || snapshot.result?.mode === "replay"
        ? "replay"
        : "mission";
      try {
        snapshotText = JSON.stringify(snapshot, null, 2);
      } catch {
        snapshotText = null;
      }
    }
    button.disabled = snapshotText === null;
  }

  button.addEventListener("click", download);

  return {
    setSnapshot,
    destroy() {
      button.removeEventListener("click", download);
      button.remove();
      for (const url of objectUrls.keys()) releaseUrl(url);
    },
  };
}

export { createExportButton };

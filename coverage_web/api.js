const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost"]);

function localBaseUrl(value) {
  if (typeof value !== "string") {
    throw new Error("baseUrl must be a string");
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    parsed = null;
  }
  const port = parsed !== null && parsed.port !== "" ? Number(parsed.port) : null;
  if (
    parsed === null
    || parsed.protocol !== "http:"
    || !LOCAL_HOSTS.has(parsed.hostname)
    || parsed.username !== ""
    || parsed.password !== ""
    || parsed.pathname !== "/"
    || parsed.search !== ""
    || parsed.hash !== ""
    || (port !== null && !(port >= 1 && port <= 65535))
  ) {
    throw new Error("baseUrl must use http://127.0.0.1 or http://localhost without credentials");
  }
  return String(value).replace(/\/+$/, "");
}

function plainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function createCoverageApi({ fetchImpl = globalThis.fetch, baseUrl = "" } = {}) {
  const base = baseUrl === "" ? "" : localBaseUrl(baseUrl);

  async function request(path, signal) {
    const response = await fetchImpl(base + path, {
      method: "GET",
      credentials: "same-origin",
      redirect: "error",
      headers: { Accept: "application/json" },
      signal,
    });
    const text = await response.text();
    let data = null;
    let parsed = true;
    try {
      data = JSON.parse(text);
    } catch {
      parsed = false;
    }
    if (!response.ok) {
      if (response.status >= 300 && response.status < 400) {
        throw new Error(`HTTP ${response.status}: redirects are not followed`);
      }
      const message = plainObject(data) && typeof data.error === "string"
        ? data.error
        : "request failed";
      throw new Error(`HTTP ${response.status}: ${message}`);
    }
    if (response.redirected === true) {
      throw new Error("redirects are not followed");
    }
    const contentType = String(response.headers?.get?.("Content-Type") ?? "")
      .split(";", 1)[0]
      .trim()
      .toLowerCase();
    if (
      contentType !== "application/json"
      && !(contentType.startsWith("application/") && contentType.endsWith("+json"))
    ) {
      throw new Error("server returned a non-JSON response");
    }
    if (!parsed) {
      throw new Error("server returned invalid JSON");
    }
    if (!plainObject(data)) {
      throw new Error("server response must be a JSON object");
    }
    return data;
  }

  return {
    async catalog({ signal } = {}) {
      return request("/api/coverage/catalog", signal);
    },
    async case(caseId, { signal } = {}) {
      const query = new URLSearchParams({ case: caseId });
      return request(`/api/coverage?${query.toString()}`, signal);
    },
  };
}

export { createCoverageApi };

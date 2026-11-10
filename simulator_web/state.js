function deepCopy(value) {
  return structuredClone(value);
}

function createStore(initial = {}) {
  let state = deepCopy(initial);
  const subscribers = new Set();

  function getState() {
    return deepCopy(state);
  }

  function patch(partial) {
    state = { ...state, ...deepCopy(partial) };
    for (const subscriber of subscribers) {
      subscriber(deepCopy(state));
    }
  }

  function subscribe(subscriber) {
    subscribers.add(subscriber);
    return function unsubscribe() {
      subscribers.delete(subscriber);
    };
  }

  return { getState, patch, subscribe };
}

function createApi(baseUrl = "") {
  async function request(path, options) {
    const response = await fetch(baseUrl + path, options);
    const text = await response.text();
    let data = null;
    if (text !== "") {
      try {
        data = JSON.parse(text);
      } catch {
        data = null;
      }
    }
    if (!response.ok) {
      const message = data && typeof data.error === "string"
        ? data.error
        : `Request failed (HTTP ${response.status})`;
      throw new Error(message);
    }
    if (text !== "" && data === null) {
      throw new Error("Invalid JSON response");
    }
    return data;
  }

  function catalog() {
    return request("/api/catalog");
  }

  function mission(payload) {
    return request("/api/mission", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  function replay(caseId, season) {
    const query = new URLSearchParams({
      case: String(caseId),
      season: String(season),
    });
    return request(`/api/replay?${query.toString()}`);
  }

  return { catalog, mission, replay };
}

export { createStore, createApi };

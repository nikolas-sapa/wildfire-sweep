import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../api.js", import.meta.url), "utf8");
const { createCoverageApi } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

function abortError() {
  return new DOMException("The operation was aborted.", "AbortError");
}

function jsonResponse(body, { status = 200, contentType = "application/json; charset=utf-8" } = {}) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    headers: {
      get: (name) => (String(name).toLowerCase() === "content-type" ? contentType : null),
    },
    text: async () => text,
    json: async () => JSON.parse(text),
  };
}

function stubFetch(handler = () => jsonResponse({})) {
  const calls = [];
  const fetchImpl = (input, init) => {
    calls.push({ input, init });
    return handler(input, init);
  };
  return { calls, fetchImpl };
}

function callUrl(call) {
  const { input } = call;
  return typeof input === "string" ? input : String(input?.url ?? input);
}

function callChannel(call) {
  return call.init ?? call.input ?? {};
}

function callMethod(call) {
  return (callChannel(call).method ?? "GET").toUpperCase();
}

function callSignal(call) {
  return callChannel(call).signal;
}

function callCredentials(call) {
  return callChannel(call).credentials;
}

function callBody(call) {
  return callChannel(call).body ?? null;
}

function surfaced(error, pattern) {
  let current = error;
  while (current instanceof Error) {
    if (pattern.test(current.message) || pattern.test(current.name)) return true;
    current = current.cause;
  }
  return false;
}

test("constructor issues no request and exposes only the two methods", async () => {
  const { calls, fetchImpl } = stubFetch();
  const api = createCoverageApi({ fetchImpl });
  assert.equal(calls.length, 0);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls.length, 0);
  assert.deepEqual(Object.keys(api).sort(), ["case", "catalog"]);
  assert.equal(typeof api.catalog, "function");
  assert.equal(typeof api.case, "function");
  const fallback = createCoverageApi();
  assert.equal(typeof fallback.catalog, "function");
  assert.equal(typeof fallback.case, "function");
  assert.equal(calls.length, 0);
});

test("catalog and case GET the two exact endpoints and return the JSON object", async () => {
  const { calls, fetchImpl } = stubFetch((input) =>
    jsonResponse({ echoed: callUrl({ input }) }));
  const api = createCoverageApi({ fetchImpl });
  const catalog = await api.catalog();
  assert.equal(calls.length, 1);
  assert.equal(callUrl(calls[0]), "/api/coverage/catalog");
  assert.deepEqual(catalog, { echoed: "/api/coverage/catalog" });
  const payload = await api.case("n9-h000");
  assert.equal(calls.length, 2);
  const [path, query] = callUrl(calls[1]).split("?");
  assert.equal(path, "/api/coverage");
  assert.ok(query !== undefined);
  assert.deepEqual([...new URLSearchParams(query).keys()], ["case"]);
  assert.deepEqual(payload, { echoed: callUrl(calls[1]) });
  for (const call of calls) {
    assert.equal(callMethod(call), "GET");
    assert.equal(callBody(call), null);
    assert.equal(callCredentials(call), "same-origin");
  }
});

test("opaque case IDs encode into the single case parameter", async () => {
  for (const id of ["n9-h000-o00", "odd id", "a/b?c&d=e", "100%+#", "x,y;z", "u\u0007v"]) {
    const { calls, fetchImpl } = stubFetch();
    const api = createCoverageApi({ fetchImpl });
    await api.case(id);
    const [path, query] = callUrl(calls[0]).split("?");
    assert.equal(path, "/api/coverage", id);
    assert.ok(query !== undefined, id);
    if (!/^[-._~A-Za-z0-9]+$/.test(id)) {
      assert.ok(!query.includes(id), `${JSON.stringify(id)} leaked unencoded`);
    }
    const params = new URLSearchParams(query);
    assert.deepEqual([...params.keys()], ["case"], id);
    assert.equal(params.get("case"), id);
  }
});

test("caller signals and same-origin credentials reach the transport", async () => {
  const { calls, fetchImpl } = stubFetch();
  const api = createCoverageApi({ fetchImpl });
  const controller = new AbortController();
  await api.catalog({ signal: controller.signal });
  await api.case("x", { signal: controller.signal });
  assert.equal(calls.length, 2);
  for (const call of calls) {
    assert.equal(callSignal(call), controller.signal);
    assert.equal(callCredentials(call), "same-origin");
  }
  await api.catalog();
  assert.equal(callCredentials(calls[2]), "same-origin");
});

test("non-2xx responses reject and surface the status", async () => {
  for (const status of [301, 302, 400, 404, 500, 503]) {
    const { fetchImpl } = stubFetch(() =>
      jsonResponse({ note: "failure" }, { status }));
    await assert.rejects(
      () => createCoverageApi({ fetchImpl }).catalog(),
      (error) => surfaced(error, new RegExp(String(status))),
      `HTTP ${status}`,
    );
  }
});

test("a JSON error body surfaces status or its message on non-2xx", async () => {
  const { fetchImpl } = stubFetch(() =>
    jsonResponse({ error: "coverage capture missing" }, { status: 503 }));
  await assert.rejects(
    () => createCoverageApi({ fetchImpl }).catalog(),
    (error) => surfaced(error, /503|capture missing/),
  );
});

test("transport failures reject instead of resolving", async () => {
  const { fetchImpl } = stubFetch(() => Promise.reject(new Error("socket reset")));
  const api = createCoverageApi({ fetchImpl });
  await assert.rejects(
    () => api.catalog(),
    (error) => surfaced(error, /socket reset/),
  );
  await assert.rejects(
    () => api.case("x"),
    (error) => surfaced(error, /socket reset/),
  );
});

test("malformed, non-object, empty and non-JSON bodies reject on 2xx", async () => {
  const bodies = [
    ["malformed", "{bad"],
    ["truncated", "{\"case\":"],
    ["array", "[1,2,3]"],
    ["number", "5"],
    ["string", "\"coverage\""],
    ["null", "null"],
    ["boolean", "true"],
    ["empty", ""],
    ["whitespace", "  "],
  ];
  for (const [label, body] of bodies) {
    const { fetchImpl } = stubFetch(() => jsonResponse(body));
    const api = createCoverageApi({ fetchImpl });
    await assert.rejects(() => api.catalog(), undefined, label);
    await assert.rejects(() => api.case("x"), undefined, label);
  }
  const { fetchImpl } = stubFetch(() =>
    jsonResponse("<html>not json</html>", { contentType: "text/html" }));
  await assert.rejects(() => createCoverageApi({ fetchImpl }).catalog());
});

test("an already-aborted signal rejects the request", async () => {
  const { fetchImpl } = stubFetch((input, init) => {
    const signal = callSignal({ input, init });
    return signal?.aborted
      ? Promise.reject(abortError())
      : Promise.resolve(jsonResponse({}));
  });
  const api = createCoverageApi({ fetchImpl });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    () => api.catalog({ signal: controller.signal }),
    (error) => surfaced(error, /abort/i),
  );
  await assert.rejects(
    () => api.case("x", { signal: controller.signal }),
    (error) => surfaced(error, /abort/i),
  );
});

test("aborting mid-request rejects the pending promise", async () => {
  const { fetchImpl } = stubFetch((input, init) => {
    const signal = callSignal({ input, init });
    return new Promise((resolve, reject) => {
      signal?.addEventListener("abort", () => reject(abortError()), { once: true });
    });
  });
  const api = createCoverageApi({ fetchImpl });
  const controller = new AbortController();
  const pending = api.case("x", { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, (error) => surfaced(error, /abort/i));
});

test("non-loopback and malformed base URLs never reach the transport", async () => {
  const blocked = [
    "https://example.com",
    "http://example.com",
    "http://127.0.0.1.evil.example",
    "http://0.0.0.0:8765",
    "https://127.0.0.1:8765",
    "https://localhost",
    "ftp://127.0.0.1",
    "//example.com/x",
    "http://user:pw@127.0.0.1:8765",
    "http://127.0.0.1:8765/api",
    "http://127.0.0.1:8765?x=1",
    "http://127.0.0.1:8765#frag",
    "http://[::1]:8765",
    "http://localhost:99999",
  ];
  for (const baseUrl of blocked) {
    const { calls, fetchImpl } = stubFetch();
    let api = null;
    try {
      api = createCoverageApi({ fetchImpl, baseUrl });
    } catch {
      api = null;
    }
    if (api !== null) {
      await assert.rejects(() => api.catalog(), undefined, baseUrl);
    }
    assert.equal(calls.length, 0, baseUrl);
  }
});

test("non-string base URLs reject before parsing or transport", () => {
  const { calls, fetchImpl } = stubFetch();
  for (const baseUrl of [null, 42, {}, []]) {
    assert.throws(
      () => createCoverageApi({ fetchImpl, baseUrl }),
      /baseUrl must be a string/,
    );
  }
  assert.equal(calls.length, 0);
});

test("loopback base URLs prefix the endpoints exactly", async () => {
  for (const baseUrl of ["http://127.0.0.1:8765", "http://localhost:8123"]) {
    const { calls, fetchImpl } = stubFetch();
    const api = createCoverageApi({ fetchImpl, baseUrl });
    await api.catalog();
    assert.equal(callUrl(calls[0]), `${baseUrl}/api/coverage/catalog`);
    await api.case("a b");
    const [path, query] = callUrl(calls[1]).split("?");
    assert.equal(path, `${baseUrl}/api/coverage`);
    assert.equal(new URLSearchParams(query).get("case"), "a b");
    assert.equal(calls.length, 2);
  }
});

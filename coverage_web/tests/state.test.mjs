import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../state.js", import.meta.url), "utf8");
const { createCoverageStore } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);

test("store exposes exactly getState, patch and subscribe", () => {
  const store = createCoverageStore();
  assert.deepEqual(Object.keys(store).sort(), [
    "getState",
    "patch",
    "subscribe",
  ]);
  for (const key of Object.keys(store)) {
    assert.equal(typeof store[key], "function");
  }
  assert.deepEqual(store.getState(), {});
});

test("initial state is a clone, not the caller's object", () => {
  const initial = {
    case_id: "case-a",
    selected: { index: 3, tags: ["x", "y"] },
  };
  const store = createCoverageStore(initial);
  initial.case_id = "mutated";
  initial.selected.index = 99;
  initial.selected.tags.push("z");
  initial.injected = true;
  assert.deepEqual(store.getState(), {
    case_id: "case-a",
    selected: { index: 3, tags: ["x", "y"] },
  });
});

test("patch merges each partial into state", () => {
  const store = createCoverageStore({ a: 1, keep: { x: 1 } });
  store.patch({ a: 2, added: "yes" });
  assert.deepEqual(store.getState(), { a: 2, keep: { x: 1 }, added: "yes" });
  store.patch({ added: null });
  assert.deepEqual(store.getState(), { a: 2, keep: { x: 1 }, added: null });
});

test("patch replaces whole top-level values without deep merging", () => {
  const store = createCoverageStore({ nested: { a: 1, b: 2 }, other: true });
  store.patch({ nested: { b: 20 } });
  assert.deepEqual(store.getState(), { nested: { b: 20 }, other: true });
});

test("patch stores a clone of the partial, not caller objects", () => {
  const store = createCoverageStore();
  const partial = { payload: { cells: [1, 2] } };
  store.patch(partial);
  partial.payload.cells.push(3);
  partial.payload.extra = true;
  partial.other = "new";
  assert.deepEqual(store.getState(), { payload: { cells: [1, 2] } });
});

test("getState returns an independent snapshot on every call", () => {
  const store = createCoverageStore({ nested: { list: [1] }, value: 1 });
  const first = store.getState();
  const second = store.getState();
  assert.notStrictEqual(first, second);
  assert.notStrictEqual(first.nested, second.nested);
  assert.notStrictEqual(first.nested.list, second.nested.list);
  assert.deepEqual(first, second);
  first.value = 99;
  first.nested.list.push(2);
  first.injected = true;
  assert.deepEqual(store.getState(), { nested: { list: [1] }, value: 1 });
});

test("each patch notifies a subscriber exactly once with merged state", () => {
  const store = createCoverageStore({ count: 0 });
  const seen = [];
  store.subscribe((state) => seen.push(state));
  assert.equal(seen.length, 0);
  store.patch({ count: 1 });
  assert.equal(seen.length, 1);
  assert.deepEqual(seen[0], { count: 1 });
  store.patch({ count: 2 });
  store.patch({ extra: true });
  assert.equal(seen.length, 3);
  assert.deepEqual(seen[1], { count: 2 });
  assert.deepEqual(seen[2], { count: 2, extra: true });
});

test("subscriber snapshots are isolated from state and each other", () => {
  const store = createCoverageStore({ nested: { list: [1] } });
  const received = [];
  store.subscribe((state) => received.push(state));
  store.patch({ tag: "a" });
  store.patch({ tag: "b" });
  assert.equal(received.length, 2);
  assert.notStrictEqual(received[0], received[1]);
  assert.notStrictEqual(received[0].nested, received[1].nested);
  received[0].tag = "mutated";
  received[0].nested.list.push(99);
  assert.deepEqual(received[1], { nested: { list: [1] }, tag: "b" });
  assert.deepEqual(store.getState(), { nested: { list: [1] }, tag: "b" });
});

test("unsubscribe stops all later notifications", () => {
  const store = createCoverageStore();
  const seen = [];
  const unsubscribe = store.subscribe((state) => seen.push(state));
  assert.equal(typeof unsubscribe, "function");
  store.patch({ count: 1 });
  assert.equal(seen.length, 1);
  unsubscribe();
  unsubscribe();
  store.patch({ count: 2 });
  store.patch({ count: 3 });
  assert.equal(seen.length, 1);
  assert.deepEqual(seen[0], { count: 1 });
});

test("multiple listeners are notified once per patch, independently", () => {
  const store = createCoverageStore({ v: 0 });
  const firstSeen = [];
  const secondSeen = [];
  const thirdSeen = [];
  const unsubFirst = store.subscribe((state) => firstSeen.push(state));
  store.subscribe((state) => secondSeen.push(state));
  store.subscribe((state) => thirdSeen.push(state));
  store.patch({ v: 1 });
  assert.equal(firstSeen.length, 1);
  assert.equal(secondSeen.length, 1);
  assert.equal(thirdSeen.length, 1);
  unsubFirst();
  store.patch({ v: 2 });
  assert.equal(firstSeen.length, 1);
  assert.equal(secondSeen.length, 2);
  assert.equal(thirdSeen.length, 2);
  assert.deepEqual(secondSeen[1], { v: 2 });
  assert.deepEqual(thirdSeen[1], { v: 2 });
  assert.notStrictEqual(secondSeen[1], thirdSeen[1]);
  secondSeen[1].v = 99;
  assert.equal(store.getState().v, 2);
  assert.equal(thirdSeen[1].v, 2);
});

test("a listener mutating its snapshot cannot affect other listeners", () => {
  const store = createCoverageStore({ nested: { list: [1] } });
  const observed = [];
  store.subscribe((state) => {
    state.nested.list.push(99);
    state.dirty = true;
  });
  store.subscribe((state) => observed.push(state));
  store.patch({ tag: true });
  assert.equal(observed.length, 1);
  assert.deepEqual(observed[0], { nested: { list: [1] }, tag: true });
  assert.deepEqual(store.getState(), { nested: { list: [1] }, tag: true });
});

test("each store instance keeps its own state and subscribers", () => {
  const first = createCoverageStore({ id: "first" });
  const second = createCoverageStore({ id: "second" });
  const seen = [];
  first.subscribe((state) => seen.push(state));
  second.patch({ other: true });
  assert.equal(seen.length, 0);
  first.patch({ mark: 1 });
  assert.deepEqual(first.getState(), { id: "first", mark: 1 });
  assert.deepEqual(second.getState(), { id: "second", other: true });
  assert.equal(seen.length, 1);
});

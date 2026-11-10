function deepCopy(value) {
  return structuredClone(value);
}

function createCoverageStore(initial = {}) {
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

export { createCoverageStore };

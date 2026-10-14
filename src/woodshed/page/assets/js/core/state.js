// One store for the page state. Views read it and subscribe; nothing else holds state.
(function () {
  "use strict";
  const W = window.Woodshed;

  W.createStore = function createStore(initial) {
    let state = Object.freeze({ ...initial });
    const listeners = new Set();
    return {
      get: () => state,
      // set({ transpose: 2 }) merges, then tells every listener which keys changed.
      set(patch) {
        const changed = Object.keys(patch).filter((k) => state[k] !== patch[k]);
        if (!changed.length) return;
        state = Object.freeze({ ...state, ...patch });
        for (const fn of listeners) fn(state, new Set(changed));
      },
      on(fn) {
        listeners.add(fn);
        return () => listeners.delete(fn);
      },
    };
  };
})();

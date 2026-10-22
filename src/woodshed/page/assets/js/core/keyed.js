// A store of values by key, kept by this browser and shared with the band's library the way the
// chord picks are (app.py _merge_keyed): two devices changing it at once both keep their changes,
// the later value of an entry wins, and an entry taken back is remembered with the value it took
// back until the library has heard of it.
(function () {
  "use strict";
  const W = window.Woodshed;
  const PENDING_MAX = 2000;

  W.keyed = function keyed(storageKey, valid) {
    let values = {};
    let pending = new Map(); // key -> the value taken back here, not yet heard by the library
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    const clean = (obj) => {
      const out = {};
      if (!obj || typeof obj !== "object" || Array.isArray(obj)) return out;
      for (const [k, v] of Object.entries(obj)) if (valid(k, v)) out[k] = v;
      return out;
    };
    function save() {
      try {
        localStorage.setItem(storageKey, JSON.stringify(values));
        localStorage.setItem(storageKey + ":removed", JSON.stringify(Object.fromEntries(pending)));
      } catch (err) {
        /* private mode or storage off: the change still applies to this visit */
      }
    }
    function restore() {
      try {
        values = clean(JSON.parse(localStorage.getItem(storageKey) || "{}"));
      } catch (err) {
        values = {};
      }
      try {
        const removed = JSON.parse(localStorage.getItem(storageKey + ":removed") || "{}");
        const entries = removed && typeof removed === "object" && !Array.isArray(removed) ? Object.entries(removed) : [];
        pending = new Map(entries.filter(([k, v]) => v === null || valid(k, v)).slice(0, PENDING_MAX));
      } catch (err) {
        pending = new Map();
      }
    }
    function heard(keys) {
      const before = pending.size;
      for (const k of keys) pending.delete(String(k));
      if (pending.size !== before) save();
    }
    return {
      restore,
      heard,
      values: () => ({ ...values }),
      pending: () => new Map(pending),
      get: (k) => values[k],
      set(k, v) {
        values[k] = v;
        pending.delete(k);
        save();
      },
      take(k) {
        if (!(k in values) && !pending.has(k)) return;
        pending.set(k, k in values ? values[k] : null);
        delete values[k];
        save();
      },
      clear() {
        for (const k of Object.keys(values)) pending.set(k, values[k]);
        values = {};
        save();
      },
      // The library's copy: taken back by the band, this device's copy goes if it is the value
      // removed (a newer one made here offline stays); taken back here and not yet heard there, the
      // library's copy goes if it is the one removed here, else the band's later value wins.
      // Returns whether anything changed and what this device still has to share.
      merge(theirsIn, removedIn) {
        const removed = removedIn && typeof removedIn === "object" && !Array.isArray(removedIn) ? removedIn : {};
        heard(Object.keys(removed));
        const mine = { ...values };
        const theirs = clean(theirsIn);
        for (const [k, was] of Object.entries(removed)) if (same(mine[k], was)) delete mine[k];
        for (const [k, was] of pending) {
          if (!(k in theirs) || same(theirs[k], was)) delete theirs[k];
          else heard([k]);
        }
        const next = { ...mine, ...theirs };
        const changed = !same(Object.entries(next).sort(), Object.entries(values).sort());
        values = next;
        save();
        const share = {};
        for (const k of pending.keys()) share[k] = null;
        for (const k of Object.keys(mine)) if (!(k in theirs)) share[k] = mine[k];
        return { changed, share };
      },
    };
  };
})();

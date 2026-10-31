// The woodshed namespace and small DOM helpers. Loaded first; every other script adds to it.
// Song data is always set as text (textContent, attributes), never parsed as markup.
(function () {
  "use strict";
  const W = (window.Woodshed = window.Woodshed || {});

  // h("button", { class: "btn", "data-testid": "play", onclick: fn }, "Play", child...)
  W.h = function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else el.setAttribute(k, v === true ? "" : String(v));
    }
    W.append(el, children);
    return el;
  };

  W.append = function append(el, children) {
    for (const c of children.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  };

  W.$ = (id) => document.getElementById(id);
  W.clear = function clear(el, ...children) {
    el.replaceChildren();
    return W.append(el, children);
  };
  // A control drawn again under the focus keeps it (spec 025): `draw` redraws `el`; when the focused element was
  // inside and is gone, the one new element with the same data-testid takes the focus back, unless it is
  // disabled or hidden. Opt-in, for the controls a musician presses in place. A focus given here is not a Tab:
  // the input method stays as it was (a button clicked keeps Space for the music).
  W.keepFocus = function keepFocus(el, draw) {
    const had = document.activeElement;
    const key = had && had !== document.body && el.contains(had) ? had.getAttribute("data-testid") : null;
    const out = draw();
    if (!key || had.isConnected) return out;
    const now = document.activeElement;
    if (now && now !== document.body && now !== document.documentElement) return out; // something else took it
    const same = el.querySelectorAll('[data-testid="' + CSS.escape(key) + '"]');
    const next = same.length === 1 ? same[0] : null;
    if (next && !next.disabled && next.getClientRects().length) next.focus({ preventScroll: true });
    return out;
  };

  // SVG built from numbers and fixed strings only: the one place markup is parsed.
  const SVG_NS = "http://www.w3.org/2000/svg";
  W.s = function s(tag, attrs, ...children) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, String(v));
    return W.append(el, children);
  };

  // Chord and note names with real flat and sharp signs: "Bb" -> B, then a ♭ in its own span.
  // The song's own names: never translated (core/i18n.js), nor by the browser.
  W.chordNode = function chordNode(name, cls) {
    const m = /^([A-G])([b#]?)(.*)$/.exec(name);
    const el = W.h("span", { class: cls || "cn", translate: "no" });
    if (!m) return W.append(el, [name]);
    const sign = (x) => (x === "b" ? "♭" : x === "#" ? "♯" : "");
    const acc = sign(m[2]);
    // A slash bass ("D/F#") gets its own sign too.
    const slash = /^(.*)\/([A-G])([b#]?)$/.exec(m[3]);
    const rest = slash ? [slash[1], "/", slash[2], sign(slash[3]) ? W.h("span", { class: "acc" }, sign(slash[3])) : null] : [m[3]];
    return W.append(el, [m[1], acc ? W.h("span", { class: "acc" }, acc) : null, ...rest]);
  };
  W.prettyText = (name) =>
    name.replace(/^([A-G])b/, "$1♭").replace(/^([A-G])#/, "$1♯").replace(/\/([A-G])b$/, "/$1♭").replace(/\/([A-G])#$/, "/$1♯");

  // 75.4 -> "1:15", or "1:15.4" with tenths. Rounded first, so 9.96 s reads "0:10.0".
  W.fmt = function fmt(t, tenths) {
    const total = tenths ? Math.round(Math.max(0, t) * 10) / 10 : Math.floor(Math.max(0, t));
    const m = Math.floor(total / 60);
    const sec = total - m * 60;
    return m + ":" + (sec < 10 ? "0" : "") + (tenths ? sec.toFixed(1) : String(sec));
  };

  // A library row's title as the band named it (spec 031): "artist - title", else the recording's.
  W.shownTitle = (row) => {
    const b = (row && row.band) || {};
    if (!b.title && !b.artist) return row.title;
    const t = String(row.title || "");
    const name = b.title || (t.includes(" - ") ? t.slice(t.indexOf(" - ") + 3) : t); // an artist alone: its song name
    return [b.artist, name].filter(Boolean).join(" - ");
  };

  // An iPhone or an iPad: iPadOS Safari says "Macintosh", only its touch points tell it apart.
  W.iOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
})();

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
    const acc = m[2] === "b" ? "♭" : m[2] === "#" ? "♯" : "";
    return W.append(el, [m[1], acc ? W.h("span", { class: "acc" }, acc) : null, m[3]]);
  };
  W.prettyText = (name) => name.replace(/^([A-G])b/, "$1♭").replace(/^([A-G])#/, "$1♯");

  // 75.4 -> "1:15", or "1:15.4" with tenths. Rounded first, so 9.96 s reads "0:10.0".
  W.fmt = function fmt(t, tenths) {
    const total = tenths ? Math.round(Math.max(0, t) * 10) / 10 : Math.floor(Math.max(0, t));
    const m = Math.floor(total / 60);
    const sec = total - m * 60;
    return m + ":" + (sec < 10 ? "0" : "") + (tenths ? sec.toFixed(1) : String(sec));
  };
})();

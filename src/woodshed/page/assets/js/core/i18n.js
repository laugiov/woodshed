// The page in English or French (the language is chosen in core/prefs.js). Every sentence of the
// page's own goes through W.t; the song's own text (title, chords, words) never does, and is marked
// translate="no" so a browser's translator leaves it alone too. The French is in core/i18n-fr.js.
(function () {
  "use strict";
  const W = (window.Woodshed = window.Woodshed || {});
  W.FR = W.FR || {};
  W.onLang = W.onLang || []; // what draws itself again in the other language

  W.lang = () => (document.documentElement.lang === "fr" ? "fr" : "en");

  // W.t(text, { n: 3 }): the English text is the key, its {names} are filled in.
  W.t = function t(text, vars) {
    let out = W.lang() === "fr" && Object.prototype.hasOwnProperty.call(W.FR, text) ? W.FR[text] : text;
    if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(vars, k) ? String(vars[k]) : m));
    return out;
  };

  // A translated sentence holding elements: W.nodes(W.t("sounds {chord}"), { chord: el }) gives
  // ["sounds ", el], for h() or W.clear(). W.t leaves the {names} it was not given.
  W.nodes = function nodes(text, parts) {
    return text.split(/(\{\w+\})/).filter((x) => x !== "").map((x) => {
      const k = /^\{(\w+)\}$/.exec(x);
      return k && Object.prototype.hasOwnProperty.call(parts, k[1]) ? parts[k[1]] : x;
    });
  };

  // The names the analysis gives the parts (sections.ROLE_NAMES, "Part B"), kept with their number
  // or letter, also when the words named them (their tags set the role, the name is the analysis's).
  const PARTS = {
    Intro: "Intro", Verse: "Couplet", "Pre-chorus": "Pré-refrain", Chorus: "Refrain", Bridge: "Pont",
    Instrumental: "Instrumental", Outro: "Outro", Part: "Partie",
  }; // prettier-ignore
  // A part's name in the language chosen: the analysis's ("Verse 2") translated, a name the band typed
  // (a part with `custom`) as typed, the same on every device.
  W.partName = function partName(part) {
    if (part && typeof part === "object") return part.custom ? part.name : W.partName(part.name);
    const name = part;
    if (W.lang() !== "fr" || typeof name !== "string") return name;
    const m = /^(Intro|Verse|Pre-chorus|Chorus|Bridge|Instrumental|Outro|Part)((?: [A-Z0-9′″]+)?)$/.exec(name);
    return m ? PARTS[m[1]] + m[2] : name;
  };

  // The page's fixed text (body.html, home.html): each text and label in W.FR, with its English kept
  // to switch back. A text the page's code wrote since (a button's label) is the new English.
  const kept = new WeakMap(); // text node -> {en, said}; element -> {attribute: {en, said}}
  const ATTRS = ["title", "aria-label", "placeholder"];
  const skip = (el) => el.closest('[translate="no"], script, style, svg');

  function sayAgain(en) {
    const trimmed = en.trim();
    const key = trimmed.replace(/\s+/g, " "); // as written in the HTML, over several lines
    return key && Object.prototype.hasOwnProperty.call(W.FR, key) ? en.replace(trimmed, W.t(key)) : null;
  }

  // The English of a text now `value`: the one kept, unless the code changed the text since.
  const englishOf = (memo, value) => (memo && memo.said === value ? memo.en : value);

  W.translatePage = function translatePage(root) {
    const top = root || document.body;
    if (!top) return;
    const walker = document.createTreeWalker(top, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.nodeType === 1 && skip(n) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    for (let n = walker.currentNode; n; n = walker.nextNode()) {
      if (n.nodeType === 3) {
        if (n.parentElement && skip(n.parentElement)) continue;
        const en = englishOf(kept.get(n), n.nodeValue);
        const said = sayAgain(en);
        if (said === null) continue;
        kept.set(n, { en, said });
        n.nodeValue = said;
      } else {
        for (const a of ATTRS) {
          if (!n.hasAttribute(a)) continue;
          const memo = kept.get(n) || {};
          const en = englishOf(memo[a], n.getAttribute(a));
          const said = sayAgain(en);
          if (said === null) continue;
          memo[a] = { en, said };
          kept.set(n, memo);
          n.setAttribute(a, said);
        }
      }
    }
  };

  document.addEventListener("DOMContentLoaded", () => W.translatePage());
  window.addEventListener("woodshed:lang", () => {
    W.translatePage();
    for (const again of W.onLang) again();
  });
})();

// The viewer's own choices, for every page of woodshed, kept in this browser: the theme (dark unless
// light is chosen) and the language (the browser's, English or French, until one is chosen).
// Loaded in <head>, before the page is drawn: no flash of the other theme.
(function () {
  "use strict";
  const THEME = "woodshed:theme";
  const LANG = "woodshed:lang";
  const LANGS = ["en", "fr"];
  const root = document.documentElement;

  function stored(key) {
    try {
      return localStorage.getItem(key);
    } catch (err) {
      return null; // storage off (private window): the defaults
    }
  }

  function keep(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (err) {
      /* this visit only */
    }
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme === "light" ? "light" : "dark");
  }
  apply(stored(THEME));

  const browser = (navigator.language || "en").slice(0, 2).toLowerCase();
  const chosen = stored(LANG);
  root.lang = LANGS.includes(chosen) ? chosen : browser === "fr" ? "fr" : "en";

  // The page's own words, translated by core/i18n.js once it is loaded; English until then.
  const say = (text) => (window.Woodshed && window.Woodshed.t ? window.Woodshed.t(text) : text);

  function label(button) {
    const light = root.getAttribute("data-theme") === "light";
    const next = say(light ? "Switch to the dark theme" : "Switch to the light theme");
    button.textContent = light ? "☾︎" : "☀︎";
    button.setAttribute("aria-label", next);
    button.title = next;
  }

  function toggle() {
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    apply(next);
    keep(THEME, next);
    document.querySelectorAll("[data-theme-toggle]").forEach(label);
    window.dispatchEvent(new CustomEvent("woodshed:theme", { detail: next })); // the waveform redraws
  }

  function marks(group) {
    group.querySelectorAll("[data-lang]").forEach((b) => {
      const on = b.getAttribute("data-lang") === root.lang;
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", String(on));
    });
  }

  function setLang(lang) {
    if (!LANGS.includes(lang) || lang === root.lang) return;
    root.lang = lang;
    keep(LANG, lang);
    document.querySelectorAll("[data-lang-toggle]").forEach(marks);
    document.querySelectorAll("[data-theme-toggle]").forEach(label);
    window.dispatchEvent(new CustomEvent("woodshed:lang", { detail: lang })); // the page says it again
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      label(button);
      // A click or a tap leaves no focus behind: the next Space (a pedal) plays the song; the
      // keyboard keeps it, so Space presses the button again.
      button.addEventListener("click", (e) => {
        toggle();
        if (e.detail > 0) button.blur();
      });
    });
    document.querySelectorAll("[data-lang-toggle]").forEach((group) => {
      marks(group);
      group.querySelectorAll("[data-lang]").forEach((b) =>
        b.addEventListener("click", (e) => {
          setLang(b.getAttribute("data-lang"));
          if (e.detail > 0) b.blur();
        }),
      );
    });
  });
})();

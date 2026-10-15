// The viewer's own choices, for every page of woodshed: the theme (dark unless light is chosen),
// kept in this browser. Loaded in <head>, before the page is drawn: no flash of the other theme.
(function () {
  "use strict";
  const KEY = "woodshed:theme";
  const root = document.documentElement;

  function stored() {
    try {
      return localStorage.getItem(KEY);
    } catch (err) {
      return null; // storage off (private window): dark, as by default
    }
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme === "light" ? "light" : "dark");
  }
  apply(stored());

  function label(button) {
    const light = root.getAttribute("data-theme") === "light";
    button.textContent = light ? "☾︎" : "☀︎";
    const next = light ? "Switch to the dark theme" : "Switch to the light theme";
    button.setAttribute("aria-label", next);
    button.title = next;
  }

  function toggle() {
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    apply(next);
    try {
      localStorage.setItem(KEY, next);
    } catch (err) {
      /* this visit only */
    }
    document.querySelectorAll("[data-theme-toggle]").forEach(label);
    window.dispatchEvent(new CustomEvent("woodshed:theme", { detail: next })); // the waveform redraws
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      label(button);
      button.addEventListener("click", toggle);
    });
  });
})();

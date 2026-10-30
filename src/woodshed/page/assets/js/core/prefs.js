// The viewer's own choices, for every page of woodshed, kept in this browser: the theme (dark unless
// light is chosen), the language (the browser's, English or French, until one is chosen) and the skin
// (spec 030: woodshed's own until another is chosen, from skins/skins.js).
// Loaded in <head>, before the page is drawn: no flash of the other theme or skin.
(function () {
  "use strict";
  const THEME = "woodshed:theme";
  const LANG = "woodshed:lang";
  const SKIN = "woodshed:skin";
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

  // The skins this page has (none in a page made before them: the base, silently).
  const skins = () => (window.WoodshedSkins && window.WoodshedSkins.list) || [{ id: "woodshed", name: "woodshed", description: "" }];
  const known = (id) => skins().some((s) => s.id === id);
  // The skin shown: this device's choice, then the base (a library's own default would come between).
  const chosenSkin = () => (known(stored(SKIN)) ? stored(SKIN) : "woodshed");
  function applySkin(id) {
    if (id !== "woodshed" && known(id)) root.setAttribute("data-skin", id);
    else root.removeAttribute("data-skin");
  }
  applySkin(chosenSkin());

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

  // The style menu (spec 030): the skins with a swatch each, beside the theme button on every page.
  const skinOf = (id) => skins().find((s) => s.id === id) || skins()[0];
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    for (const c of children) node.append(c);
    return node;
  }
  // Four squares in a skin's colours (bg, panel, accent, ink), read from the skin through its probe.
  const swatch = (id, cls) => el("span", { class: cls, "data-skin-probe": id, "aria-hidden": "true" }, el("i"), el("i"), el("i"), el("i"));
  let menu = null; // { box, scrim, button, keys, outside } while open
  function styleLabel(button) {
    const current = skinOf(chosenSkin());
    const name = say("Style: {skin}").replace("{skin}", say(current.name));
    button.setAttribute("aria-label", name);
    button.title = name;
    button.replaceChildren(swatch(current.id, "dots"));
  }
  function closeMenu(focusBack) {
    if (!menu) return;
    const { box, scrim, button, keys, outside } = menu;
    menu = null;
    box.remove();
    scrim.remove();
    button.setAttribute("aria-expanded", "false");
    window.removeEventListener("keydown", keys, true);
    window.removeEventListener("keyup", keys, true);
    document.removeEventListener("pointerdown", outside, true);
    if (focusBack) button.focus();
  }
  function setSkin(id) {
    if (!known(id)) return;
    applySkin(id);
    keep(SKIN, id);
    document.querySelectorAll("[data-style-toggle]").forEach(styleLabel);
    window.dispatchEvent(new CustomEvent("woodshed:theme", { detail: root.getAttribute("data-theme") })); // the waveform redraws
    window.dispatchEvent(new CustomEvent("woodshed:skin", { detail: id }));
  }
  function openMenu(button) {
    const current = chosenSkin();
    const items = skins().map((s) =>
      el("button", { type: "button", class: "style-item", role: "menuitemradio", "aria-checked": String(s.id === current), "data-skin-id": s.id },
        swatch(s.id, "swatch"),
        el("span", { class: "style-name" }, el("b", { translate: "no" }, say(s.name)), el("small", {}, say(s.description))),
        el("span", { class: "tick", "aria-hidden": "true" }, s.id === current ? "✓" : "")));
    const close = el("button", { type: "button", class: "btn ghost menu-close", "aria-label": say("Close") }, "✕");
    const box = el("div", { class: "style-menu", role: "menu", "aria-label": say("Style") },
      el("div", { class: "menu-h" }, el("span", { class: "label" }, say("Style")), close),
      ...items,
      el("p", { class: "menu-foot" }, say("Only on this device. Light or dark: the button beside it.")));
    const scrim = el("div", { class: "style-scrim", "aria-hidden": "true" });
    const pickWith = (item, e) => {
      setSkin(item.getAttribute("data-skin-id"));
      closeMenu(e.detail === 0); // a pointer leaves no focus behind (a pedal's Space plays); the keyboard keeps it
      if (e.detail > 0) button.blur();
    };
    items.forEach((item) => item.addEventListener("click", (e) => pickWith(item, e)));
    close.addEventListener("click", () => closeMenu(false));
    scrim.addEventListener("click", () => closeMenu(false));
    // While open, the keys are the menu's: the page's shortcuts (Space plays, S stage, N next song...) wait.
    const keys = (e) => {
      e.stopPropagation();
      if (e.type !== "keydown") return;
      const at = items.indexOf(document.activeElement);
      const go = (k) => {
        e.preventDefault();
        items[(k + items.length) % items.length].focus();
      };
      if (e.key === "ArrowDown") go(at + 1);
      else if (e.key === "ArrowUp") go(at < 0 ? items.length - 1 : at - 1);
      else if (e.key === "Home") go(0);
      else if (e.key === "End") go(items.length - 1);
      else if (e.key === "Escape") {
        e.preventDefault();
        closeMenu(true);
      } else if (e.key === "Tab") closeMenu(false);
    };
    const outside = (e) => {
      if (!box.contains(e.target) && !button.contains(e.target) && e.target !== scrim) closeMenu(false);
    };
    menu = { box, scrim, button, keys, outside };
    button.setAttribute("aria-expanded", "true");
    button.parentNode.append(scrim, box);
    window.addEventListener("keydown", keys, true);
    window.addEventListener("keyup", keys, true);
    document.addEventListener("pointerdown", outside, true);
    const focusOn = items.find((i) => i.getAttribute("aria-checked") === "true") || items[0];
    focusOn.focus({ preventScroll: true });
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
    document.querySelectorAll("[data-style-toggle]").forEach(styleLabel);
    if (menu) closeMenu(false); // said again in the other language when opened again
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
    document.querySelectorAll("[data-style-toggle]").forEach((button) => {
      styleLabel(button);
      button.addEventListener("click", (e) => {
        if (menu) closeMenu(e.detail === 0);
        else openMenu(button);
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

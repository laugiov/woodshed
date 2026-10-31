// The places a skin may draw (spec 030): <html> says when the song plays and when the stage is up, and every
// decor slot carries the names a skin may print. One subscriber writes them all: no other view knows skins exist.
(function () {
  "use strict";
  const W = window.Woodshed;

  W.views = W.views || {};

  W.views.decor = function decor(app) {
    const { song, store } = app;
    const root = document.documentElement;
    const name = (el, key, value) => (value ? el.setAttribute("data-" + key, value) : el.removeAttribute("data-" + key));
    function draw(s) {
      root.toggleAttribute("data-playing", !!s.playing); // the count-in included: the reels turn from the click
      root.toggleAttribute("data-stage", !!s.stage || !!s.rehearsal); // the rehearsal sheet is plain too
      for (const el of document.querySelectorAll(".decor")) {
        name(el, "song-title", song.song.title);
        name(el, "set-title", s.setName); // read once when the page opens, from the library (none from a folder)
      }
    }
    draw(store.get());
    store.on((s, changed) => {
      if (changed.has("playing") || changed.has("stage") || changed.has("rehearsal") || changed.has("setName")) draw(s);
    });
    return {};
  };
})();

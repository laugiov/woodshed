// The skins woodshed ships (spec 030, docs/skins.md), in the style menu's order. A skin is a folder beside this
// file (skin.css and its images), one line here, and one @import in skins.css.
(function () {
  "use strict";
  window.WoodshedSkins = {
    list: [
      { id: "woodshed", name: "woodshed", description: "The practice room" },
      { id: "spotlight", name: "Spotlight", description: "Most contrast: sunlight or a dark stage" },
    ],
    // Where a skin may draw: every <span class="decor" data-slot="…"> of the pages is one of these.
    slots: ["page", "library-head", "set-head", "welcome", "song-head", "player"],
  };
})();

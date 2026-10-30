// The skins woodshed ships (spec 030, docs/skins.md), in the style menu's order. A skin is a folder beside this
// file (skin.css and its images), one line here, and one @import in skins.css.
(function () {
  "use strict";
  window.WoodshedSkins = {
    list: [
      { id: "woodshed", name: "woodshed", description: "The practice room" },
      { id: "spotlight", name: "Spotlight", description: "Most contrast: sunlight or a dark stage" },
      { id: "disco70", name: "Disco 70", description: "Mirror balls, 45s, sunsets" },
      { id: "mixtape80", name: "Mixtape 80", description: "Tapes, vinyl, neon" },
      { id: "grunge90", name: "Grunge 90", description: "CDs, flannel, photocopies" },
      { id: "y2k", name: "Y2K", description: "MP3 players, chrome, aqua" },
    ],
    // Where a skin may draw: every <span class="decor" data-slot="…"> of the pages is one of these.
    slots: ["page", "library-head", "set-head", "welcome", "song-head", "player"],
  };
})();

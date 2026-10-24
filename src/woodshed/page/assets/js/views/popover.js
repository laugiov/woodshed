// The editors' shell (views/editor.js for a bar, views/lines.js for a sung line): a dialog by what it edits on a
// computer, a sheet over the keyboard on a phone, the keyboard kept inside it.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $ } = W;
  const PHONE = window.matchMedia("(max-width: 600px)");

  // On a phone the sheet stays above the keyboard, no taller than the screen left to it.
  function keepAboveKeyboard(box) {
    const vv = window.visualViewport;
    box.style.bottom = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) + "px" : "0px";
    box.style.maxHeight = (vv ? vv.height : window.innerHeight) - 16 + "px";
  }

  // On a phone, what is edited stays in sight above the sheet: its bottom just over the sheet, its top on the
  // screen when it is taller than the room left.
  function keepInSight(box, el) {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const top = box.getBoundingClientRect().top;
    if (r.bottom > top - 8 || r.top < 0) window.scrollBy({ top: Math.min(r.bottom - (top - 16), r.top - 8) });
  }

  // `still`: placed again where the anchor is now (scrolling), without scrolling the page itself.
  function place(box, anchor, still) {
    document.querySelectorAll(".ed-tail").forEach((t) => t.remove());
    if (PHONE.matches) {
      $("edScrim").hidden = false;
      box.style.left = "";
      box.style.top = "";
      keepAboveKeyboard(box);
      keepInSight(box, anchor);
      return;
    }
    $("edScrim").hidden = true;
    box.style.bottom = "";
    // The anchor near the top of the view first, so the editor opens under it with room to spare.
    const seen = window.innerHeight - ($("dock") ? $("dock").offsetHeight : 0);
    let r = anchor.getBoundingClientRect();
    if (!still && r.bottom + 12 + box.offsetHeight > seen - 8) {
      window.scrollBy({ top: r.top - 140 });
      r = anchor.getBoundingClientRect();
    }
    const w = box.offsetWidth;
    const left = Math.max(12, Math.min(window.innerWidth - w - 12, r.left + r.width / 2 - w / 2));
    const below = seen - 8 - (r.bottom + 12);
    const up = below < box.offsetHeight && r.top - 20 > below;
    box.style.left = left + "px";
    box.style.top = (up ? Math.max(8, r.top - 12 - box.offsetHeight) : r.bottom + 12) + "px";
    const tail = h("div", { class: "ed-tail" + (up ? " up" : ""), "aria-hidden": "true" });
    tail.style.left = r.left + r.width / 2 - 7 + "px";
    tail.style.top = (up ? r.top - 19 : r.bottom + 5) + "px";
    document.body.append(tail);
  }

  // Tab and Shift+Tab cycle inside the dialog.
  function trap(box, e) {
    const list = [...box.querySelectorAll("button:not([disabled]), input, textarea")].filter((el) => el.getClientRects().length > 0);
    const first = list[0];
    const last = list[list.length - 1];
    if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    }
  }

  W.popover = { PHONE, place, keepAboveKeyboard, keepInSight, trap };
})();

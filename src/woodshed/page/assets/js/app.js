(function () {
  "use strict";
  var SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  var FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
  var FLAT_KEYS = { 5: 1, 10: 1, 3: 1, 8: 1, 1: 1, 6: 1 };
  var BEATS = 4;

  function C(pc, q, beats, doubt) { return { pc: pc, q: q, beats: beats, doubt: doubt || null, fixed: false }; }
  var SONG = /*SONG_DATA*/null;
  var Z16 = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
  // Without a drum track, the stand-in band plays a plain backbeat so practice still works.
  var GROOVE = SONG.groove || { kick: [1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0], snare: [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0], hat: [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0], fallback: true };
  var BASSLINE = SONG.bass || [], COMP = SONG.comp || [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], VOICINGS = SONG.voicings || [], VOCAL = SONG.vocal || null;
  var COUNTS = "1 e & a 2 e & a 3 e & a 4 e & a".split(" ");
  var BPM = Math.round(SONG.bpm), KEY_PC = SONG.key.pc, KEY_MINOR = SONG.key.mode === "min", DURATION = SONG.duration, ENERGY = SONG.energy, GROUPS = SONG.groups;
  var song = SONG.bars.map(function (b) {
    return { start: b.start, end: b.end, group: b.group, occ: b.occ, col: b.col,
             chords: b.chords.map(function (c) { return C(c.pc, c.q, c.beats, c.doubt || null); }) };
  });
  var TOTAL_BARS = song.length, TOTAL_BEATS = TOTAL_BARS * BEATS;

  var state = { transpose: 0, capo: 0, inst: "guitar", pos: "open", playing: false, beat: 0, loop: null, loopOn: false,
                countIn: false, speed: 1, bpm: BPM, trainer: false, view: "concert", step: 1, voiceType: null, stage: false, mix: { drums: 1, bass: 1, chords: 1, click: 1 }, mute: { click: true }, solo: null, chordSound: "guitar" };

  var $ = function (id) { return document.getElementById(id); };
  function keyPc() { return (KEY_PC + state.transpose + 120) % 12; }
  function spell(pc) { var k = KEY_MINOR ? (keyPc() + 3) % 12 : keyPc(); return (FLAT_KEYS[k] ? FLAT : SHARP)[(pc + 120) % 12]; }
  function nameOf(ch, shift) { return spell(ch.pc + state.transpose - (shift || 0)) + ch.q; }
  function pretty(name) {
    var m = /^([A-G])([b#]?)(.*)$/.exec(name);
    if (!m) return name;
    var acc = m[2] === "b" ? "♭" : m[2] === "#" ? "♯" : "";
    return m[1] + (acc ? '<span class="acc">' + acc + "</span>" : "") + m[3];
  }
  function roman(ch) {
    var d = ((ch.pc - KEY_PC) % 12 + 12) % 12;
    var r = { 0: "I", 1: "♭II", 2: "II", 3: "♭III", 4: "III", 5: "IV", 6: "♯IV", 7: "V", 8: "♭VI", 9: "VI", 10: "♭VII", 11: "VII" }[d];
    return ch.q === "m" ? r.toLowerCase() : r;
  }
  function chordAtBeat(b) {
    var bar = song[Math.max(0, Math.min(TOTAL_BARS - 1, Math.floor(b / BEATS)))], pos = b % BEATS, acc = 0;
    for (var i = 0; i < bar.chords.length; i++) { acc += bar.chords[i].beats; if (pos < acc) return bar.chords[i]; }
    return bar.chords[bar.chords.length - 1];
  }
  function same(a, b) { return a && b && a.pc === b.pc && a.q === b.q; }
  function upcoming(b, n) {
    var out = [], cur = chordAtBeat(b);
    for (var k = b + 1; k < TOTAL_BEATS && out.length < n; k++) { var c = chordAtBeat(k); if (!same(c, cur)) { out.push(c); cur = c; } }
    return out;
  }
  function fmt(t) { var m = Math.floor(t / 60), s = t - m * 60; return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1); }
  function barTime(i) { return i >= TOTAL_BARS ? song[TOTAL_BARS - 1].end : song[Math.max(0, i)].start; }
  function beatTime(b) { var u = Math.min(TOTAL_BARS - 1, Math.floor(b / BEATS)); return song[u].start + (b % BEATS) * (song[u].end - song[u].start) / BEATS; }
  function keyName() { return pretty(spell(KEY_MINOR ? keyPc() + 9 : keyPc())) + (KEY_MINOR ? " minor" : " major"); }
  function occRange(u) { var o = GROUPS[song[u].group].occurrences[song[u].occ]; return [o[0], o[o.length - 1]]; }
  function barAtTime(t) { var u = 0; for (var i = 0; i < TOTAL_BARS; i++) if (song[i].start <= t) u = i; return u; }
  function uniqueChords() {
    var seen = {}, out = [];
    song.forEach(function (bar) { bar.chords.forEach(function (c) { if (c.doubt && !c.fixed && c.beats <= 1) return; var k = c.pc + c.q; if (!seen[k]) { seen[k] = 1; out.push(c); } }); });
    return out;
  }

  // Guitar voicings. Open shapes where they exist, E- or A-shape barres otherwise, and small funk triads on strings 3-2-1.
  var OPEN = { "0": [-1, 3, 2, 0, 1, 0], "9": [-1, 0, 2, 2, 2, 0], "7": [3, 2, 0, 0, 0, 3], "4": [0, 2, 2, 1, 0, 0], "2": [-1, -1, 0, 2, 3, 2],
               "9m": [-1, 0, 2, 2, 1, 0], "4m": [0, 2, 2, 0, 0, 0], "2m": [-1, -1, 0, 2, 3, 1] };
  function barreShape(pc, q) {
    pc = (pc + 120) % 12;
    var fe = (pc - 4 + 12) % 12 || 12, fa = (pc - 9 + 12) % 12 || 12;
    if (fe <= fa) return { frets: q === "m" ? [fe, fe + 2, fe + 2, fe, fe, fe] : [fe, fe + 2, fe + 2, fe + 1, fe, fe], barre: fe, from: 0 };
    return { frets: q === "m" ? [-1, fa, fa + 2, fa + 2, fa + 1, fa] : [-1, fa, fa + 2, fa + 2, fa + 2, fa], barre: fa, from: 1 };
  }
  function openShape(pc, q) { var k = ((pc + 120) % 12) + q; return OPEN[k] ? { frets: OPEN[k], barre: 0, open: true } : barreShape(pc, q); }
  function triadCandidates(pc, q) {
    var pcs = [0, q === "m" ? 3 : 4, 7].map(function (i) { return (pc + i + 120) % 12; }), open = [55, 59, 64], out = [];
    for (var a = 1; a <= 13; a++) for (var b = 1; b <= 13; b++) for (var c = 1; c <= 13; c++) {
      var n = [(open[0] + a) % 12, (open[1] + b) % 12, (open[2] + c) % 12];
      if (pcs.every(function (x) { return n.indexOf(x) >= 0; }) && Math.max(a, b, c) - Math.min(a, b, c) <= 3) out.push([a, b, c]);
    }
    return out;
  }
  function funkVoicings(chords) {
    // Pick one small triad per chord so the hand barely moves: start near fret 6, then stay close to the previous shape.
    var prev = 6, map = {};
    chords.forEach(function (ch) {
      var pc = ch.pc + state.transpose, best = null, bestCost = Infinity;
      triadCandidates(pc, ch.q).forEach(function (t) { var avg = (t[0] + t[1] + t[2]) / 3, cost = Math.abs(avg - prev) + 0.3 * Math.abs(avg - 6); if (cost < bestCost) { bestCost = cost; best = t; } });
      map[ch.pc + ch.q] = { frets: [-1, -1, -1, best[0], best[1], best[2]], barre: 0 };
      prev = (best[0] + best[1] + best[2]) / 3;
    });
    return map;
  }
  // F and Bm have well-known small shapes, so they count as easy barres.
  function difficulty(pc, q) { var k = ((pc + 120) % 12) + q; return OPEN[k] ? 1 : (k === "5" || k === "11m") ? 2 : 3; }
  function suggestCapo() {
    // A capo is only worth suggesting when it makes the song clearly easier than playing without one.
    function cost(c) { var t = 0; song.forEach(function (bar) { bar.chords.forEach(function (ch) { t += difficulty(ch.pc + state.transpose - c, ch.q) * ch.beats; }); }); return t; }
    var base = cost(0), best = 0, bestCost = base;
    for (var c = 1; c <= 7; c++) { var v = cost(c); if (v < bestCost) { bestCost = v; best = c; } }
    return bestCost <= 0.75 * base ? best : 0;
  }
  function svgGuitar(sh) {
    var frets = sh.frets, played = frets.filter(function (f) { return f > 0; });
    var max = played.length ? Math.max.apply(null, played) : 1, min = played.length ? Math.min.apply(null, played) : 1;
    var base = max <= 4 ? 1 : min, W = 96, H = 112, x0 = 16, y0 = 22, sw = 13, fh = 17, rows = 5;
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Chord diagram">';
    for (var i = 0; i < 6; i++) s += '<line x1="' + (x0 + i * sw) + '" y1="' + y0 + '" x2="' + (x0 + i * sw) + '" y2="' + (y0 + rows * fh) + '" stroke="var(--muted)" stroke-width="1"/>';
    for (var j = 0; j <= rows; j++) s += '<line x1="' + x0 + '" y1="' + (y0 + j * fh) + '" x2="' + (x0 + 5 * sw) + '" y2="' + (y0 + j * fh) + '" stroke="var(--muted)" stroke-width="' + (j === 0 && base === 1 ? 4 : 1) + '"/>';
    if (base > 1) s += '<text x="' + (x0 + 5 * sw + 5) + '" y="' + (y0 + fh * 0.7) + '" font-size="10" fill="var(--muted)" font-family="var(--font-body)">' + base + "fr</text>";
    if (sh.barre) {
      var by = y0 + (sh.barre - base + 0.5) * fh, bx1 = x0 + (sh.from || 0) * sw, bx2 = x0 + 5 * sw;
      s += '<rect x="' + (bx1 - 5) + '" y="' + (by - 5) + '" width="' + (bx2 - bx1 + 10) + '" height="10" rx="5" fill="var(--ink)"/>';
    }
    frets.forEach(function (f, i) {
      var x = x0 + i * sw;
      if (f < 0) s += '<text x="' + x + '" y="' + (y0 - 7) + '" text-anchor="middle" font-size="10" fill="var(--muted)" font-family="var(--font-body)">×</text>';
      else if (f === 0) s += '<circle cx="' + x + '" cy="' + (y0 - 10) + '" r="3.5" fill="none" stroke="var(--muted)" stroke-width="1.2"/>';
      else if (!(sh.barre && f === sh.barre)) s += '<circle cx="' + x + '" cy="' + (y0 + (f - base + 0.5) * fh) + '" r="5.5" fill="var(--accent)"/>';
    });
    return s + "</svg>";
  }
  function svgPiano(cur, nxt) {
    function notes(ch) { if (!ch) return []; var r = (ch.pc + state.transpose + 120) % 12, n0 = r < 6 ? 60 + r : 48 + r; return [n0, n0 + (ch.q === "m" ? 3 : 4), n0 + 7]; }
    var on = {}, ghost = {}; notes(cur).forEach(function (n) { on[n] = 1; }); notes(nxt).forEach(function (n) { ghost[n] = 1; });
    var whites = [0, 2, 4, 5, 7, 9, 11], W = 14 * 22 + 2, s = '<svg viewBox="0 0 ' + W + ' 116" width="' + W + '" role="img" aria-label="Keyboard">', wi = 0, blacks = [];
    for (var m = 48; m < 72; m++) {
      if (whites.indexOf(m % 12) >= 0) {
        s += '<rect x="' + (1 + wi * 22) + '" y="1" width="21" height="112" rx="3" fill="' + (on[m] ? "var(--accent)" : "var(--sheet)") + '" stroke="' + (ghost[m] && !on[m] ? "var(--warn)" : "var(--muted)") + '" stroke-width="' + (ghost[m] && !on[m] ? 2.5 : 1) + '"/>';
        wi++;
      } else blacks.push([m, wi]);
    }
    blacks.forEach(function (b) { s += '<rect x="' + (1 + b[1] * 22 - 7) + '" y="1" width="14" height="70" rx="2" fill="' + (on[b[0]] ? "var(--accent)" : "var(--ink)") + '" stroke="' + (ghost[b[0]] && !on[b[0]] ? "var(--warn)" : "none") + '" stroke-width="2.5"/>'; });
    return s + "</svg>";
  }
  // Bass line: root on the beat, the half step below on the off-beats, octave pop. This is the riff the analysis found.
  var BASS_PAT = { 0: 0, 1: 0, 3: -1, 4: 0, 6: 12, 7: -1 };
  function bassMidi(ch) { var pc = (ch.pc + state.transpose + 120) % 12; return 28 + (pc - 4 + 12) % 12; }
  function bassTab(u) {
    // Real bass line from the bass track. One column per sixteenth, counts on top; faint notes were heard in two passes out of three.
    var strings = [["G", 43], ["D", 38], ["A", 33], ["E", 28]], rows = [[], [], [], []], cnt = [], prev = 1;
    for (var pos = 0; pos < 16; pos++) {
      cnt.push((COUNTS[pos] + "  ").slice(0, 3));
      var e = (BASSLINE[u] || Z16)[pos] || null, cell = ["---", "---", "---", "---"];
      if (e) {
        var n = e[0] + state.transpose, best = -1, bf = 99;
        strings.forEach(function (st, k) { var f = n - st[1]; if (f >= 0 && f <= 12) { var cost = Math.abs(f - prev) + (f > 7 ? 3 : 0); if (best < 0 || cost < bf) { bf = cost; best = k; } } });
        if (best >= 0) { var fret = n - strings[best][1]; prev = fret; var txt = ("-" + fret + "--").slice(0, 3); cell[best] = e[1] < 0.67 ? '<span class="lo">' + txt + "</span>" : txt; }
      }
      cell.forEach(function (c, k) { rows[k].push(c); });
    }
    return { counts: "  " + cnt.join(""), lines: strings.map(function (st, k) { return st[0] + "|" + rows[k].join("") + "|"; }) };
  }
  function countDoubts() { var n = 0; song.forEach(function (b) { if (b.chords.some(function (c) { return c.doubt && !c.fixed; })) n++; }); return n; }
  function renderChips() {
    var spots = {}, first = -1;
    song.forEach(function (b, i) { b.chords.forEach(function (c) { if (c.doubt && !c.fixed) { if (first < 0) first = i; spots[c.doubt.id] = 1; } }); });
    var n = Object.keys(spots).length;
    $("facts").innerHTML = "<span><b>" + BPM + "</b> BPM</span><span><b>4/4</b></span><span>Key <b>" + keyName() + "</b></span><span>" + fmt(DURATION).replace(/\.\d$/, "") + "</span>" +
      (n ? '<button type="button" class="warnfact" data-goto="' + first + '">' + n + " spot" + (n > 1 ? "s" : "") + " to check by ear</button>" : '<span class="okfact">All chords checked</span>');
  }

  function showShapes() { return state.inst === "guitar" && state.pos === "open" && state.capo > 0 && state.view === "shapes"; }
  function chordHtml(ch, small, ref) {
    var shapes = showShapes(), main = '<span class="cn">' + pretty(nameOf(ch, shapes ? state.capo : 0)) + "</span>";
    var sub = shapes ? '<span class="shape" style="color: var(--muted)">' + pretty(nameOf(ch)) + "</span>" : "";
    var inner = ch.doubt && !ch.fixed ? '<button type="button" class="doubt" data-ref="' + ref + '" title="Check by ear">' + main + "<sup>?</sup></button>" : main + (ch.fixed ? '<span class="fixed-dot" title="Your correction"></span>' : "");
    return '<span class="ch' + (small ? " small" : "") + '">' + inner + sub + "</span>";
  }
  function renderViewCtl() {
    var el = $("viewCtl");
    if (state.inst === "guitar" && state.pos === "open" && state.capo > 0) {
      el.innerHTML = '<div class="seg-ctl" role="group" aria-label="Chart shows"><button type="button" data-view="concert" class="' + (state.view === "concert" ? "on" : "") + '">Real chords</button><button type="button" data-view="shapes" class="' + (state.view === "shapes" ? "on" : "") + '">Shapes, capo ' + state.capo + "</button></div>";
    } else el.innerHTML = '<span class="hint">Real chords, concert pitch</span>';
  }
  function barInner(chords, ref) {
    if (chords.length === 1) return chordHtml(chords[0], false, ref + "_0");
    var h = "";
    var even = chords.length === 2 && chords[0].beats === 2;
    chords.forEach(function (ch, k) { h += chordHtml(ch, !even, ref + "_" + k); if (!even) for (var s = 1; s < ch.beats; s++) h += '<span class="slash">/</span>'; });
    return h;
  }
  function curBar() { return Math.floor(state.beat / BEATS); }
  function curOcc(g) { var u = curBar(); return song[u].group === g ? song[u].occ : 0; }
  function displayBar(col, g) { var o = GROUPS[g].occurrences[curOcc(g)]; return o[Math.min(col, o.length - 1)]; }
  function renderSheet() {
    var h = SONG.intro ? '<div class="intro"><b>Intro</b><span>' + SONG.intro + "</span></div>" : "";
    GROUPS.forEach(function (gr, g) {
      var n = gr.occurrences.length, len = gr.occurrences[0].length;
      h += '<div class="line"><div class="line-label"><span class="sec">' + gr.label + '</span><span class="t">' + fmt(song[gr.occurrences[0][0]].start) + "</span></div>" +
           '<div class="staff four">' + (n > 1 ? '<div class="rep">𝄆</div>' : '<div class="plain-bar"></div>');
      for (var col = 0; col < 4; col++) {
        if (col >= len) { h += '<div class="bar empty" aria-hidden="true"></div>'; continue; }
        var u = displayBar(col, g), bar = song[u];
        h += '<div class="bar" data-col="' + col + '" data-group="' + g + '" role="button" tabindex="0" aria-label="Bar ' + (u + 1) + '">' + barInner(bar.chords, u) +
             '<span class="num">' + (u + 1) + '</span><span class="rn">' + bar.chords.map(roman).join(" ") + "</span></div>";
      }
      h += (n > 1 ? '<div class="rep r-end">𝄇</div><span class="times">×' + n + "</span>" : '<div class="plain-end"></div>') + "</div></div>";
    });
    if (SONG.outro) h += '<div class="intro"><span>' + SONG.outro + "</span></div>";
    $("sheet").innerHTML = h;
    renderViewCtl();
    paintBars();
  }
  function barEl(u) {
    var b = song[u]; if (displayBar(b.col, b.group) !== u) return null;
    return document.querySelector('.bar[data-group="' + b.group + '"][data-col="' + b.col + '"]');
  }
  function paintBars() {
    document.querySelectorAll(".bar").forEach(function (e) { e.classList.remove("cur", "inloop"); var c = e.querySelector(".cursor"); if (c) c.remove(); });
    var u = curBar(), el = barEl(u);
    if (el) { el.classList.add("cur"); var cu = document.createElement("span"); cu.className = "cursor"; cu.style.left = (state.beat % BEATS) * 25 + "%"; el.appendChild(cu); }
    if (state.loopOn && state.loop) for (var i = state.loop[0]; i <= state.loop[1]; i++) { var le = barEl(i); if (le) le.classList.add("inloop"); }
  }

  function renderHarmony() {
    $("keyTitle").innerHTML = keyName();
    $("prog").innerHTML = SONG.harmony.prog.map(function (c) { return "<span>" + pretty(nameOf(c)) + "<small>" + roman(c) + "</small></span>"; }).join("");
    $("progText").innerHTML = SONG.harmony.text;
    var items = [], seen = {};
    song.forEach(function (b, i) { b.chords.forEach(function (c) {
      if (c.doubt && !c.fixed && !seen[c.doubt.id]) { seen[c.doubt.id] = 1; var where = "Bar " + (i + 1);
        items.push('<li><button type="button" data-goto="' + i + '">' + where + "</button><span>" + pretty(nameOf(c)) + "? " + c.doubt.why + "</span></li>"); }
    }); });
    $("checks").innerHTML = items.length ? items.join("") : '<li class="ok"><span>All checked. Your corrections are saved with the song and used by every export.</span></li>';
  }

  function renderDesk() {
    var cur = chordAtBeat(state.beat), up = upcoming(state.beat, 1)[0], h = "";
    $("capoWrap").hidden = $("capoStepper").hidden = state.inst !== "guitar";
    $("deskTitle").textContent = { guitar: "Your guitar", bass: "Your bass", piano: "Your keys", drums: "Your drums", voice: "Your voice" }[state.inst];
    var s2 = { guitar: ["Learn the shapes", "Your part alone. Click a shape to hear it."], bass: ["Learn the line", "The bass alone, with its tab."], piano: ["Learn the voicings", "The chords alone, as played on the record."],
               drums: ["Learn the groove", "The drums alone, with the notation."], voice: ["Find your key", "Set your voice type, then sing over the chords alone."] }[state.inst];
    $("step2t").textContent = s2[0]; $("step2d").textContent = s2[1];
    if (state.inst === "guitar") {
      h += '<div class="seg-ctl" role="group" aria-label="Voicing" style="margin-bottom: 12px">' +
        [["open", "Open, capo " + state.capo], ["barre", "Barre chords"], ["funk", "Funk triads"]].map(function (o) { return '<button type="button" data-pos="' + o[0] + '" class="' + (state.pos === o[0] ? "on" : "") + '">' + o[1] + "</button>"; }).join("") + "</div>";
      var chords = uniqueChords(), funk = state.pos === "funk" ? funkVoicings(chords) : null;
      h += '<div class="shapes">';
      chords.forEach(function (ch) {
        var sh, label, sub;
        if (state.pos === "open") { sh = openShape(ch.pc + state.transpose - state.capo, ch.q); label = nameOf(ch, state.capo); sub = state.capo ? "sounds " + pretty(nameOf(ch)) : ""; }
        else if (state.pos === "barre") { sh = barreShape(ch.pc + state.transpose, ch.q); label = nameOf(ch); sub = "no capo"; }
        else { sh = funk[ch.pc + ch.q]; label = nameOf(ch); sub = "strings 3-2-1"; }
        h += '<button type="button" class="shape-card' + (same(ch, cur) ? " cur" : "") + '" data-strum="' + ch.pc + "_" + ch.q + '" aria-label="Hear ' + nameOf(ch) + '"><span class="nm" style="display: block">' + pretty(label) + '</span><span class="sub" style="display: block">' + sub + "</span>" + svgGuitar(sh) + '<span class="play-hint" style="display: block">▶ hear</span></button>';
      });
      h += "</div>";
      var tip = state.pos === "open" ? (state.capo === suggestCapo() ? "Capo " + state.capo + " gives open shapes for the whole song." : "Tip: capo " + suggestCapo() + " gives the easiest shapes.")
        : state.pos === "funk" ? "Three-note shapes chosen so your hand barely moves from one chord to the next. This is how funk rhythm guitar is usually played." : "Full barre chords, no capo, concert pitch.";
      h += '<p class="desk-note">' + tip + " Click a shape to hear it.</p>";
      h += compBlock();
    } else if (state.inst === "bass") {
      var u = curBar(), t1 = bassTab(u), notes = [];
      (BASSLINE[u] || []).forEach(function (e) { if (e) { var nm = pretty(spell(e[0] + state.transpose)); if (notes.indexOf(nm) < 0) notes.push(nm); } });
      h += '<div class="label" style="margin-bottom: 6px">Bar ' + (u + 1) + ', the line as played <span class="exp">experimental</span></div>';
      h += '<div class="tab"><span class="cnt">' + t1.counts + "</span>\n" + t1.lines.join("\n") + "</div>";
      h += '<div class="chips-row"><span class="hint">Notes in this bar:</span>' + notes.map(function (n) { return '<span class="pc-chip">' + n + "</span>"; }).join("") + "</div>";
      h += '<div class="hear-row"><button type="button" class="btn" data-riff="' + u + '">▶ Hear bar ' + (u + 1) + "</button>" + (u + 1 < TOTAL_BARS ? '<button type="button" class="btn" data-riff="' + (u + 1) + '">▶ Hear bar ' + (u + 2) + "</button>" : "") + "</div>";
      h += '<p class="desk-note">' + (SONG.bass ? "Transcribed from the isolated bass track. Faint notes are less certain." : "No bass track was separated for this song.") + " Step 4 mutes the bass so you can play it.</p>";
    } else if (state.inst === "voice" && !VOCAL) {
      h += '<p class="desk-note">No singing was detected on the isolated vocal track, so there is no range to match.</p>';
    } else if (state.inst === "voice") {
      var vt = state.voiceType ? VOICES.filter(function (v) { return v[0] === state.voiceType; })[0] : null;
      h += '<div class="label" style="margin-bottom: 6px">Your range against the song</div><div class="range">' + rangeSvg(vt) + "</div>";
      h += '<div class="voice-types" role="group" aria-label="Your voice type">' + VOICES.map(function (v) { return '<button type="button" class="btn' + (state.voiceType === v[0] ? " on" : "") + '" data-voice="' + v[0] + '">' + v[0] + "</button>"; }).join("") + "</div>";
      if (vt) {
        var bt = bestTranspose(vt[1], vt[2]);
        h += '<p class="fit">' + (bt === state.transpose ? "<b>This key fits a " + vt[0].toLowerCase() + " voice.</b>" : "Best key for a " + vt[0].toLowerCase() + ' voice: <b>' + pretty(spell(KEY_PC + bt)) + " major</b> (" + (bt > 0 ? "+" : "") + bt + ' semitones). <button type="button" class="btn" data-fit="' + bt + '">Transpose the song</button>') + "</p>";
      } else h += '<p class="fit">Pick your voice type to see the best key.</p>';
      h += '<p class="src-note">Range measured on the isolated vocal track: ' + noteName(VOCAL.low) + " to " + noteName(VOCAL.high) + " for 95% of the sung notes. Transposing moves the chart, the shapes and the band together.</p>";
    } else if (state.inst === "drums") {
      var counts = "1 e & a 2 e & a 3 e & a 4 e & a".split(" ");
      h += '<div class="label" style="margin-bottom: 6px">Main groove <span class="exp">experimental</span></div>';
      h += '<div class="staffbox" id="drumStaff" aria-label="Drum notation of the main groove"></div>';
      h += '<div class="groove" style="margin-top: 10px" id="grooveGrid"><span></span>' + counts.map(function (c, i) { return '<span class="ct' + (i % 4 === 0 ? " downbeat" : "") + '">' + c + "</span>"; }).join("");
      [["hat", "Hi-hat"], ["snare", "Snare"], ["kick", "Kick"]].forEach(function (r) {
        h += '<span class="rl">' + r[1] + "</span>" + GROOVE[r[0]].map(function (v, i) {
          var size = v < 0.1 ? 0 : 6 + Math.round(v * 12);
          return '<span class="cell' + (i % 4 === 0 ? " q0" : "") + '" data-six="' + i + '" title="' + r[1] + ", " + counts[i] + ": hit in " + Math.round(v * 100) + '% of bars">' + (size ? '<span class="dot" style="width:' + size + "px;height:" + size + "px;opacity:" + (0.25 + v * 0.75).toFixed(2) + '"></span>' : "") + "</span>";
        }).join("");
      });
      h += "</div>";
      h += '<div class="legend-row"><span>Bigger dot: hit in more bars</span><span>Notation: hits played in more than half the bars</span></div>';
      h += '<div class="hear-row"><button type="button" class="btn" data-groove="1">▶ Hear the groove</button><button type="button" class="btn" data-groove="2">▶ Groove with the band</button></div>';
      h += '<p class="desk-note">' + (GROOVE.fallback ? "No drum track was separated: this is a plain backbeat, not the record." : "Read from the drum track, isolated on this computer, over " + GROOVE.bars + " bars. Kick on " + hitsText(GROOVE.kick) + ", snare on " + hitsText(GROOVE.snare) + ". Bars matching the main groove: kick " + Math.round(GROOVE.agree.kick * 100) + "%, snare " + Math.round(GROOVE.agree.snare * 100) + "%, hi-hat " + Math.round(GROOVE.agree.hat * 100) + "%. Fills are not detected yet.") + "</p>";
    } else {
      h += '<div class="piano-wrap">' + svgPiano(cur, up) + '<div class="hint">Now: <b>' + pretty(nameOf(cur)) + "</b> in root position. Orange outline: the next chord, " + (up ? pretty(nameOf(up)) : "none") + ".</div>" +
        '<div class="hear-row"><button type="button" class="btn" data-keys="' + cur.pc + "_" + cur.q + '">▶ Hear ' + pretty(nameOf(cur)) + "</button>" + (up ? '<button type="button" class="btn" data-keys="' + up.pc + "_" + up.q + '">▶ Hear ' + pretty(nameOf(up)) + "</button>" : "") +
        '<button type="button" class="btn" data-arp="' + cur.pc + "_" + cur.q + '">Note by note</button></div></div>';
      var vc = VOICINGS[curBar()] || [], rootName = pretty(spell(chordAtBeat(state.beat).pc + state.transpose));
      h += '<div class="label subhead">On the record, this bar</div><div class="chips-row">' + vc.map(function (pc) { return '<span class="pc-chip">' + pretty(spell(pc + state.transpose)) + "</span>"; }).join("") +
        '<span class="hint">over</span><span class="pc-chip bassnote">' + rootName + '</span><button type="button" class="btn" data-recvoice="1" style="margin-left: 4px">▶ Hear it</button></div>' +
        '<p class="src-note">Upper notes heard on the isolated keys and guitar track. The keyboard often leaves the root to the bass: richer than the plain triad above.</p>';
      h += compBlock();
    }
    $("desk").innerHTML = h;
    if (state.inst === "drums") renderDrumStaff();
    $("trVal").innerHTML = pretty(spell(keyPc())) + (state.transpose ? " (" + (state.transpose > 0 ? "+" : "") + state.transpose + ")" : "");
    $("capoVal").textContent = String(state.capo);
  }

  function drumVoice(VF, slots, dir) {
    // 16 slots of keys (empty = silence), grouped per beat into quarter, eighth or sixteenth figures.
    var notes = [];
    function note(keys, d) { return new VF.StaveNote({ keys: keys.length ? keys : [dir > 0 ? "b/4" : "f/4"], duration: keys.length ? d : d + "r", stem_direction: dir }); }
    for (var b = 0; b < 4; b++) {
      var sl = slots.slice(b * 4, b * 4 + 4);
      if (!sl[1].length && !sl[2].length && !sl[3].length) { notes.push(note(sl[0], "q")); continue; }
      for (var hh = 0; hh < 2; hh++) { var a = sl[hh * 2], c = sl[hh * 2 + 1]; if (!c.length) notes.push(note(a, "8")); else { notes.push(note(a, "16")); notes.push(note(c, "16")); } }
    }
    return notes;
  }
  function renderDrumStaff() {
    var box = $("drumStaff"); if (!box) return;
    if (!window.Vex || !window.Vex.Flow) {
      box.innerHTML = '<p class="hint" style="margin: 6px">Drawing the notation…</p>';
      loadScript("assets/vendor/vexflow-4.2.2-bravura.js").then(renderDrumStaff, function () {
        if ($("drumStaff")) $("drumStaff").innerHTML = '<p class="hint" style="margin: 6px">The notation library could not load. The grid below shows the same groove.</p>';
      });
      return;
    }
    try {
      var VF = window.Vex.Flow, w = Math.max(300, Math.min(520, box.clientWidth - 12)), hands = [], feet = [];
      for (var i = 0; i < 16; i++) {
        var k = []; if (GROOVE.hat[i] > 0.5) k.push("g/5/x2"); if (GROOVE.snare[i] > 0.5) k.push("c/5"); hands.push(k);
        feet.push(GROOVE.kick[i] > 0.5 ? ["f/4"] : []);
      }
      box.innerHTML = "";
      var r = new VF.Renderer(box, VF.Renderer.Backends.SVG); r.resize(w, 130);
      var c = r.getContext(), st = new VF.Stave(4, 14, w - 10);
      st.addClef("percussion").addTimeSignature("4/4").setContext(c).draw();
      var up = drumVoice(VF, hands, 1), down = drumVoice(VF, feet, -1);
      var v1 = new VF.Voice({ num_beats: 4, beat_value: 4 }).addTickables(up), v2 = new VF.Voice({ num_beats: 4, beat_value: 4 }).addTickables(down);
      var beams = VF.Beam.generateBeams(up, { stem_direction: 1 }).concat(VF.Beam.generateBeams(down, { stem_direction: -1 }));
      new VF.Formatter().joinVoices([v1, v2]).format([v1, v2], w - 110);
      v1.draw(c, st); v2.draw(c, st); beams.forEach(function (b) { b.setContext(c).draw(); });
      // Follow the page theme: VexFlow draws in fixed black and grey.
      box.innerHTML = box.innerHTML.replace(/(fill|stroke)="(black|#000000|#999999)"/g, '$1="currentColor"');
    } catch (err) { box.innerHTML = '<p class="hint" style="margin: 6px">Could not draw the notation. The grid below shows the same groove.</p>'; }
  }
  function markSixteenth(six) {
    var pos = six % 16;
    document.querySelectorAll("#grooveGrid .cell, #compGrid .cell").forEach(function (c) { c.classList.toggle("now", +c.getAttribute("data-six") === pos); });
  }

  function loopCol(u) { return u; }
  function bassAt(u, pos) {
    var line = BASSLINE[u]; if (!line) return null; var e = line[pos]; if (!e) return null;
    var len = 1; while (pos + len < 16 && !line[pos + len] && len < 4) len++;
    return { midi: e[0], conf: e[1], len: len };
  }
  function noteName(m) { return spell(m + state.transpose) + (Math.floor((m + state.transpose) / 12) - 1); }
  function hitsText(probs) {
    var names = { 0: "1", 2: "the & of 1", 4: "2", 6: "the & of 2", 8: "3", 10: "the & of 3", 12: "4", 14: "the & of 4" };
    var top = Math.max.apply(null, probs), on = []; probs.forEach(function (p, i) { if (p > 0.6 * top && p > 0.2) on.push(names[i] || ("the " + COUNTS[i] + " of " + (Math.floor(i / 4) + 1))); });
    return on.length > 1 ? on.slice(0, -1).join(", ") + " and " + on[on.length - 1] : on.join("");
  }
  function rhythmGrid(label, probs, id) {
    var h = '<div class="groove" id="' + id + '"><span></span>' + COUNTS.map(function (c, i) { return '<span class="ct' + (i % 4 === 0 ? " downbeat" : "") + '">' + c + "</span>"; }).join("");
    h += '<span class="rl">' + label + "</span>" + probs.map(function (v, i) {
      var size = v < 0.1 ? 0 : 6 + Math.round(v * 12);
      return '<span class="cell' + (i % 4 === 0 ? " q0" : "") + '" data-six="' + i + '">' + (size ? '<span class="dot" style="width:' + size + "px;height:" + size + "px;opacity:" + (0.25 + v * 0.75).toFixed(2) + '"></span>' : "") + "</span>";
    }).join("");
    return h + "</div>";
  }
  function compBlock() {
    return '<div class="label subhead">Rhythm: when the chords hit</div>' + rhythmGrid("Chords", COMP, "compGrid") +
      '<p class="src-note">From the isolated keys and guitar track: chords on ' + hitsText(COMP) + '. Bigger dot: hit in more bars.</p>';
  }
  var VOICES = [["Bass", 40, 64], ["Baritone", 45, 69], ["Tenor", 48, 72], ["Alto", 53, 77], ["Mezzo", 57, 81], ["Soprano", 60, 84]];
  function bestTranspose(lo, hi) {
    var best = 0, bestCost = Infinity;
    for (var t = -6; t <= 6; t++) {
      var a = VOCAL.low + t, b = VOCAL.high + t, cost = Math.max(0, lo - a) * 3 + Math.max(0, b - hi) * 3 + Math.abs((a + b) / 2 - (lo + hi) / 2) * 0.2 + Math.abs(t) * 0.05;
      if (cost < bestCost) { bestCost = cost; best = t; }
    }
    return best;
  }
  function rangeSvg(voice) {
    var lo = 40, hi = 86, W = 520, H = 70, X = function (m) { return 10 + (m - lo) / (hi - lo) * (W - 20); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Song vocal range against your voice">';
    for (var m = lo; m <= hi; m++) if (m % 12 === 0) s += '<line x1="' + X(m) + '" y1="8" x2="' + X(m) + '" y2="58" stroke="var(--line)"/><text x="' + X(m) + '" y="68" font-size="11" text-anchor="middle" fill="var(--muted)" font-family="var(--font-body)">C' + (m / 12 - 1) + "</text>";
    if (voice) s += '<rect x="' + X(voice[1]) + '" y="34" width="' + (X(voice[2]) - X(voice[1])) + '" height="16" rx="5" fill="var(--accent-soft)" stroke="var(--accent)"/><text x="' + (X(voice[1]) + 6) + '" y="46" font-size="11" fill="var(--ink)" font-family="var(--font-body)">' + voice[0] + "</text>";
    var a = VOCAL.low + state.transpose, b = VOCAL.high + state.transpose;
    s += '<rect x="' + X(a) + '" y="12" width="' + (X(b) - X(a)) + '" height="16" rx="5" fill="var(--warn-soft)" stroke="var(--warn)"/><text x="' + (X(a) + 6) + '" y="24" font-size="11" fill="var(--ink)" font-family="var(--font-body)">Song: ' + noteName(VOCAL.low) + "–" + noteName(VOCAL.high) + "</text>";
    return s + "</svg>";
  }

  function renderMixer() {
    var stems = [["drums", "Drums"], ["bass", "Bass"], ["chords", "Chords"], ["click", "Click"]];
    $("mixer").innerHTML = stems.map(function (s) {
      var extra = s[0] === "chords" ? '<span class="seg-ctl sound" role="group" aria-label="Chord sound"><button type="button" data-sound="guitar" class="' + (state.chordSound === "guitar" ? "on" : "") + '">Guitar</button><button type="button" data-sound="rhodes" class="' + (state.chordSound === "rhodes" ? "on" : "") + '">Rhodes</button><button type="button" data-sound="piano" class="' + (state.chordSound === "piano" ? "on" : "") + '">Piano</button></span>' : "";
      return '<div class="strip" style="grid-template-columns: 64px 54px 50px minmax(0, 1fr)"><span>' + s[1] + '</span><button type="button" class="btn mute' + (state.mute[s[0]] ? " off" : "") + '" data-mute="' + s[0] + '">' + (state.mute[s[0]] ? "Muted" : "On") + '</button>' +
        '<button type="button" class="btn solo' + (state.solo === s[0] ? " on" : "") + '" data-solo="' + s[0] + '" style="justify-content: center; padding: 4px 0; font-size: 12.5px">Solo</button>' +
        '<input type="range" min="0" max="100" value="' + Math.round(state.mix[s[0]] * 100) + '" data-mix="' + s[0] + '" aria-label="' + s[1] + ' volume"></div>' + (extra ? '<div style="margin: -4px 0 0 64px">' + extra + "</div>" : "");
    }).join("");
  }

  // Waveform from the real energy profile, with sections, spots to check, loop and playhead.
  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function drawWave() {
    var cv = $("wave"), dpr = window.devicePixelRatio || 1, w = cv.clientWidth, hgt = cv.clientHeight;
    if (!w) return;
    cv.width = w * dpr; cv.height = hgt * dpr;
    var g = cv.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, w, hgt);
    var X = function (t) { return t / DURATION * w; };
    g.fillStyle = css("--accent-soft");
    GROUPS.forEach(function (gr, gi) { if (gi % 2 === 0) gr.occurrences.forEach(function (o) { g.fillRect(X(barTime(o[0])), 0, X(barTime(o[o.length - 1] + 1)) - X(barTime(o[0])), hgt); }); });
    if (state.loopOn && state.loop) { g.fillStyle = css("--accent"); g.globalAlpha = 0.18; g.fillRect(X(barTime(state.loop[0])), 0, X(barTime(state.loop[1] + 1)) - X(barTime(state.loop[0])), hgt); g.globalAlpha = 1; }
    g.fillStyle = css("--wave");
    for (var i = 0; i < ENERGY.length; i++) {
      var t0 = ENERGY[i][0], t1 = i + 1 < ENERGY.length ? ENERGY[i + 1][0] : t0 + 0.6, amp = Math.pow(10, ENERGY[i][1] / 20);
      var steps = 6;
      for (var s = 0; s < steps; s++) {
        var t = t0 + (t1 - t0) * s / steps, wob = 0.75 + 0.25 * Math.abs(Math.sin(t * 13.7 + s)), a = Math.max(0.02, amp * wob) * (hgt / 2 - 3);
        g.fillRect(X(t), hgt / 2 - a, Math.max(1, X(t1) - X(t0)) / steps - 0.6, a * 2);
      }
    }
    g.fillStyle = css("--warn");
    song.forEach(function (b, i) { if (b.chords.some(function (c) { return c.doubt && !c.fixed; })) g.fillRect(X(barTime(i)), hgt - 4, X(barTime(i + 1)) - X(barTime(i)), 4); });
    g.fillStyle = css("--muted"); g.font = "11px " + css("--font-body");
    var lastX = -99; GROUPS.forEach(function (gr) { gr.occurrences.forEach(function (o) { var x = X(barTime(o[0])); if (x - lastX > 14) { g.fillText(gr.label, x + 3, 12); lastX = x; } }); });
    g.fillStyle = css("--accent"); g.fillRect(X(beatTime(state.beat)) - 1, 0, 2, hgt);
  }

  function nowHint(ch) {
    if (state.inst === "guitar") {
      if (state.pos === "open" && state.capo) return showShapes() ? "sounds <b>" + pretty(nameOf(ch)) + "</b>, capo " + state.capo : "play the <b>" + pretty(nameOf(ch, state.capo)) + "</b> shape, capo " + state.capo;
      return state.pos === "funk" ? "funk triad on strings 3-2-1" : "barre chord, no capo";
    }
    if (state.inst === "voice") return "chord tones <b>" + [0, ch.q === "m" ? 3 : 4, 7].map(function (i) { return pretty(spell(ch.pc + state.transpose + i)); }).join(" ") + "</b>";
    if (state.inst === "drums") return "kick on <b>" + hitsText(GROOVE.kick) + "</b>, snare on <b>" + hitsText(GROOVE.snare) + "</b>";
    if (state.inst === "bass") { var nn = []; (BASSLINE[curBar()] || []).forEach(function (e) { if (e) { var x = pretty(spell(e[0] + state.transpose)); if (nn.indexOf(x) < 0) nn.push(x); } }); return "this bar: <b>" + nn.join(" ") + "</b>"; }
    var iv = [0, ch.q === "m" ? 3 : 4, 7];
    return "notes <b>" + iv.map(function (i) { return pretty(spell(ch.pc + state.transpose + i)); }).join(" ") + "</b>";
  }
  function renderPosition() {
    var b = state.beat, u = curBar(), ch = chordAtBeat(b), up = upcoming(b, 2), bar = song[u];
    $("bigChord").innerHTML = pretty(nameOf(ch, showShapes() ? state.capo : 0));
    $("bigRoman").textContent = roman(ch);
    $("nowSub").innerHTML = nowHint(ch);
    var sh = showShapes() ? state.capo : 0;
    $("nextChord").innerHTML = up[0] ? pretty(nameOf(up[0], sh)) : "end";
    $("thenChord").innerHTML = up[1] ? pretty(nameOf(up[1], sh)) : "";
    [$("beats"), $("stBeats")].forEach(function (box) { for (var i = 0; i < box.children.length; i++) box.children[i].classList.toggle("on", i === b % BEATS); });
    $("barInfo").textContent = "Bar " + (u + 1) + " of " + TOTAL_BARS;
    var gn = GROUPS[bar.group].occurrences.length;
    $("passInfo").textContent = "Line " + GROUPS[bar.group].label + (gn > 1 ? ", pass " + (bar.occ + 1) + " of " + gn : "");
    $("timeInfo").textContent = fmt(beatTime(b));
    $("posInfo").innerHTML = "<b>" + fmt(beatTime(b)) + "</b> / " + fmt(DURATION);
    if (state.stage) {
      $("stNow").innerHTML = pretty(nameOf(ch, sh));
      $("stShape").innerHTML = nowHint(ch);
      $("stNext").innerHTML = up[0] ? pretty(nameOf(up[0], sh)) : "end"; $("stThen").innerHTML = up[1] ? pretty(nameOf(up[1], sh)) : "";
      var col = song[u].col, mp = "", len = GROUPS[bar.group].occurrences[bar.occ].length;
      for (var k = 0; k < len; k++) mp += '<i class="' + (k === col ? "on" : k < col ? "done" : "") + '"></i>';
      $("stMap").innerHTML = mp;
      $("stTop").textContent = "Bar " + (u + 1) + " · line " + GROUPS[bar.group].label + (gn > 1 ? ", pass " + (bar.occ + 1) + " of " + gn : "") + " · " + state.bpm + " BPM";
    }
    paintBars(); drawWave();
  }
  var lastBar = -1, lastPass = -1, lastChord = "";
  function onBeat() {
    var u = curBar(), pass = song[u].group + ":" + song[u].occ, ch = chordAtBeat(state.beat), key = ch.pc + ch.q;
    if (pass !== lastPass) { renderSheet(); lastPass = pass; }
    if (u !== lastBar && (state.inst === "bass" || state.inst === "piano")) renderDesk();
    else if (key !== lastChord && state.inst !== "bass" && state.inst !== "drums" && state.inst !== "voice") renderDesk();
    if (key !== lastChord) $("srChord").textContent = nameOf(ch);
    lastBar = u; lastChord = key;
    renderPosition();
  }
  function renderAll() { funkCache = null; if (ctx) Object.keys(loading).forEach(function (n) { ensureNotes(n).catch(function () {}); }); renderChips(); renderSheet(); renderHarmony(); renderDesk(); renderMixer(); lastBar = lastPass = -1; lastChord = ""; onBeat(); updateLoopInfo(); }
  function updateLoopInfo() {
    $("loopInfo").textContent = state.loopOn && state.loop ? "Looping bars " + (state.loop[0] + 1) + "–" + (state.loop[1] + 1) + (state.trainer ? " · trainer on" : "") : "No loop";
    $("loopBtn").classList.toggle("on", state.loopOn);
  }

  // Audio engine. Real instrument samples (FluidR3_GM, MIT), one bus per stem, a reverb send for the
  // chords, and a compressor on the master so stacked voices never clip.
  var ctx = null, bus = {}, master = null, decoded = {}, loading = {}, sampleKeys = {};
  var timer = null, nextTime = 0, six = 0, queue = [], countLeft = 0;
  function hz(m) { return 440 * Math.pow(2, (m - 69) / 12); }
  function makeImpulse(seconds) {
    var sr = ctx.sampleRate, len = Math.floor(sr * seconds), buf = ctx.createBuffer(2, len, sr);
    for (var c = 0; c < 2; c++) {
      var d = buf.getChannelData(c), lp = 0;
      for (var i = 0; i < len; i++) { lp = lp * 0.55 + (Math.random() * 2 - 1) * 0.45; d[i] = lp * Math.pow(1 - i / len, 3.2); }
    }
    return buf;
  }
  function ensureAudio() {
    if (ctx) return true;
    try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { toast("Audio is not available in this browser."); return false; }
    var comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18; comp.knee.value = 10; comp.ratio.value = 4; comp.attack.value = 0.004; comp.release.value = 0.16;
    master = ctx.createGain(); master.gain.value = 0.9; master.connect(comp); comp.connect(ctx.destination);
    var verb = ctx.createConvolver(), verbIn = ctx.createGain(), verbOut = ctx.createGain();
    verb.buffer = makeImpulse(1.7); verbIn.gain.value = 0.22; verbOut.gain.value = 0.7;
    verbIn.connect(verb); verb.connect(verbOut); verbOut.connect(master);
    var levels = { drums: 0.75, bass: 0.95, chords: 0.7, click: 0.7, preview: 0.9 };
    Object.keys(levels).forEach(function (s) {
      var g = ctx.createGain(), trim = ctx.createGain(); trim.gain.value = levels[s];
      g.connect(trim); trim.connect(master);
      if (s === "chords" || s === "preview") trim.connect(verbIn);
      bus[s] = g;
    });
    applyMix(); return true;
  }
  function applyMix() {
    if (!ctx) return;
    ["drums", "bass", "chords", "click"].forEach(function (s) { bus[s].gain.value = state.solo ? (state.solo === s ? state.mix[s] : 0) : (state.mute[s] ? 0 : state.mix[s]); });
  }
  function b64ToBuf(b64) { var bin = atob(b64), n = bin.length, u = new Uint8Array(n); for (var i = 0; i < n; i++) u[i] = bin.charCodeAt(i); return u.buffer; }
  // Scripts load on demand, so the page shows at once and phones only fetch the sounds they play.
  var scriptCache = {};
  function loadScript(src) {
    if (scriptCache[src]) return scriptCache[src];
    scriptCache[src] = new Promise(function (res, rej) {
      var el = document.createElement("script"); el.src = src; el.async = true;
      el.onload = function () { res(); }; el.onerror = function () { delete scriptCache[src]; rej(new Error("Could not load " + src)); };
      document.head.appendChild(el);
    });
    return scriptCache[src];
  }
  function decodeOne(b64) {
    return new Promise(function (res) {
      try { ctx.decodeAudioData(b64ToBuf(b64), function (b) { res(b); }, function () { res(null); }); } catch (e) { res(null); }
    });
  }
  function loadInst(name) {
    if (loading[name]) return loading[name];
    loading[name] = loadScript("samples-" + name + ".js").then(function () {
      var src = window.WOODSHED_SAMPLES && window.WOODSHED_SAMPLES[name];
      if (!src) throw new Error("Samples missing for " + name);
      decoded[name] = decoded[name] || {}; sampleKeys[name] = sampleKeys[name] || [];
      return src;
    });
    loading[name].catch(function () { delete loading[name]; });
    return loading[name];
  }
  // Only the notes this song needs are decoded, at full quality: the original files are never re-encoded.
  function nearestKey(src, midi) { var best = null; Object.keys(src).forEach(function (k) { if (best === null || Math.abs(k - midi) < Math.abs(best - midi)) best = +k; }); return best; }
  function neededMidis(name) {
    var chords = uniqueChords().slice(), out = {};
    song.forEach(function (b) { b.chords.forEach(function (c) { if (c.doubt) c.doubt.alts.forEach(function (a) { chords.push({ pc: a[0], q: a[1] }); }); }); });
    chords.forEach(function (ch) {
      var list = name === "guitar" ? guitarMidi(ch) : name === "muted" ? guitarMidi(ch).slice(-3)
        : name === "bass" ? [] : name === "drums" ? [36, 37, 38, 42, 44, 46] : keysMidi(ch, true);
      list.forEach(function (m) { out[m] = 1; });
    });
    if (name === "bass") BASSLINE.forEach(function (bar) { bar.forEach(function (e) { if (e) out[e[0] + state.transpose] = 1; }); });
    if (name === "piano" || name === "rhodes") VOICINGS.forEach(function (v) { v.forEach(function (pc) { out[60 + ((pc + state.transpose + 120) % 12)] = 1; }); });
    return Object.keys(out).map(Number);
  }
  function ensureNotes(name) {
    return loadInst(name).then(function (src) {
      var want = {}; neededMidis(name).forEach(function (m) { var k = nearestKey(src, m); if (k !== null && !decoded[name][k]) want[k] = 1; });
      var keys = Object.keys(want), i = 0;
      function next() {
        if (i >= keys.length) return Promise.resolve();
        var batch = keys.slice(i, i + 3); i += 3;
        return Promise.all(batch.map(function (k) { return decodeOne(src[k]).then(function (b) { if (b) decoded[name][k] = b; }); })).then(next);
      }
      return next().then(function () {
        sampleKeys[name] = Object.keys(decoded[name]).map(Number).sort(function (a, b) { return a - b; });
        if (!sampleKeys[name].length) throw new Error("No playable samples for " + name);
      });
    });
  }
  function chordInst() { return state.chordSound === "piano" ? "piano" : state.chordSound === "rhodes" ? "rhodes" : "guitar"; }
  function withSounds(names, fn) {
    if (!ensureAudio()) return;
    if (ctx.state === "suspended") ctx.resume();
    var pending = names.filter(function (n) { return !loading[n]; });
    if (pending.length) toast("Loading sounds: " + pending.filter(function (n) { return n !== "muted"; }).join(", ") + "…");
    Promise.all(names.map(ensureNotes)).then(fn, function (err) { toast((err && err.message ? err.message + ". " : "") + "Check your connection and press play again."); });
  }
  function sample(name, midi, t, dur, vel, out, release) {
    var keys = sampleKeys[name]; if (!keys) return;
    var k = keys[0];
    for (var i = 0; i < keys.length; i++) if (Math.abs(keys[i] - midi) < Math.abs(k - midi)) k = keys[i];
    var src = ctx.createBufferSource(), g = ctx.createGain(), rel = release || 0.08;
    src.buffer = decoded[name][k]; src.playbackRate.value = Math.pow(2, (midi - k) / 12);
    var v = vel * (0.92 + Math.random() * 0.16);
    g.gain.setValueAtTime(v, t); g.gain.setValueAtTime(v, t + dur); g.gain.exponentialRampToValueAtTime(0.0001, t + dur + rel);
    src.connect(g); g.connect(out); src.start(t); src.stop(t + dur + rel + 0.05);
  }
  function hum(t) { return t + (Math.random() - 0.5) * 0.008; }
  function strum(name, midis, t, dur, vel, up, out, gap) {
    (up ? midis.slice().reverse() : midis).forEach(function (m, i) { sample(name, m, t + i * (gap || 0.012), dur, vel * (up ? 0.85 : 1), out, 0.06); });
  }
  // The notes actually fingered in the selected guitar position, or the keyboard voicing.
  var funkCache = null;
  function funkFor(ch) {
    if (!funkCache) funkCache = funkVoicings(uniqueChords());
    var v = funkCache[ch.pc + ch.q]; if (v) return v;
    var c = triadCandidates(ch.pc + state.transpose, ch.q)[0]; return { frets: [-1, -1, -1, c[0], c[1], c[2]] };
  }
  var STRINGS = [40, 45, 50, 55, 59, 64];
  function guitarMidi(ch, pos) {
    var sh, capo = 0, p = pos || state.pos;
    if (p === "open") { sh = openShape(ch.pc + state.transpose - state.capo, ch.q); capo = state.capo; }
    else if (p === "barre") sh = barreShape(ch.pc + state.transpose, ch.q);
    else sh = funkFor(ch);
    var out = []; sh.frets.forEach(function (f, i) { if (f >= 0) out.push(STRINGS[i] + capo + f); }); return out;
  }
  function keysMidi(ch, withBass) { var r = (ch.pc + state.transpose + 120) % 12, n0 = r < 7 ? 60 + r : 48 + r, v = [n0, n0 + (ch.q === "m" ? 3 : 4), n0 + 7]; return withBass ? [n0 - 12].concat(v) : v; }

  // One bar of funk, on a sixteenth-note grid.
  var KICK = {}, SNARE = {}, GHOST = {}, HAT = {};
  for (var gi = 0; gi < 16; gi++) {
    if (GROOVE.kick[gi] > 0.5) KICK[gi] = 0.95;
    if (GROOVE.snare[gi] > 0.5) SNARE[gi] = 0.85; else if (GROOVE.snare[gi] > 0.1) GHOST[gi] = 1;
    if (GROOVE.hat[gi] > 0.4) HAT[gi] = 0.12 + 0.3 * GROOVE.hat[gi];
  }
  // The chord track follows the comping rhythm heard on the record.
  var GTR_HIT = {}, KEYS_HIT = {}, GTR_GHOST = {};
  COMP.forEach(function (p, i) { if (p > 0.5) { GTR_HIT[i] = 0.6 + 0.3 * p; KEYS_HIT[i] = 0.45 + 0.2 * p; } else if (p >= 0.3) GTR_GHOST[i] = 1; });
  function playSixteenth(s, t, sec, override) {
    var pos = s % 16, beat = Math.floor(s / 4), ch = override || chordAtBeat(beat);
    if (KICK[pos]) sample("drums", 36, hum(t), 0.3, KICK[pos] * 0.95, bus.drums);
    if (SNARE[pos]) sample("drums", 38, hum(t), 0.4, 0.8, bus.drums);
    if (GHOST[pos]) sample("drums", 38, hum(t), 0.15, 0.13, bus.drums);
    if (HAT[pos]) sample("drums", 42, hum(t), 0.12, HAT[pos], bus.drums);
    var bl = bassAt(Math.floor(s / 16) % TOTAL_BARS, pos);
    if (bl) sample("bass", bl.midi + state.transpose, hum(t), sec * bl.len * 0.92, 0.75 + 0.25 * bl.conf, bus.bass, 0.05);
    var inst = chordInst();
    if (inst === "guitar") {
      if (GTR_HIT[pos]) strum("guitar", guitarMidi(ch), hum(t), sec * 0.9, GTR_HIT[pos] * 0.42, pos % 4 === 2, bus.chords);
      else if (GTR_GHOST[pos] && sampleKeys.muted && sampleKeys.muted.length) strum("muted", guitarMidi(ch).slice(-3), hum(t), 0.05, 0.14, true, bus.chords, 0.006);
    } else if (KEYS_HIT[pos]) {
      keysMidi(ch, false).forEach(function (m) { sample(inst, m, hum(t), sec * (inst === "rhodes" ? 2.6 : 2.2), KEYS_HIT[pos] * 0.45, bus.chords, 0.12); });
    }
    if (pos % 4 === 0) sample("drums", 37, t, 0.08, pos === 0 ? 0.6 : 0.32, bus.click);
  }
  function loopBounds() { return state.loopOn && state.loop ? [state.loop[0] * 16, (state.loop[1] + 1) * 16] : [0, TOTAL_BARS * 16]; }
  function tick() {
    while (nextTime < ctx.currentTime + 0.12) {
      var sec = 60 / state.bpm / 4;
      if (countLeft > 0) {
        if (countLeft % 4 === 0) sample("drums", 37, nextTime, 0.08, countLeft === 16 ? 0.7 : 0.45, master);
        countLeft--; nextTime += sec; continue;
      }
      var lb = loopBounds();
      if (six >= lb[1]) {
        if (state.loopOn && state.loop) {
          six = lb[0];
          if (state.trainer && state.bpm < BPM) { setBpm(Math.min(BPM, state.bpm + 5)); toast("Trainer: " + state.bpm + " BPM"); sec = 60 / state.bpm / 4; }
        } else { stop(); return; }
      }
      playSixteenth(six, nextTime, sec);
      queue.push({ t: nextTime, beat: Math.floor(six / 4), six: six });
      six++; nextTime += sec;
    }
  }
  function frame() {
    if (!state.playing) return;
    var now = ctx.currentTime;
    while (queue.length && queue[0].t <= now) { var q = queue.shift(); if (q.beat !== state.beat) { state.beat = q.beat; onBeat(); } markSixteenth(q.six); }
    requestAnimationFrame(frame);
  }
  function play() {
    withSounds(["drums", "bass", chordInst(), "muted"], function () {
      if (state.playing) return;
      state.playing = true; queue = [];
      var lb = loopBounds(); six = curBar() * 16; if (six < lb[0] || six >= lb[1]) six = lb[0];
      state.beat = six / 4; onBeat();
      countLeft = state.countIn ? 16 : 0; nextTime = ctx.currentTime + 0.08;
      timer = setInterval(tick, 25); tick(); requestAnimationFrame(frame);
      $("playBtn").textContent = "❚❚"; $("playBtn").setAttribute("aria-label", "Pause");
    });
  }
  function stop() { state.playing = false; clearInterval(timer); timer = null; $("playBtn").textContent = "▶"; $("playBtn").setAttribute("aria-label", "Play"); }
  function audition(barIdx, alt) {
    // Plays the bar once with the candidate chord. On a real recording, the candidate is layered softly over the original bar.
    withSounds(["drums", "bass", chordInst(), "muted"], function () {
      if (state.playing) stop();
      var sec = 60 / state.bpm / 4, t = ctx.currentTime + 0.06, cand = { pc: alt[0], q: alt[1] };
      for (var s = 0; s < 16; s++) playSixteenth(barIdx * 16 + s, t + s * sec, sec, cand);
    });
  }
  function hearChord(ch, sound) {
    var inst = sound || chordInst();
    withSounds([inst], function () {
      var t = ctx.currentTime + 0.04;
      if (inst === "guitar") strum("guitar", guitarMidi(ch), t, 2.2, 0.55, false, bus.preview, 0.03);
      else keysMidi(ch, true).forEach(function (m) { sample(inst, m, t, 2.4, 0.5, bus.preview, 0.3); });
    });
  }
  function hearArp(ch) {
    withSounds(["piano"], function () { var t = ctx.currentTime + 0.04; keysMidi(ch, true).forEach(function (m, i) { sample("piano", m, t + i * 0.42, 1.3, 0.55, bus.preview, 0.3); }); });
  }
  function hearGroove(withBand) {
    withSounds(["drums", "bass", chordInst(), "muted"], function () {
      if (state.playing) stop();
      var sec = 60 / state.bpm / 4, t = ctx.currentTime + 0.06, u = curBar();
      for (var s = 0; s < 32; s++) {
        var at = t + s * sec, pos = s % 16;
        if (withBand) playSixteenth(u * 16 + (s % 16), at, sec);
        else {
          if (KICK[pos]) sample("drums", 36, at, 0.3, KICK[pos], bus.preview);
          if (SNARE[pos]) sample("drums", 38, at, 0.4, 0.8, bus.preview);
          if (GHOST[pos]) sample("drums", 38, at, 0.15, 0.13, bus.preview);
          if (HAT[pos]) sample("drums", 42, at, 0.12, HAT[pos], bus.preview);
        }
        (function (six, when) { setTimeout(function () { markSixteenth(six); }, Math.max(0, (when - ctx.currentTime) * 1000)); })(s, at);
      }
    });
  }
  function hearRiff(u) {
    withSounds(["bass"], function () {
      if (state.playing) stop();
      var sec8 = 60 / state.bpm / 2, t = ctx.currentTime + 0.05;
      var sec16 = sec8 / 2;
      for (var p16 = 0; p16 < 16; p16++) { var bn = bassAt(u, p16); if (bn) sample("bass", bn.midi + state.transpose, t + p16 * sec16, sec16 * bn.len * 0.92, 1, bus.preview, 0.05); }
    });
  }

  var toastTimer = null;
  function toast(msg) { var t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 2600); }
  function seek(u) { state.beat = u * BEATS; if (state.playing) { stop(); play(); } else onBeat(); }

  function openPop(btn) {
    var ref = btn.getAttribute("data-ref").split("_"), u = +ref[0], ch = song[u].chords[+ref[1]], pop = $("pop");
    var h = "<h3>Which one do you hear?</h3><p>" + ch.doubt.why + "</p>";
    ch.doubt.alts.forEach(function (a, k) {
      h += '<div class="alt"><span class="an">' + pretty(nameOf({ pc: a[0], q: a[1] })) + '</span><span class="meter"><i style="width:' + a[2] + '%"></i></span><span class="pc">' + a[2] + '%</span><span class="acts"><button type="button" data-hear="' + k + '" aria-label="Hear it in context">▶</button><button type="button" class="pick" data-pick="' + k + '">Use</button></span></div>';
    });
    h += '<p>▶ plays this bar with each candidate. Pick what matches your ear.</p>';
    pop.innerHTML = h; pop.hidden = false;
    var r = btn.getBoundingClientRect(), pw = pop.offsetWidth, ph = pop.offsetHeight;
    var left = Math.min(Math.max(16, r.left), window.innerWidth - pw - 16), top = r.bottom + 8;
    if (top + ph > window.innerHeight - 110) top = Math.max(16, r.top - ph - 8);
    pop.style.left = left + "px"; pop.style.top = top + "px";
    pop.onclick = function (e) {
      var hear = e.target.closest("[data-hear]"), pick = e.target.closest("[data-pick]");
      if (hear) audition(u, ch.doubt.alts[+hear.getAttribute("data-hear")]);
      if (pick) {
        var a = ch.doubt.alts[+pick.getAttribute("data-pick")];
        ch.pc = a[0]; ch.q = a[1]; ch.fixed = true;
        // A fixed one-beat blip that now matches its neighbour merges back into the bar.
        song.forEach(function (b) { if (b.chords.length === 2 && same(b.chords[0], b.chords[1])) b.chords = [C(b.chords[0].pc, b.chords[0].q, 4)]; });
        pop.hidden = true; renderAll(); toast("Saved. Exports will use " + nameOf({ pc: a[0], q: a[1] }) + ".");
      }
    };
    var f = pop.querySelector("[data-hear]"); if (f) f.focus();
  }

  // Bars: click to jump, drag across bars to set a loop.
  var drag = null;
  function barFromEl(el) { return displayBar(+el.getAttribute("data-col"), +el.getAttribute("data-group")); }
  document.addEventListener("pointerdown", function (e) {
    if (e.target.closest(".doubt")) return;
    var el = e.target.closest(".bar"); if (!el || el.classList.contains("empty")) return;
    drag = { start: barFromEl(el), end: barFromEl(el) };
  });
  document.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var el = document.elementFromPoint(e.clientX, e.clientY); el = el && el.closest(".bar:not(.empty)");
    if (el) { drag.end = barFromEl(el); if (drag.end !== drag.start) { state.loop = [Math.min(drag.start, drag.end), Math.max(drag.start, drag.end)]; state.loopOn = true; paintBars(); drawWave(); updateLoopInfo(); } }
  });
  document.addEventListener("pointerup", function () {
    if (!drag) return;
    if (drag.end === drag.start) seek(drag.start);
    else { toast("Looping bars " + (state.loop[0] + 1) + "–" + (state.loop[1] + 1) + ". Press play."); seek(state.loop[0]); }
    drag = null;
  });

  document.addEventListener("click", function (e) {
    var d = e.target.closest(".doubt"); if (d) { e.stopPropagation(); openPop(d); return; }
    var pop = $("pop"); if (!pop.hidden && !e.target.closest("#pop")) pop.hidden = true;
    if (!e.target.closest(".menu") && !e.target.closest("[data-menu-anchor]")) closeMenus();
    var go = e.target.closest("[data-goto]"); if (go) { var i = +go.getAttribute("data-goto"); seek(i); var el = barEl(i); if (el) el.scrollIntoView({ block: "center", behavior: "smooth" }); return; }
    var ex = e.target.closest("[data-export]"); if (ex) { closeMenus(); toast("In the real app this saves a " + ex.getAttribute("data-export") + " next to your song."); return; }
    var inst = e.target.closest("[data-inst]");
    if (inst) {
      state.inst = inst.getAttribute("data-inst"); document.querySelectorAll("[data-inst]").forEach(function (b) { b.classList.toggle("on", b === inst); });
      if (state.inst === "guitar") state.chordSound = "guitar"; if (state.inst === "piano") state.chordSound = "piano";
      if (state.step === 2 || state.step === 4) setStep(state.step, true);
      renderAll(); return;
    }
    var vw = e.target.closest("[data-view]"); if (vw) { state.view = vw.getAttribute("data-view"); renderSheet(); onBeat(); return; }
    var stp = e.target.closest("[data-step]"); if (stp) { setStep(+stp.getAttribute("data-step")); return; }
    var sg = e.target.closest("[data-song]"); if (sg) { closeMenus(); toast("Mockup: only this song is analysed here. " + sg.getAttribute("data-song") + " would open its own page."); return; }
    var pos = e.target.closest("[data-pos]"); if (pos) { state.pos = pos.getAttribute("data-pos"); renderSheet(); renderDesk(); hearChord(chordAtBeat(state.beat), "guitar"); return; }
    var st = e.target.closest("[data-strum]"); if (st) { var a = st.getAttribute("data-strum").split("_"); hearChord({ pc: +a[0], q: a[1] }, "guitar"); return; }
    var ky = e.target.closest("[data-keys]"); if (ky) { var b2 = ky.getAttribute("data-keys").split("_"); hearChord({ pc: +b2[0], q: b2[1] }, "piano"); return; }
    var ar = e.target.closest("[data-arp]"); if (ar) { var c3 = ar.getAttribute("data-arp").split("_"); hearArp({ pc: +c3[0], q: c3[1] }); return; }
    var vtb = e.target.closest("[data-voice]"); if (vtb) { state.voiceType = vtb.getAttribute("data-voice"); renderDesk(); return; }
    var fit = e.target.closest("[data-fit]"); if (fit) { state.transpose = +fit.getAttribute("data-fit"); renderAll(); toast("Transposed to " + spell(keyPc()) + " major: chart, shapes and band follow."); return; }
    var rv = e.target.closest("[data-recvoice]"); if (rv) {
      var inst = state.chordSound === "rhodes" ? "rhodes" : "piano", vcs = VOICINGS[curBar()] || [], root = chordAtBeat(state.beat);
      withSounds([inst], function () {
        var t0 = ctx.currentTime + 0.04, r = (root.pc + state.transpose + 120) % 12;
        sample(inst, 48 + r, t0, 2.4, 0.5, bus.preview, 0.3);
        vcs.forEach(function (pc) { sample(inst, 60 + ((pc + state.transpose + 120) % 12), t0, 2.4, 0.45, bus.preview, 0.3); });
      });
      return;
    }
    var gv = e.target.closest("[data-groove]"); if (gv) { hearGroove(gv.getAttribute("data-groove") === "2"); return; }
    var rf = e.target.closest("[data-riff]"); if (rf) { hearRiff(+rf.getAttribute("data-riff")); return; }
    var so = e.target.closest("[data-solo]"); if (so) { var sv = so.getAttribute("data-solo"); state.solo = state.solo === sv ? null : sv; applyMix(); renderMixer(); return; }
    var snd = e.target.closest("[data-sound]"); if (snd) { state.chordSound = snd.getAttribute("data-sound"); renderMixer(); hearChord(chordAtBeat(state.beat)); return; }
    var mu = e.target.closest("[data-mute]"); if (mu) { var s = mu.getAttribute("data-mute"); state.mute[s] = !state.mute[s]; applyMix(); renderMixer(); if (s === "bass" && state.mute.bass) toast("Bass muted. Your turn: the tab is under Bass."); }
  });
  document.addEventListener("input", function (e) { var m = e.target.getAttribute && e.target.getAttribute("data-mix"); if (m) { state.mix[m] = e.target.value / 100; applyMix(); } });
  document.addEventListener("keydown", function (e) {
    var tag = e.target.tagName, typing = tag === "INPUT" || tag === "TEXTAREA";
    if (e.key === "Escape") { $("pop").hidden = true; closeMenus(); if (state.stage) setStage(false); return; }
    var bar = e.target.closest && e.target.closest(".bar"); if (bar && e.key === "Enter") { e.preventDefault(); seek(barFromEl(bar)); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    var k = e.key;
    if (k === " " && (tag !== "BUTTON" || e.target.id === "playBtn")) { e.preventDefault(); if (state.playing) stop(); else play(); }
    else if (k === "ArrowRight" || k === "PageDown") { e.preventDefault(); seek(Math.min(TOTAL_BARS - 1, curBar() + 1)); }
    else if (k === "ArrowLeft" || k === "PageUp") { e.preventDefault(); seek(Math.max(0, curBar() - 1)); }
    else if (k === "l" || k === "L") $("loopBtn").click();
    else if (k === "[") setBpm(state.bpm - 5);
    else if (k === "]") setBpm(state.bpm + 5);
    else if (k === "s" || k === "S") setStage(!state.stage);
    else if (k >= "1" && k <= "4") setStep(+k);
    else if (k === "?") openMenu("helpMenu", $("helpBtn"));
  });
  $("wave").addEventListener("click", function (e) {
    var r = this.getBoundingClientRect(), t = (e.clientX - r.left) / r.width * DURATION;
    seek(barAtTime(t));
  });
  $("playBtn").addEventListener("click", function () { if (state.playing) stop(); else play(); });
  $("loopBtn").addEventListener("click", function () {
    if (!state.loop) state.loop = occRange(curBar());
    state.loopOn = !state.loopOn; updateLoopInfo(); paintBars(); drawWave();
  });
  $("trainBtn").addEventListener("click", function () {
    state.trainer = !state.trainer; this.classList.toggle("on", state.trainer);
    if (state.trainer && state.bpm >= BPM) setBpm(Math.round(BPM * 0.7));
    if (state.trainer && !state.loopOn) $("loopBtn").click();
    updateLoopInfo(); toast(state.trainer ? "Trainer on: " + state.bpm + " BPM, +5 BPM each loop up to " + BPM + "." : "Trainer off.");
  });
  $("countBtn").addEventListener("click", function () { state.countIn = !state.countIn; syncToggles(); });
  function setBpm(v) {
    state.bpm = Math.max(50, Math.min(150, Math.round(v))); state.speed = state.bpm / BPM;
    $("bpm").value = state.bpm; $("bpmVal").textContent = state.bpm + " BPM";
    $("bpmReset").classList.toggle("on", state.bpm === BPM);
    if (state.stage) renderPosition();
  }
  $("bpm").addEventListener("input", function () { setBpm(+this.value); });
  $("bpmUp").addEventListener("click", function () { setBpm(state.bpm + 1); });
  $("bpmDown").addEventListener("click", function () { setBpm(state.bpm - 1); });
  $("bpmReset").addEventListener("click", function () { setBpm(BPM); });
  $("trUp").addEventListener("click", function () { state.transpose = Math.min(6, state.transpose + 1); renderAll(); });
  $("trDown").addEventListener("click", function () { state.transpose = Math.max(-6, state.transpose - 1); renderAll(); });
  $("capoUp").addEventListener("click", function () { state.capo = Math.min(7, state.capo + 1); renderAll(); });
  $("capoDown").addEventListener("click", function () { state.capo = Math.max(0, state.capo - 1); renderAll(); });
  function setStage(on) {
    state.stage = on; $("stage").hidden = !on;
    if (on) { try { var p = $("stage").requestFullscreen && $("stage").requestFullscreen(); if (p && p.catch) p.catch(function () {}); } catch (err) {} renderPosition(); }
    else if (document.fullscreenElement) { try { document.exitFullscreen(); } catch (err) {} }
  }
  $("stageBtn").addEventListener("click", function () { setStage(true); });
  $("stageExit").addEventListener("click", function () { setStage(false); });
  document.addEventListener("fullscreenchange", function () { if (!document.fullscreenElement && state.stage) setStage(false); });
  window.addEventListener("resize", function () { drawWave(); if (state.inst === "drums") renderDrumStaff(); });
  if (window.matchMedia) { var mq = window.matchMedia("(prefers-color-scheme: dark)"); if (mq.addEventListener) mq.addEventListener("change", drawWave); }
  new MutationObserver(drawWave).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  if (window.ResizeObserver) new ResizeObserver(function () { $("wrap").style.paddingBottom = ($("dock").offsetHeight + 24) + "px"; document.documentElement.style.setProperty("--dock-h", $("dock").offsetHeight + "px"); }).observe($("dock"));

  function syncToggles() {
    $("trainBtn").classList.toggle("on", state.trainer); $("countBtn").classList.toggle("on", state.countIn);
    applyMix(); renderMixer(); updateLoopInfo(); paintBars(); drawWave();
  }
  function setStep(n, quiet) {
    state.step = n;
    document.querySelectorAll("[data-step]").forEach(function (b) { b.classList.toggle("on", +b.getAttribute("data-step") === n); });
    var mine = state.inst === "bass" ? "bass" : state.inst === "drums" ? "drums" : state.inst === "voice" ? null : "chords", part = { bass: "bass", piano: "keys", guitar: "guitar", drums: "drums", voice: "voice" }[state.inst], msg = "";
    state.solo = null; state.mute = { click: state.mute.click };
    if (n === 1) { state.loopOn = false; state.trainer = false; state.countIn = false; setBpm(BPM); msg = "Step 1: the full band at " + BPM + " BPM. Follow the big chord and the chart."; }
    if (n === 2) { state.loopOn = false; state.trainer = false; setBpm(BPM); state.solo = mine || "chords"; msg = mine ? "Step 2: your " + part + " part alone. Use the panel on the right to hear each piece." : "Step 2: the chords alone, to find your notes. Pick your voice type on the right."; }
    if (n === 3) {
      if (!state.loop) state.loop = occRange(curBar());
      state.loopOn = true; state.trainer = true; state.countIn = true; setBpm(Math.round(BPM * 0.7));
      msg = "Step 3: bars " + (state.loop[0] + 1) + "–" + (state.loop[1] + 1) + " loop from " + state.bpm + " BPM, 5 faster each pass. Drag across bars to pick others.";
    }
    if (n === 4) { state.loopOn = false; state.trainer = false; state.countIn = true; setBpm(BPM); if (mine) state.mute[mine] = true; msg = mine ? "Step 4: the " + part + " is muted. One bar of count-in, then it is you and the band." : "Step 4: the band plays, you sing. One bar of count-in."; }
    syncToggles();
    if (!quiet) toast(msg);
    if (n === 2 && window.innerWidth <= 900) { var d = document.querySelector(".desk-col"); if (d) d.scrollIntoView({ block: "start", behavior: "smooth" }); }
  }
  function closeMenus() { document.querySelectorAll(".menu").forEach(function (m) { m.hidden = true; }); }
  function openMenu(id, anchor) {
    var m = $(id), was = !m.hidden; closeMenus(); if (was) return;
    m.hidden = false;
    var r = anchor.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
    var left = Math.min(Math.max(16, r.right - w), window.innerWidth - w - 16);
    var top = r.top > window.innerHeight / 2 ? r.top - h - 8 : r.bottom + 8;
    m.style.left = left + "px"; m.style.top = Math.max(16, top) + "px";
    var f = m.querySelector("button, input"); if (f) f.focus();
  }
  [["mixBtn", "mixMenu"], ["exportBtn", "exportMenu"], ["setlistBtn", "setlistMenu"], ["helpBtn", "helpMenu"]].forEach(function (p) {
    var a = $(p[0]); a.setAttribute("data-menu-anchor", "1");
    a.addEventListener("click", function (e) { e.stopPropagation(); openMenu(p[1], a); });
  });
  $("moreBtn").addEventListener("click", function () { var open = $("dock").classList.toggle("open"); this.setAttribute("aria-expanded", String(open)); this.textContent = open ? "Hide" : "Controls"; });

  document.title = SONG.title + " · Woodshed";
  $("songTitle").textContent = SONG.title;
  $("songFile") && ($("songFile").textContent = SONG.file);
  $("madeWith").innerHTML = "Made with <code>woodshed " + SONG.file + "</code> in " + Math.round(SONG.analysis_seconds) + " s. Nothing was uploaded, no account.";
  $("setCur").textContent = SONG.title; $("setKey").innerHTML = keyName().split(" ")[0]; $("setBpm").textContent = BPM + " BPM";
  state.capo = suggestCapo();
  setBpm(BPM);
  renderAll();
})();

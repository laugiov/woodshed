// Wiring: reads the song, creates the store, the transport and the sounds, mounts the views and
// handles input (mouse, touch, keyboard and page-turner pedals). Loaded last.
(function () {
  "use strict";
  const W = window.Woodshed;
  const { h, $, chordNode } = W;
  const I = W.instruments;

  // The isolated track each instrument learns from (step 2) and plays over (step 4).
  const STEM_OF = { guitar: "other", piano: "other", bass: "bass", drums: "drums", voice: "vocals" };

  // 32-bit FNV-1a, enough to tell two analyses apart in a storage key.
  function fnv1a(text) {
    let hash = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(16);
  }

  function start() {
    const song = W.song.load();
    const meta = song.song;
    const songBpm = Math.round(meta.bpm);
    // Corrections are kept per analysis: a rebuilt page with other chords starts clean.
    // The key is made of what a correction depends on (chords, doubt ids, beats), not of the whole
    // bar data: a rebuild that only adds a field (a doubt's kind, sections) keeps the corrections.
    const chords = meta.bars.map((b) => b.chords.map((c) => [c.pc, c.quality, c.beats, c.doubt ? c.doubt.id : null]));
    const storageKey = "woodshed:corrections:" + fnv1a(JSON.stringify([chords, meta.beats]));

    const app = {
      song,
      songBpm,
      minBpm: Math.max(30, Math.round(songBpm * 0.5)),
      maxBpm: Math.round(songBpm * 1.25),
    };
    W.current = song;
    W.app = app;


    const store = W.createStore({
      time: 0, beat: 0, playing: false, transpose: 0, capo: song.capoFor(0), inst: "guitar", pos: "open",
      view: "concert", step: 1, loop: null, loopOn: false, trainer: false, countIn: false, bpm: songBpm,
      voiceType: null, stage: false, track: "mix", corrections: 0, click: false, chordSound: "guitar",
      sheet: null, // "grid" or "lyrics"; null: as suits the instrument
      bandKey: null, // the key the band plays this song in (semitones), once the library said; null: no library
      bandNote: "", // the leader's note on this song
      wordsElsewhere: false, // a phone of the band: words are added from the computer
      editing: false, // the chart's bars open the bar editor (views/editor.js)
    });
    app.store = store;

    // Names: the chord as heard, moved by the transposition and, for capo shapes, down by the capo.
    app.nameFor = (c, shift, s) => song.chordName(c, s.transpose - (shift || 0));
    app.showShapes = (s) => s.inst === "guitar" && s.pos === "open" && s.capo > 0 && s.view === "shapes";
    app.nowHint = function nowHint(c, s) {
      if (c.pc < 0) return W.t("no chord");
      const tones = () => I.triadOf(c.pc, c.quality).map((pc) => chordNode(song.noteName(pc, s.transpose), "tone"));
      if (s.inst === "guitar") {
        if (s.pos === "open" && s.capo) {
          return app.showShapes(s)
            ? W.nodes(W.t("sounds {chord}, capo {n}", { n: s.capo }), { chord: h("b", null, chordNode(app.nameFor(c, 0, s))) })
            : W.nodes(W.t("play the {chord} shape, capo {n}", { n: s.capo }), { chord: h("b", null, chordNode(app.nameFor(c, s.capo, s))) });
        }
        if (s.pos === "funk") return W.t("funk triad on strings 3-2-1");
        if (s.pos === "barre") return W.t("barre chord, no capo");
        // In the Open voicing a chord with no open shape is played as a barre: said as the diagram shows it.
        const shape = I.openOrBarre(song.view.shapes, c.pc + s.transpose, c.quality, I.bassOf(c, s.transpose));
        if (shape.open) return W.t("open shape");
        if (shape.barre > 0) return W.t("barre shape");
        return W.t("shape at fret {n}", { n: Math.min(...shape.frets.filter((f) => f > 0)) });
      }
      if (s.inst === "drums" && song.parts && song.parts.groove) {
        const g = song.parts.groove;
        const hits = I.grooveHits(g); // as the notation and the drums panel
        const kick = I.playedText(hits.kick, song.per);
        const snare = I.playedText(hits.snare, song.per);
        if (!kick && !snare) return W.t("no clear groove");
        if (!snare) return W.nodes(W.t("kick on {kick}, no steady snare"), { kick: h("b", null, kick) });
        if (!kick) return W.nodes(W.t("snare on {snare}, no steady kick"), { snare: h("b", null, snare) });
        return W.nodes(W.t("kick on {kick}, snare on {snare}"), { kick: h("b", null, kick), snare: h("b", null, snare) });
      }
      return W.nodes(s.inst === "voice" ? W.t("chord tones {notes}") : W.t("notes {notes}"), { notes: h("b", null, tones()) });
    };

    const popups = W.views.popups(app);
    app.toast = popups.toast;

    const barStart = (i) => (i >= song.bars.length ? song.bars[song.bars.length - 1].end : song.bars[Math.max(0, i)].start);

    const transport = W.createTransport(song.tracks, {
      onTime: (t) => store.set({ time: t, beat: song.beatAt(t), playing: transport.playing || app.counting() }),
      onEnded: () => store.set({ playing: false }),
      onError: (err, trackId) => {
        if (!trackId) {
          app.toast(W.t("The browser blocked playback: press play again."));
          return;
        }
        app.toast(err.message);
        // The track playing now broke (a file removed while the page was open): back to the mix.
        if (trackId === transport.track && trackId !== "mix") app.setTrack("mix");
      },
      onLoop: () => {
        const s = store.get();
        if (s.trainer && s.bpm < songBpm) {
          setBpm(Math.min(songBpm, s.bpm + 5));
          app.toast(W.t("Trainer: {bpm} BPM", { bpm: store.get().bpm }));
        }
      },
    });
    app.transport = transport;
    const sounds = W.createSounds(app.toast);
    app.sounds = sounds;

    // A follower's position comes from the leader: nothing on the device moves it or makes sound.
    const following = () => !!(W.band && W.band.mode() === "follow");
    const leaderMoves = () => app.toast(W.t("The leader moves the band. Press Stop following to play on your own."));

    function setBpm(v) {
      const bpm = Math.max(app.minBpm, Math.min(app.maxBpm, Math.round(v)));
      transport.setRate(bpm / songBpm);
      store.set({ bpm });
    }
    function setLoop(range, on) {
      transport.setLoop(on && range ? [barStart(range[0]), barStart(range[1] + 1)] : null);
      store.set({ loop: range, loopOn: !!(on && range) });
    }
    // The words, when they were placed on the voice (woodshed lyrics): read with the chart as it is.
    app.words = W.lyrics(song, window.WOODSHED_LYRICS);
    // What the chart shows: the words for those who sing or play chords, the grid for bass and drums.
    app.sheetMode = (s) => (!app.words || s.editing ? "grid" : s.sheet || (s.inst === "bass" || s.inst === "drums" ? "grid" : "lyrics"));

    // The sung line lit now: the last one begun, held a bar after its end for a long note, unless a
    // new part has started since (a jump to the next part does not light the line before it).
    app.lineNow = (s) => {
      if (!app.words) return { now: -1, next: 0 };
      const at = app.words.lineAt(s.time);
      const ln = at.now >= 0 ? app.words.lines[at.now] : null;
      const part = app.sectionOf(Math.floor(s.beat / song.per));
      if (ln && part && s.time > ln.end && song.barAt(ln.start + 0.15) < part.start) return { now: -1, next: at.next };
      return at;
    };

    // The song's parts: the band's own names and cuts (views/editor.js), else as the words named them
    // when placed, else as the analysis did.
    let editedParts = null;
    app.sections = () => editedParts || (app.words && app.words.sections) || meta.sections;
    song.partsNow = () => app.sections(); // the exports' parts (core/exports.js)
    // The analysis's lines, for the harmony summary and for parts taken back to the analysis.
    const analysisGroups = JSON.parse(JSON.stringify(meta.groups));
    app.analysisGroups = analysisGroups;
    const analysisLines = song.bars.map((b) => [b.group, b.occurrence, b.column]);
    app.sectionOf = (u) => {
      const list = app.sections();
      return list.length ? list[song.sectionIndex(u, list)] : null;
    };
    // What a loop takes by default: the section being played (a band loops "the chorus"), or the
    // line when the song has no sections.
    const lineOf = (u) => {
      const sec = app.sectionOf(u);
      return sec ? [sec.start, sec.end - 1] : song.occurrenceRange(u);
    };
    app.loopSection = (u) => {
      if (following()) return leaderMoves();
      setLoop(lineOf(u), true);
      app.seekBar(lineOf(u)[0]);
      const sec = app.sectionOf(u);
      const [from, to] = lineOf(u);
      app.toast(sec ? W.t("Looping {part}. Press play.", { part: W.partName(sec) }) : W.t("Looping bars {from}–{to}. Press play.", { from: from + 1, to: to + 1 }));
    };
    const curBar = () => Math.floor(store.get().beat / song.per);

    // Where the parts start: the sections, or without them the lines of the chart.
    function partStarts() {
      const list = app.sections();
      const starts = list.length ? list.map((sec) => sec.start) : song.song.groups.flatMap((g) => g.occurrences.map((o) => o[0]));
      return [...new Set(starts)].sort((a, b) => a - b);
    }
    // Back to the start of the part, or to the part before when already at its start.
    // A press in the first beat of a part means the part before (as on a music player).
    app.prevPart = () => {
      const beat = store.get().beat;
      const starts = [...new Set([0, ...partStarts()])].filter((b) => b * song.per <= beat);
      const k = starts.length - 1;
      app.seekBar(beat - starts[k] * song.per >= 1 || k === 0 ? starts[k] : starts[k - 1]);
    };
    app.nextPart = () => {
      const next = partStarts().find((b) => b > curBar());
      if (next !== undefined) app.seekBar(next);
    };
    // A jump the musician asks for: the page follows the music again (views/chart.js).
    app.seekBar = function seekBar(u) {
      if (following()) return leaderMoves();
      if (app.followAgain) app.followAgain();
      transport.seek(barStart(Math.max(0, Math.min(song.bars.length - 1, u))));
    };
    app.seekTime = (t) => {
      if (following()) return leaderMoves();
      if (app.followAgain) app.followAgain();
      transport.seek(Math.max(0, t));
    };
    app.setBpm = (v) => setBpm(v);
    app.setLoop = (range, on) => setLoop(range, on);
    // A count-in in progress: pressing play again cancels it.
    let countIn = null;
    app.togglePlay = async function togglePlay() {
      if (following()) return leaderMoves();
      app.cancelTimers();
      if (countIn) {
        countIn.cancelled = true;
        countIn = null;
        sounds.stopClicks();
        store.set({ playing: false });
        return;
      }
      if (transport.playing) {
        transport.pause();
        store.set({ playing: false });
        return;
      }
      const s = store.get();
      if (s.countIn) {
        const mine = { cancelled: false };
        countIn = mine;
        store.set({ playing: true });
        const left = await sounds.clicks(song.per, 60 / s.bpm);
        if (left !== null) await new Promise((resolve) => setTimeout(resolve, Math.max(0, left) * 1000));
        if (mine.cancelled) return;
        countIn = null;
        store.set({ playing: left !== null && (await transport.play()) });
      } else {
        const ok = await transport.play();
        store.set({ playing: ok });
      }
    };
    app.counting = () => countIn !== null;
    app.setTrack = async function setTrack(id) {
      if (!song.tracks.some((t) => t.id === id)) return false;
      store.set({ track: id }); // the menu shows the choice at once; the audio follows when loaded
      const ok = await transport.setTrack(id);
      if (!ok) {
        const kept = song.tracks.find((t) => t.id === transport.track);
        const failed = song.tracks.find((t) => t.id === id);
        store.set({ track: transport.track });
        app.toast(W.t("Could not read {file}. Still playing: {track}.", { file: failed.file, track: W.t(kept.label) }));
        return ok;
      }
      // Another track than the marked step card plays (Your part, the Tracks menu): that card is no
      // longer the one in use; step 3 plays no track of its own and stays.
      const s = store.get();
      const stem = STEM_OF[s.inst];
      const has = (t) => song.tracks.some((x) => x.id === t);
      const own = { 1: "mix", 2: "solo-" + stem, 4: "minus-" + stem }[s.step];
      const plays = own && (has(own) ? own : "mix"); // without the instruments' tracks, steps 2 and 4 play the mix
      if (plays && plays !== id && store.get().track === id) store.set({ step: null });
      return ok;
    };
    app.stemOf = (inst) => STEM_OF[inst];
    app.setInstrument = function setInstrument(inst) {
      store.set({ inst });
      const s = store.get();
      if (s.step === 2 || s.step === 4) app.setStep(s.step, true);
    };
    app.transposeTo = function transposeTo(t) {
      const transpose = Math.max(-6, Math.min(6, t));
      store.set({ transpose, capo: song.capoFor(transpose) });
      app.toast(W.t("Transposed to {key}: the chart and the shapes follow. The recording keeps its key.", { key: W.prettyText(song.keyName(transpose)) }));
    };
    // The band's key for this song (served by woodshed app): every device opens in it, and a change
    // made on one device reaches the others. A device already in that key just takes note of it.
    app.useBand = (band) => {
      const t = typeof band.transpose === "number" ? band.transpose : 0;
      const s = store.get();
      const fresh = s.bandKey === null ? t !== 0 : t !== s.bandKey;
      store.set({ bandKey: t, bandNote: band.note || "" });
      if (!fresh || t === s.transpose) return;
      store.set({ transpose: t, capo: song.capoFor(t) });
      app.toast(t
        ? W.t("The band plays this song in {key}: the chords follow, the recording keeps its key.", { key: W.prettyText(song.keyName(t)) })
        : W.t("The band plays this song in the recorded key again."));
    };
    app.keepBandKey = async () => {
      const t = store.get().transpose;
      const saved = app.shareBand && (await app.shareBand({ transpose: t, key: song.keyName(t) }));
      if (!saved) return app.toast(W.t("Not saved: the app did not answer."));
      app.useBand(saved);
      app.toast(W.t("Saved: the band plays this song in {key}, on every device.", { key: W.prettyText(song.keyName(t)) }));
    };
    app.setStep = function setStep(n, quiet) {
      const s = store.get();
      const stem = STEM_OF[s.inst];
      const has = (id) => song.tracks.some((t) => t.id === id);
      let message = "";
      if (n === 1) {
        setLoop(null, false);
        store.set({ trainer: false, countIn: false });
        setBpm(songBpm);
        app.setTrack("mix");
        message = W.t("Step 1: the full band at {bpm} BPM. Follow the big chord and the chart.", { bpm: songBpm });
      } else if (n === 2) {
        setLoop(null, false);
        store.set({ trainer: false, countIn: false });
        setBpm(songBpm);
        app.setTrack(has("solo-" + stem) ? "solo-" + stem : "mix");
        const alone = {
          guitar: W.t("Step 2: the guitar alone, isolated from the recording."),
          bass: W.t("Step 2: the bass alone, isolated from the recording."),
          piano: W.t("Step 2: the keys alone, isolated from the recording."),
          drums: W.t("Step 2: the drums alone, isolated from the recording."),
          voice: W.t("Step 2: the voice alone, isolated from the recording."),
        }[s.inst];
        message = has("solo-" + stem) ? alone : W.t("Step 2: learn the chords with the panel on the right.");
      } else if (n === 3) {
        setLoop(s.loop || lineOf(curBar()), true);
        store.set({ trainer: true, countIn: true });
        setBpm(Math.round(songBpm * 0.7));
        const l = store.get().loop;
        message = W.t("Step 3: bars {from}–{to} loop from {bpm} BPM, 5 faster each pass. Drag across bars to pick others.", { from: l[0] + 1, to: l[1] + 1, bpm: store.get().bpm });
      } else {
        setLoop(null, false);
        store.set({ trainer: false, countIn: true });
        setBpm(songBpm);
        app.setTrack(has("minus-" + stem) ? "minus-" + stem : "mix");
        const without = {
          guitar: W.t("Step 4: the recording without the guitar. One bar of count-in, then it is you."),
          bass: W.t("Step 4: the recording without the bass. One bar of count-in, then it is you."),
          piano: W.t("Step 4: the recording without the keys. One bar of count-in, then it is you."),
          drums: W.t("Step 4: the recording without the drums. One bar of count-in, then it is you."),
          voice: W.t("Step 4: the recording without the voice. One bar of count-in, then it is you."),
        }[s.inst];
        message = has("minus-" + stem) ? without : W.t("Step 4: play along with the full mix, after one bar of count-in.");
      }
      store.set({ step: n });
      if (!quiet) app.toast(message);
      if (n === 2 && !quiet && window.innerWidth <= 900) {
        const deskCol = document.querySelector(".desk-col");
        if (deskCol) deskCol.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    };

    // Corrections: the chord picked by ear replaces the doubtful one, here and in later visits.
    // Kept by doubt id (stable for one analysis), applied before neighbouring chords merge.
    const QUALITIES = new Set(["", "m", "7", "m7"]);
    let fixes = {};
    function merge(bar) {
      const out = [];
      for (const c of bar.chords) {
        const last = out[out.length - 1];
        if (last && song.same(last, c)) {
          last.beats += c.beats;
          // A correction to the chord before it in the bar: the merged chord carries its doubt, so
          // the correction can still be opened, changed or taken back.
          if (c.fixed && c.doubt && !(last.doubt && !last.fixed)) last.doubt = c.doubt;
          last.fixed = last.fixed || c.fixed;
        } else out.push(c);
      }
      bar.chords = out;
    }
    // The chords as analysed: every correction is applied to these, so a chart after a reload is
    // the same as the chart before it, however many times a doubt was corrected.
    const original = song.bars.map((b) => b.chords.map((c) => ({ ...c })));
    // The analysis's doubts: picks are checked against these, not against the chart now (a bar the band
    // typed has no doubt left, but its picks are kept for when the typed chords are taken back).
    const analysedDoubts = new Set(original.flat().filter((c) => c.doubt).map((c) => String(c.doubt.id)));
    // The band's typed bars and part names (core/edits.js), kept by the beat they start on under a key of
    // the beats alone: a new analysis on the same beats (the bar lines moved) keeps them. As app.beats_key.
    const editsKey = fnv1a(JSON.stringify(meta.beats.map((t) => Math.floor(t * 1000 + 0.5))));
    const BEAT = /^(0|-?[1-9][0-9]{0,5})$/; // one spelling a beat, as app.py BEAT_INDEX
    const typedBars = W.keyed("woodshed:edits:" + editsKey + ":bars", (k, v) =>
      BEAT.test(k) && !!v && Array.isArray(v.chords) && v.chords.length > 0 &&
      v.chords.every((c) => Array.isArray(c) && Number.isInteger(c[0]) && c[0] > 0 && typeof c[1] === "string" && !W.chords.parse(c[1]).refused));
    const typedParts = W.keyed("woodshed:edits:" + editsKey + ":parts", (k, v) =>
      BEAT.test(k) && !!v && (v.join === true || (typeof v.name === "string" && v.name.trim().length > 0 && [...v.name].length <= 40)));
    typedBars.restore();
    typedParts.restore();
    // Beats are counted from the first bar's beat one in the page, from the first tracked beat in the store.
    const beatOfBar = (u) => String(meta.first_beat + u * song.per);
    function applyFixes() {
      song.bars.forEach((bar, u) => {
        bar.chords = original[u].map((c) => ({ ...c }));
      });
      for (const bar of song.bars) {
        for (const c of bar.chords) {
          const fix = c.doubt && fixes[c.doubt.id];
          if (fix) Object.assign(c, { pc: fix[0], quality: fix[1], fixed: true });
        }
        merge(bar);
      }
      // The bars the band typed, over the picks (core/edits.js): on their beats.
      const typed = W.edits.apply(song.bars, { bars: typedBars.values() }, meta.first_beat, song.per);
      typed.forEach((bar, u) => {
        song.bars[u].chords = bar.chords;
        song.bars[u].edited = !!bar.edited;
      });
      // The band's parts, and the chart's lines drawn again from them (a part always starts a line).
      editedParts = W.edits.applyParts((app.words && app.words.sections) || meta.sections, typedParts.values(), meta.first_beat, song.per, song.bars.length);
      if (editedParts) {
        const lines = W.structure.regroup(song.bars, editedParts);
        meta.groups = lines.groups;
        lines.fields.forEach((f, u) => Object.assign(song.bars[u], f));
      } else {
        meta.groups = JSON.parse(JSON.stringify(analysisGroups));
        analysisLines.forEach(([group, occurrence, column], u) => Object.assign(song.bars[u], { group, occurrence, column }));
      }
    }
    // Doubts taken back to the analysis on this device, until the band's library has them: a
    // device that was offline shares them when it comes back, and the library's copy of the old fix
    // does not bring it back meanwhile.
    // Each with the fix it took back, so the library's copy goes only if it is that same fix.
    let pendingRemovals = new Map();
    function saveCorrections() {
      try {
        localStorage.setItem(storageKey, JSON.stringify(fixes));
        localStorage.setItem(storageKey + ":removed", JSON.stringify(Object.fromEntries(pendingRemovals)));
      } catch (err) {
        /* private mode or storage off: the correction still applies to this visit */
      }
    }
    // Only fixes of this analysis's doubts, as this version writes them: anything else is ignored,
    // the page must open whatever is stored (in this browser, or by the band in the library).
    function validFixes(stored) {
      const out = {};
      if (!stored || typeof stored !== "object" || Array.isArray(stored)) return out;
      const ids = analysedDoubts;
      for (const [id, fix] of Object.entries(stored)) {
        const valid = ids.has(id) && Array.isArray(fix) && Number.isInteger(fix[0]) && fix[0] >= 0 && fix[0] <= 11 && QUALITIES.has(fix[1]);
        if (valid) out[id] = [fix[0], fix[1]];
      }
      return out;
    }
    function restoreCorrections() {
      let stored = {};
      try {
        stored = JSON.parse(localStorage.getItem(storageKey) || "{}");
      } catch (err) {
        stored = {};
      }
      fixes = validFixes(stored);
      try {
        const removed = JSON.parse(localStorage.getItem(storageKey + ":removed") || "{}");
        // Only this analysis's doubts, each with a fix as this version writes them: a damaged entry
        // would make the library refuse every share.
        const ids = analysedDoubts;
        const was = validFixes(removed);
        pendingRemovals = new Map(
          Object.keys(removed && typeof removed === "object" && !Array.isArray(removed) ? removed : {})
            .filter((id) => ids.has(id))
            .slice(0, 2000)
            .map((id) => [id, was[id] || null]),
        );
      } catch (err) {
        pendingRemovals = new Map();
      }
      applyFixes();
    }
    // The band's corrections (views/band.js, when the page is served by woodshed app): the analysis
    // they belong to, the ones this device has, and taking the band's.
    app.fixesKey = storageKey.split(":").pop();
    app.fixes = () => ({ ...fixes });
    app.pendingRemovals = () => new Map(pendingRemovals);
    // The library has these removals: nothing left to share for them.
    app.removalsHeard = (ids) => {
      const before = pendingRemovals.size;
      for (const id of ids) pendingRemovals.delete(String(id));
      if (pendingRemovals.size !== before) saveCorrections();
    };
    app.useFixes = (stored) => {
      const next = validFixes(stored);
      if (JSON.stringify(next) === JSON.stringify(fixes)) return; // nothing new: no redraw
      fixes = next;
      applyFixes();
      saveCorrections();
      store.set({ corrections: store.get().corrections + 1 });
    };
    // The chord the analysis gave a doubt, before any correction.
    app.analysedChord = (id) => {
      for (const bar of original) for (const c of bar) if (c.doubt && c.doubt.id === id) return c;
      return null;
    };
    // A correction taken back: the chord is the analysis's again, with its doubt to check by ear.
    app.uncorrect = function uncorrect(id) {
      const analysed = app.analysedChord(id);
      pendingRemovals.set(String(id), fixes[id] || null); // doubt ids are keys: strings, as the library sends them
      delete fixes[id];
      applyFixes();
      saveCorrections();
      popups.closeAll(true);
      store.set({ corrections: store.get().corrections + 1 });
      const shared = app.shareFixes ? app.shareFixes({ [id]: null }) : false;
      if (!app.shareFixes) app.removalsHeard([id]); // opened from disk: this browser was all there was
      // The keyboard back on the chord taken back (the pop that held it is gone).
      const u = original.findIndex((bar) => bar.some((c) => c.doubt && String(c.doubt.id) === String(id)));
      const back = document.querySelector('.doubt[data-ref^="' + u + '_"]:not(.fixed)');
      if (back && (document.activeElement === document.body || !document.activeElement)) back.focus({ preventScroll: true });
      const where = shared ? W.t("The band sees it on every device.") : W.t("This browser remembers it for this song.");
      app.toast(W.t("Back to the analysis: {chord}. {where}", { chord: analysed ? W.prettyText(app.nameFor(analysed, 0, store.get())) : "", where }));
    };
    app.correct = function correct(u, k, alt) {
      const c = song.bars[u].chords[k];
      fixes[c.doubt.id] = [alt.pc, alt.quality];
      pendingRemovals.delete(c.doubt.id);
      applyFixes();
      saveCorrections();
      popups.closeAll();
      store.set({ corrections: store.get().corrections + 1 });
      const shared = app.shareFixes ? app.shareFixes(fixes) : false;
      const where = shared ? W.t("The band sees it on every device.") : W.t("This browser remembers it for this song.");
      app.toast(W.t("Saved: {chord}. {where}", { chord: W.prettyText(app.nameFor(alt, 0, store.get())), where }));
    };

    restoreCorrections();

    // Typing the chords of bars (the bar editor): stored, applied, and shared with the band when served.
    app.editsKey = editsKey;
    app.typedBars = typedBars;
    app.typedParts = typedParts;
    function editsChanged(change) {
      applyFixes();
      store.set({ corrections: store.get().corrections + 1 });
      return app.shareEdits ? app.shareEdits(change) : false;
    }
    // A part's name, typed at the start of bar u (renaming the part there, or starting one); a join of
    // the part starting at bar u to the one before; the parts back to the analysis.
    app.namePart = (u, name) => {
      const entry = { name: String(name).replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, "").trim() };
      entry.name = Array.from(entry.name).slice(0, 40).join(""); // 40 characters as Python counts them, an emoji never cut in half
      if (!entry.name) return false;
      typedParts.set(beatOfBar(u), entry);
      return editsChanged({ parts: { [beatOfBar(u)]: entry } });
    };
    app.joinPart = (u) => {
      typedParts.set(beatOfBar(u), { join: true });
      return editsChanged({ parts: { [beatOfBar(u)]: { join: true } } });
    };
    // The parts back to the analysis; the function returned puts back what nobody typed again meanwhile.
    app.untypeParts = () => {
      const parts = typedParts.values();
      const keys = Object.keys(parts);
      for (const k of keys) typedParts.take(k);
      if (!app.shareEdits) typedParts.heard(keys);
      editsChanged({ parts: Object.fromEntries(keys.map((k) => [k, null])) });
      return () => {
        const back = {};
        for (const [k, v] of Object.entries(parts)) if (typedParts.get(k) === undefined) typedParts.set(k, (back[k] = v));
        editsChanged({ parts: back });
      };
    };
    // The chords typed on bar u, as [[beats, label]], or null.
    app.typedBar = (u) => {
      const entry = typedBars.get(beatOfBar(u));
      return entry ? entry.chords.map(([n, l]) => [n, l]) : null;
    };
    // chords: [[beats, label]] for bar u, and the same on the bars in `also` (the line played again).
    app.typeBars = (us, chords) => {
      const change = {};
      for (const u of us) {
        const entry = { chords: chords.map(([n, l]) => [n, l]), t: Math.round(song.beatTime(u * song.per) * 1000) / 1000 };
        typedBars.set(beatOfBar(u), entry);
        change[beatOfBar(u)] = entry;
      }
      return editsChanged({ bars: change });
    };
    // Back to the analysis for bar u: every typed span that starts on one of its beats.
    app.untypeBar = (u) => {
      const first = meta.first_beat + u * song.per;
      // Every typed span over a beat of this bar (one typed before the bar lines moved may start in the bar before).
      const spans = typedBars.values();
      const keys = Object.keys(spans).filter((k) => {
        const len = spans[k].chords.reduce((n, [b]) => n + b, 0);
        return Number(k) < first + song.per && Number(k) + len > first;
      });
      for (const k of keys) typedBars.take(k);
      if (!app.shareEdits) typedBars.heard(keys); // opened from disk: this browser was all there was
      return editsChanged({ bars: Object.fromEntries(keys.map((k) => [k, null])) });
    };
    // The band's copy of the typed bars and parts (views/band.js): what this device still has to share.
    // Everything typed taken back at once; the function returned puts it all back (the toast's Undo).
    app.untypeAll = () => {
      const bars = typedBars.values();
      const parts = typedParts.values();
      typedBars.clear();
      typedParts.clear();
      if (!app.shareEdits) {
        typedBars.heard(Object.keys(bars));
        typedParts.heard(Object.keys(parts));
      }
      const none = (o) => Object.fromEntries(Object.keys(o).map((k) => [k, null]));
      editsChanged({ bars: none(bars), parts: none(parts) });
      // Undo puts back only what nobody typed again meanwhile (the band's newer change stays).
      return () => {
        const back = { bars: {}, parts: {} };
        for (const [k, v] of Object.entries(bars)) if (typedBars.get(k) === undefined) typedBars.set(k, (back.bars[k] = v));
        for (const [k, v] of Object.entries(parts)) if (typedParts.get(k) === undefined) typedParts.set(k, (back.parts[k] = v));
        editsChanged(back);
      };
    };
    // `quiet`: the first read when the page opens, nothing to announce.
    app.useEdits = (edits, quiet) => {
      const before = typedBars.values();
      const bars = typedBars.merge(edits.bars, edits.removed_bars);
      const parts = typedParts.merge(edits.parts, edits.removed_parts);
      if (bars.changed || parts.changed) {
        applyFixes();
        store.set({ corrections: store.get().corrections + 1 });
        const after = typedBars.values();
        const moved = [...new Set([...Object.keys(before), ...Object.keys(after)])]
          .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
          .map((k) => Math.floor((Number(k) - meta.first_beat) / song.per) + 1)
          .sort((a, b) => a - b);
        if (!quiet && moved.length === 1) app.toast(W.t("Bar {n} changed on another device.", { n: moved[0] }));
        else if (!quiet && moved.length) app.toast(W.t("{n} bars changed on another device.", { n: moved.length }));
        else if (!quiet && parts.changed) app.toast(W.t("The parts changed on another device."));
      }
      return { bars: bars.share, parts: parts.share };
    };

    // One pending "stop after these bars" at a time; any play, pause or new preview cancels it.
    let oneShot = 0;
    app.cancelTimers = () => {
      clearTimeout(oneShot);
      oneShot = 0;
    };

    // Previews with the sampled instruments.
    const guitarMidi = (shape, capo) => I.fingeredMidi(shape, capo);
    app.hearShape = (shape, capo) => {
      const midis = guitarMidi(shape, capo);
      sounds.play(["guitar"], { guitar: midis }, (t) => sounds.strum("guitar", midis, t, 2.2, 0.55, false, 0.03));
    };
    const keysSound = () => (store.get().chordSound === "rhodes" ? "rhodes" : "piano");
    app.hearKeys = (c) => {
      const inst = keysSound();
      const midis = I.keysMidi(c.pc + store.get().transpose, c.quality, true, I.bassOf(c, store.get().transpose));
      sounds.play([inst], { [inst]: midis }, (t) => midis.forEach((m) => sounds.note(inst, m, t, 2.4, 0.5, null, 0.3)));
    };
    // The notes heard on the record in bar u, over the chord's root.
    app.hearVoicing = (u) => {
      const s = store.get();
      const inst = keysSound();
      const root = song.chordAtBeat(u * song.per);
      const pcs = (song.parts && song.parts.voicings[u]) || [];
      const midis = [...(root.pc >= 0 ? [48 + ((root.pc + s.transpose + 120) % 12)] : []), ...pcs.map((pc) => 60 + ((pc + s.transpose + 120) % 12))];
      sounds.play([inst], { [inst]: midis }, (t) => midis.forEach((m) => sounds.note(inst, m, t, 2.4, 0.45, null, 0.3)));
    };
    // Bars u to u+n-1 of the recording, on the current track, then stop.
    app.playBars = async (u, n) => {
      const s = store.get();
      app.seekBar(u);
      const seconds = (barStart(u + n) - barStart(u)) / (s.bpm / songBpm);
      app.cancelTimers();
      if (await transport.play()) {
        store.set({ playing: true });
        // Stop on the recording's own time: the sound starts a little after play() returns, a
        // timer alone cut the last beat short.
        const end = barStart(u + n);
        const stop = () => {
          const left = (end - transport.time) / (s.bpm / songBpm);
          if (left > 0.03 && transport.playing) {
            oneShot = setTimeout(stop, left * 1000);
            return;
          }
          transport.pause();
          store.set({ playing: false });
        };
        oneShot = setTimeout(stop, seconds * 1000);
      }
    };
    app.hearArpeggio = (c) => {
      const inst = keysSound();
      const midis = I.keysMidi(c.pc + store.get().transpose, c.quality, true, I.bassOf(c, store.get().transpose));
      sounds.play([inst], { [inst]: midis }, (t) => midis.forEach((m, i) => sounds.note(inst, m, t + i * 0.42, 1.3, 0.55, null, 0.3)));
    };
    app.hearRiff = (u) => {
      const s = store.get();
      const line = (song.parts.bass[u] || []).map((e) => (e ? e[0] + s.transpose : null));
      const sixteenth = 60 / s.bpm / 4;
      sounds.play(["bass"], { bass: line.filter((m) => m !== null) }, (t) => {
        line.forEach((m, i) => {
          if (m === null) return;
          let len = 1;
          while (i + len < line.length && line[i + len] === null && len < 4) len++;
          sounds.note("bass", m, t + i * sixteenth, sixteenth * len * 0.92, 1, null, 0.05);
        });
      });
    };
    app.hearGroove = () => {
      const g = song.parts.groove;
      const hits = I.grooveHits(g);
      const sixteenth = 60 / store.get().bpm / 4;
      sounds.play(["drums"], { drums: [36, 38, 42] }, (t) => {
        for (let rep = 0; rep < 2; rep++) {
          g.kick.forEach((_, i) => {
            const at = t + (rep * g.kick.length + i) * sixteenth;
            if (hits.kick[i]) sounds.note("drums", 36, at, 0.3, 0.95);
            if (hits.snare[i]) sounds.note("drums", 38, at, 0.4, 0.8);
            if (hits.hat[i]) sounds.note("drums", 42, at, 0.12, 0.12 + 0.3 * g.hat[i]);
          });
        }
      });
    };
    // This bar of the recording, once (the bar editor checks typed chords against it).
    app.playBar = (u) => {
      if (following()) return leaderMoves();
      transport.pause();
      app.seekBar(u);
      transport.play();
      store.set({ playing: true });
      app.cancelTimers();
      oneShot = setTimeout(() => {
        transport.pause();
        store.set({ playing: false });
      }, (song.beatTime((u + 1) * song.per) - song.beatTime(u * song.per)) * 1000 * (song.song.bpm / store.get().bpm) + 100);
    };
    // This bar of the recording in a loop, while the bar editor's button is held; then as it was.
    let loopBefore = null;
    app.loopBar = (u) => {
      if (following()) return leaderMoves();
      const s = store.get();
      loopBefore = { loop: s.loop, loopOn: s.loopOn };
      app.cancelTimers();
      setLoop([u, u], true);
      app.seekBar(u);
      if (!store.get().playing) app.togglePlay();
    };
    app.stopBarLoop = () => {
      if (!loopBefore) return;
      if (store.get().playing) app.togglePlay();
      setLoop(loopBefore.loop, loopBefore.loopOn);
      loopBefore = null;
    };
    // A candidate chord, strummed softly on each beat over this bar of the recording.
    app.audition = (u, alt) => {
      if (following()) return leaderMoves(); // it plays the recording under the candidate
      const s = store.get();
      const guitar = s.chordSound === "guitar";
      const inst = guitar ? "guitar" : keysSound();
      const midis = guitar ? I.fingeredMidi(I.openOrBarre(song.view.shapes, alt.pc + s.transpose, alt.quality, I.bassOf(alt, s.transpose)), 0) : I.keysMidi(alt.pc + s.transpose, alt.quality, false, I.bassOf(alt, s.transpose));
      const beat = 60 / s.bpm;
      sounds.play([inst], { [inst]: midis }, (t) => {
        transport.pause();
        app.seekBar(u);
        transport.play();
        for (let i = 0; i < song.per; i++) {
          if (guitar) sounds.strum("guitar", midis, t + i * beat, beat * 0.9, 0.35, i % 2 === 1, 0.015);
          else midis.forEach((m) => sounds.note(inst, m, t + i * beat, beat * 0.9, 0.3, null, 0.1));
        }
        app.cancelTimers();
        oneShot = setTimeout(() => {
          transport.pause();
          store.set({ playing: false });
        }, song.per * beat * 1000 + 100);
      });
    };

    // Drum notation, drawn by VexFlow (loaded on first use).
    app.drawDrumStaff = function drawDrumStaff() {
      const box = $("drumStaff");
      const g = song.parts && song.parts.groove;
      if (!box || !g) return;
      const hits = I.grooveHits(g);
      if (!window.Vex || !window.Vex.Flow) {
        W.clear(box, h("p", { class: "hint", style: { margin: "6px" } }, W.t("Drawing the notation…")));
        const el = document.createElement("script");
        el.src = "assets/vendor/vexflow-4.2.2-bravura.js";
        el.onload = drawDrumStaff;
        el.onerror = () => W.clear(box, h("p", { class: "hint" }, W.t("The notation could not be drawn. The grid below shows the same groove.")));
        document.head.appendChild(el);
        return;
      }
      const VF = window.Vex.Flow;
      const w = Math.max(300, Math.min(520, box.clientWidth - 12));
      const hands = [];
      const feet = [];
      for (let i = 0; i < 16; i++) {
        const k = [];
        if (hits.hat[i]) k.push("g/5/x2");
        if (hits.snare[i]) k.push("c/5");
        hands.push(k);
        feet.push(hits.kick[i] ? ["f/4"] : []);
      }
      const voice = (slots, dir) => {
        const notes = [];
        const n = (keys, d) => new VF.StaveNote({ keys: keys.length ? keys : [dir > 0 ? "b/4" : "f/4"], duration: keys.length ? d : d + "r", stem_direction: dir });
        for (let b = 0; b < 4; b++) {
          const sl = slots.slice(b * 4, b * 4 + 4);
          if (!sl[1].length && !sl[2].length && !sl[3].length) {
            notes.push(n(sl[0], "q"));
            continue;
          }
          for (let half = 0; half < 2; half++) {
            const a = sl[half * 2];
            const c = sl[half * 2 + 1];
            if (!c.length) notes.push(n(a, "8"));
            else notes.push(n(a, "16"), n(c, "16"));
          }
        }
        return notes;
      };
      try {
        W.clear(box);
        const r = new VF.Renderer(box, VF.Renderer.Backends.SVG);
        r.resize(w, 130);
        const ctx = r.getContext();
        const stave = new VF.Stave(4, 14, w - 10);
        stave.addClef("percussion").addTimeSignature("4/4").setContext(ctx).draw();
        const up = voice(hands, 1);
        const down = voice(feet, -1);
        const v1 = new VF.Voice({ num_beats: 4, beat_value: 4 }).addTickables(up);
        const v2 = new VF.Voice({ num_beats: 4, beat_value: 4 }).addTickables(down);
        const beams = VF.Beam.generateBeams(up, { stem_direction: 1 }).concat(VF.Beam.generateBeams(down, { stem_direction: -1 }));
        new VF.Formatter().joinVoices([v1, v2]).format([v1, v2], w - 110);
        v1.draw(ctx, stave);
        v2.draw(ctx, stave);
        beams.forEach((b) => b.setContext(ctx).draw());
        // Follow the page theme: VexFlow draws in fixed black and grey.
        box.querySelectorAll("[fill], [stroke]").forEach((el) => {
          for (const attr of ["fill", "stroke"]) if (/^(black|#000000|#999999)$/.test(el.getAttribute(attr) || "")) el.setAttribute(attr, "currentColor");
        });
      } catch (err) {
        W.clear(box, h("p", { class: "hint" }, W.t("The notation could not be drawn. The grid below shows the same groove.")));
      }
    };

    app.setStage = (on, full) => setStage(on, full);
    const words = W.views.words(app);
    app.openWords = () => words.open();
    W.views.barLines(app);
    const views = [W.views.header(app), W.views.chart(app), W.views.desk(app), W.views.dock(app), W.views.stage(app), W.views.band(app)];
    const chart = views[1];
    app.chart = chart; // its bars, for the tests and the console
    const editor = W.views.editor(app, chart);
    views.push(editor);
    app.editor = editor;
    // The instrument on the page itself: a phone's layout follows it (the singer: words first).
    const mark = (s) => {
      document.body.dataset.inst = s.inst;
      document.body.dataset.sheet = app.sheetMode(s);
    };
    mark(store.get());
    store.on((s, changed) => {
      if (changed.has("inst") || changed.has("sheet") || changed.has("editing")) mark(s);
    });
    const dock = views[3];
    for (const v of views) v.render(store.get());

    // Awake on the music stand (spec 008): while following, leading or on stage. Said only when the
    // phone may lock: under the Follow banner a line worded for its system, else a toast once.
    const awakeLine = $("awakeLine");
    const stored = (key) => {
      try {
        return localStorage.getItem(key);
      } catch (err) {
        return null;
      }
    };
    const keep = (key) => {
      try {
        localStorage.setItem(key, "1");
      } catch (err) {
        /* this visit only */
      }
    };
    let cameBack = false; // the page was hidden while a mode was on: the screen probably locked
    let sayTimer = 0;
    const awake = W.createAwake(() => {
      if (awake && awake.locked() && !document.hidden) cameBack = false; // the Wake Lock again: nothing to fear
      clearTimeout(sayTimer);
      sayTimer = setTimeout(sayAwake, 1500); // a lock or a video takes a moment: no line that flickers
    });
    const bandMode = () => (W.band ? W.band.mode() : "alone");
    function screenAdvice() {
      const ua = navigator.userAgent;
      if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return W.t("Screen locking? Settings → Display & Brightness → Auto-Lock → Never.");
      if (/Android/.test(ua)) return W.t("Screen going dark? Settings → Screen timeout → the longest.");
      return W.t("Screen locking? Turn off its sleep while you play.");
    }
    function sayAwake() {
      const mode = bandMode();
      const atRisk = awake.wanted() && (!awake.holding() || cameBack);
      const line = mode === "follow" && atRisk && !stored("woodshed:awakeLineClosed");
      if (mode !== "follow") cameBack = false;
      if (line && (awakeLine.hidden || awakeLine.lang !== W.lang())) {
        awakeLine.lang = W.lang(); // said again in the other language
        W.clear(awakeLine, h("span", null, screenAdvice()), h("button", {
          type: "button", "aria-label": W.t("Close"), "data-testid": "awake-close",
          onclick: () => {
            keep("woodshed:awakeLineClosed");
            awakeLine.hidden = true;
          },
        }, "✕"));
      }
      awakeLine.hidden = !line;
      // Leading or on stage: a toast, once per device, never over another one.
      if (mode !== "follow" && atRisk && !stored("woodshed:awakeTold")) {
        if (!$("toast").hidden) {
          clearTimeout(sayTimer);
          sayTimer = setTimeout(sayAwake, 3000); // another toast is being read: after it
          return;
        }
        app.toast(screenAdvice());
        keep("woodshed:awakeTold");
      }
    }
    app.awakeCheck = () => {
      awake.want(bandMode() !== "alone" || !!store.get().stage);
      sayAwake();
    };
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && awake.wanted()) cameBack = true;
      else if (!document.hidden) setTimeout(sayAwake, 300);
    });
    store.on((s, changed) => changed.has("stage") && app.awakeCheck());
    app.awakeCheck();
    W.awake = awake;

    // The other language, chosen while playing: every view says it again, the music goes on.
    W.onLang.push(() => {
      $("toast").hidden = true; // said in the other language
      for (const v of views) v.render(store.get());
      words.relabel();
      renderExports();
      renderMore();
      renderStagePlay(store.get());
      sayAwake();
    });

    // Input.
    let drag = null;
    const BARS = ".bar:not(.empty), .lline .nb[data-bar]"; // the grid's bars, the sung bars of the Lyrics view
    document.addEventListener("pointerdown", (e) => {
      if (store.get().editing && e.target.closest("#sheet")) return; // a bar opens its editor (the click)
      if (e.target.closest(".doubt")) return;
      const el = e.target.closest(BARS);
      if (!el) return;
      if (following()) return e.target.closest("[data-seek]") ? undefined : leaderMoves(); // a word: its click says it
      const u = chart.barFromEl(el);
      // A press on a word seeks to the word (the click), unless it becomes a drag over bars.
      drag = { start: u, end: u, word: !!e.target.closest("[data-seek]") };
    });
    document.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      const el = hit && hit.closest(BARS);
      if (!el) return;
      drag.end = chart.barFromEl(el);
      if (drag.end !== drag.start) setLoop([Math.min(drag.start, drag.end), Math.max(drag.start, drag.end)], true);
    });
    document.addEventListener("pointerup", () => {
      if (!drag) return;
      if (drag.end === drag.start) {
        if (!drag.word) app.seekBar(drag.start);
      } else {
        const l = store.get().loop;
        app.toast(W.t("Looping bars {from}–{to}. Press play.", { from: l[0] + 1, to: l[1] + 1 }));
        app.seekBar(l[0]);
      }
      drag = null;
    });
    document.addEventListener("pointercancel", () => (drag = null)); // a touch that became a scroll
    document.addEventListener("click", (e) => {
      // Editing the chart: a bar, or the chord to check in it, opens the bar editor.
      const typedAt = store.get().editing && e.target.closest("#sheet") && e.target.closest(BARS);
      if (typedAt) {
        e.stopPropagation();
        popups.closeAll();
        editor.openBar(chart.barFromEl(typedAt), typedAt);
        return;
      }
      const d = e.target.closest(".doubt");
      if (d) {
        e.stopPropagation();
        popups.openDoubt(d);
        return;
      }
      if (!e.target.closest("#pop") && !e.target.closest(".menu") && !e.target.closest("[data-menu-anchor]")) popups.closeAll();
      const word = e.target.closest("[data-seek]");
      if (word) {
        app.seekTime(+word.getAttribute("data-seek"));
        // A line's time says "Play from 0:52": it plays from there; a word only moves there.
        if (word.classList.contains("t") && !store.get().playing && !following()) app.togglePlay();
        return;
      }
      const loop = e.target.closest("[data-loop]");
      if (loop) {
        app.loopSection(+loop.getAttribute("data-loop"));
        return;
      }
      const go = e.target.closest("[data-goto]");
      if (go) {
        const u = +go.getAttribute("data-goto");
        app.seekBar(u);
        const el = chart.barEl(u);
        if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    });
    document.addEventListener("keydown", (e) => {
      const tag = e.target.tagName;
      if (e.target.closest && e.target.closest("dialog[open]")) return; // a dialog's keys are its own (Escape closes it)
      if (e.target.closest && e.target.closest("#barEd")) return; // the bar editor's too (its buttons, its field)
      if (e.key === "Escape") {
        popups.closeAll(true);
        if (store.get().stage) setStage(false);
        return;
      }
      const bar = e.target.closest && e.target.closest(".bar");
      if (bar && e.target === bar && e.key === "Enter") {
        e.preventDefault();
        if (store.get().editing) editor.openBar(chart.barFromEl(bar), bar);
        else app.seekBar(chart.barFromEl(bar));
        return;
      }
      if (tag === "INPUT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key;
      // Held keys repeat: toggles react to the first press only (a pedal held down must not flicker).
      if (e.repeat && [" ", "l", "L", "s", "S", "?"].includes(k)) {
        if (k === " ") e.preventDefault();
        return;
      }
      // Space plays or pauses, whatever button has the focus (a page-turner pedal sends Space, and a
      // click on Trainer must not make Space toggle it); in a menu, the doubt pop or on the language
      // and theme buttons it presses the button, as a keyboard user expects there.
      if (k === " " && !e.target.closest(".menu, #pop, .prefs")) {
        e.preventDefault();
        app.togglePlay();
      } else if (k === "ArrowRight" || k === "PageDown") {
        e.preventDefault();
        // The pedal at the end of a song, in stage mode: on to the next song of the set.
        const end = curBar() >= song.bars.length - 1 && !store.get().playing;
        if (store.get().stage && end && app.nextSong && app.nextSong()) return;
        app.seekBar(curBar() + 1);
      } else if (k === "ArrowLeft" || k === "PageUp") {
        e.preventDefault();
        app.seekBar(curBar() - 1);
      } else if (k === "l" || k === "L") $("loopBtn").click();
      else if (k === "[") setBpm(store.get().bpm - 5);
      else if (k === "]") setBpm(store.get().bpm + 5);
      else if (k === "s" || k === "S") setStage(!store.get().stage);
      else if ((k === "n" || k === "N") && app.nextSong) app.nextSong();
      else if (k >= "1" && k <= "4") app.setStep(+k);
      else if (k === "?") popups.openMenu("helpMenu", $("helpBtn"));
    });

    $("wave").addEventListener("click", (e) => (following() ? leaderMoves() : transport.seek(dock.timeAt(e.clientX))));
    $("playBtn").addEventListener("click", () => app.togglePlay());
    $("loopBtn").addEventListener("click", () => {
      if (following()) return leaderMoves();
      const s = store.get();
      setLoop(s.loop || lineOf(curBar()), !s.loopOn);
    });
    $("trainBtn").addEventListener("click", () => {
      if (following()) return leaderMoves();
      const s = store.get();
      const on = !s.trainer;
      store.set({ trainer: on });
      if (on && s.bpm >= songBpm) setBpm(Math.round(songBpm * 0.7));
      if (on && !s.loopOn) setLoop(s.loop || lineOf(curBar()), true);
      app.toast(on ? W.t("Trainer on: {bpm} BPM, +5 BPM each loop up to {max}.", { bpm: store.get().bpm, max: songBpm }) : W.t("Trainer off."));
    });
    $("countBtn").addEventListener("click", () => store.set({ countIn: !store.get().countIn }));
    $("clickBtn").addEventListener("click", () => {
      const on = !store.get().click;
      store.set({ click: on });
      if (on) sounds.play(["drums"], { drums: [37] }, () => {}); // load the click before it is needed
    });
    // While playing: a click on each beat (scheduled ahead, on the audio clock) and the sixteenth
    // lit in the rhythm grids.
    let ticked = -1;
    let lit = -1;
    store.on((s, changed) => {
      if (!s.playing || !changed.has("time") || following()) return;
      const b = s.beat;
      // The next beat to click: beat one of the first bar while the intro plays, else the one after b.
      const next = s.time < song.beatTime(0) ? 0 : b + 1;
      if (s.click && next !== ticked && sounds.loaded("drums")) {
        ticked = next;
        const rate = s.bpm / songBpm;
        sounds.tick((song.beatTime(next) - transport.time) / rate, next % song.per === 0);
      }
      const t0 = song.beatTime(b);
      const t1 = song.beatTime(b + 1);
      const frac = t1 > t0 ? Math.min(0.999, Math.max(0, (s.time - t0) / (t1 - t0))) : 0;
      const six = (b % song.per) * 4 + Math.floor(frac * 4);
      if (six !== lit) {
        lit = six;
        document.querySelectorAll("#grooveGrid .cell, #compGrid .cell").forEach((c) => c.classList.toggle("now", +c.getAttribute("data-six") === six));
      }
    });
    $("bpm").addEventListener("input", (e) => setBpm(+e.target.value));
    $("bpmUp").addEventListener("click", () => setBpm(store.get().bpm + 1));
    $("bpmDown").addEventListener("click", () => setBpm(store.get().bpm - 1));
    $("bpmReset").addEventListener("click", () => setBpm(songBpm));
    $("trUp").addEventListener("click", () => app.transposeTo(store.get().transpose + 1));
    $("trDown").addEventListener("click", () => app.transposeTo(store.get().transpose - 1));
    $("capoUp").addEventListener("click", () => store.set({ capo: Math.min(7, store.get().capo + 1) }));
    $("capoDown").addEventListener("click", () => store.set({ capo: Math.max(0, store.get().capo - 1) }));
    // Export: every format made here, with your corrections.
    const stem = (meta.file.replace(/\.[^.]*$/, "") || "song").replace(/[<>:"/\\|?*]/g, "_");
    const item = (label, detail, attrs) => h("button", { type: "button", class: "item", ...attrs }, h("span", null, label), h("small", null, detail));
    // Format names are names: ChordPro, JSON, MIDI and MusicXML are not translated.
    function renderExports() {
      W.clear(
        $("exportItems"),
        item("ChordPro", W.t("With your corrections, in the key shown, and the words when they are placed. Opens in OnSong, SongbookPro and other songbook apps"), {
          "data-testid": "export-chordpro", onclick: () => W.exports.save(stem + ".cho", W.exports.chordpro(song, app.words, store.get().transpose), "text/plain"),
        }),
        item(W.t("Chord timeline (.lab)"), W.t("With your corrections. Start, end and chord, for analysis tools"), {
          "data-testid": "export-lab", onclick: () => W.exports.save(stem + ".lab", W.exports.lab(song), "text/plain"),
        }),
        item("JSON", W.t("With your corrections. The whole analysis, for developers"), {
          "data-testid": "export-json", onclick: () => W.exports.save(stem + ".json", W.exports.json(song), "application/json"),
        }),
        item("MIDI", W.t("With your corrections. Chords, bass and drums, for a sequencer or a DAW"), {
          "data-testid": "export-midi", onclick: () => W.exports.save(stem + ".mid", W.exports.midi(song), "audio/midi"),
        }),
        item("MusicXML", W.t("With your corrections. Chord symbols and bass line, for MuseScore"), {
          "data-testid": "export-musicxml", onclick: () => W.exports.save(stem + ".musicxml", W.exports.musicxml(song), "application/vnd.recordare.musicxml+xml"),
        }),
        item(W.t("Print the chart"), W.t("The chart for the music stand, without the screen's buttons"), { "data-testid": "export-print", onclick: () => window.print() }),
      );
    }
    renderExports();

    for (const [button, menu] of [["mixBtn", "mixMenu"], ["helpBtn", "helpMenu"], ["exportBtn", "exportMenu"]]) {
      const anchor = $(button);
      anchor.setAttribute("data-menu-anchor", "1");
      anchor.addEventListener("click", (e) => {
        e.stopPropagation();
        popups.openMenu(menu, anchor);
      });
    }
    function renderMore() {
      $("moreBtn").textContent = $("dock").classList.contains("open") ? W.t("Hide") : W.t("Controls");
    }
    $("moreBtn").addEventListener("click", function () {
      const open = $("dock").classList.toggle("open");
      this.setAttribute("aria-expanded", String(open));
      renderMore();
    });

    // Full screen needs a gesture: a stage carried over from the previous song shows without it.
    function setStage(on, full = true) {
      store.set({ stage: on });
      if (on && full) {
        try {
          const p = $("stage").requestFullscreen && $("stage").requestFullscreen();
          if (p && p.catch) p.catch(() => {});
        } catch (err) {
          /* full screen refused: the stage still covers the page */
        }
      } else if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    }
    $("stageBtn").addEventListener("click", () => setStage(true));
    $("stageExit").addEventListener("click", () => setStage(false));
    // The stage's own controls: a tablet on the stand has no keyboard. A tapped button lets go of
    // the focus, and Space released on a stage button does nothing more: a pedal (it sends Space)
    // must not press the button again (Firefox clicks a button when Space is released).
    const tapped = (act) => (e) => {
      if (e.detail > 0) e.currentTarget.blur();
      act();
    };
    $("stPrev").addEventListener("click", tapped(() => app.prevPart()));
    $("stPlay").addEventListener("click", tapped(() => app.togglePlay()));
    $("stNextPart").addEventListener("click", tapped(() => app.nextPart()));
    // Firefox presses a focused button when Space is released: Space played or paused already.
    document.addEventListener("keyup", (e) => {
      const button = e.key === " " && e.target.closest && e.target.closest("button");
      if (button && !button.closest(".menu, #pop, #barEd, dialog, .prefs")) e.preventDefault();
    });
    function renderStagePlay(s) {
      $("stPlay").textContent = s.playing ? "❚❚" : "▶\ufe0e"; // text, not an emoji, on phones
      $("stPlay").setAttribute("aria-label", s.playing ? W.t("Pause") : W.t("Play"));
    }
    store.on((s, changed) => {
      if (changed.has("playing") || changed.has("stage")) renderStagePlay(s);
    });
    document.addEventListener("fullscreenchange", () => {
      if (!document.fullscreenElement && store.get().stage) setStage(false);
    });
    let spoken = "";
    store.on((s, changed) => {
      if (!changed.has("beat") && !changed.has("transpose")) return;
      const name = app.nameFor(song.chordAtBeat(s.beat), 0, s);
      if (name !== spoken) $("srChord").textContent = spoken = name; // screen readers: once per chord
    });
    if (window.ResizeObserver) {
      new ResizeObserver(() => {
        $("wrap").style.paddingBottom = $("dock").offsetHeight + 24 + "px";
        document.documentElement.style.setProperty("--dock-h", $("dock").offsetHeight + "px");
      }).observe($("dock"));
    }

    // A read-only view of the state, for tests and for curious users.
    W.debug = () => ({ ...store.get(), track: transport.track, audioTime: transport.time });
    W.ready = true;
  }

  try {
    start();
  } catch (err) {
    document.body.prepend(W.h("p", { class: "fatal", role: "alert" }, String(err.message || err)));
    throw err;
  }
})();

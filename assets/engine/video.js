/* Renderer for lesson videos built from SLIDE IMAGES (1920x1080 PNG) + storyboard.json + timeline.json.
 *
 * Every frame is a pure function of time t (seconds): window.__render(t) draws exactly the frame at t, so render.mjs
 * can screenshot each frame with headless Chrome and pipe it to ffmpeg, and seeking back and forth always gives the
 * same picture.
 *
 * Data: window.__DATA = { board: storyboard.json, tl: timeline.json, base: 'file:///.../videos/<course>/<lesson>/' }
 * Preview in a browser: open video.html?board=<storyboard.json>&tl=<timeline.json> (or &fake=3 without a timeline), press Space.
 *
 * Motion rules (references/motion-and-sound.md): entrances 0.45-0.8 s with ease-out (0.16,1,0.3,1); exits about half
 * as long with ease-in (0.6,0,0.9,0.35); 0.2-0.25 s stagger between cards; text being read never moves; no spins or
 * flips; nothing stands still for more than 25 s.
 */
(() => {
  'use strict';
  const W = 1920, H = 1080;
  const Q = new URLSearchParams(location.search);
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const bez = (x1, y1, x2, y2) => u => {
    if (u <= 0) return 0; if (u >= 1) return 1;
    const f = (a, b, s) => 3 * a * s * (1 - s) * (1 - s) + 3 * b * s * s * (1 - s) + s * s * s;
    let lo = 0, hi = 1, s = u;
    for (let i = 0; i < 22; i++) { s = (lo + hi) / 2; if (f(x1, x2, s) < u) lo = s; else hi = s; }
    return f(y1, y2, s);
  };
  const eIn = bez(.16, 1, .3, 1);        // arriving (ease-out expo)
  const eOut = bez(.6, 0, .9, .35);      // leaving (ease-in)
  const eIO = bez(.65, 0, .35, 1);       // moving between two states
  const eBack = u => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(u - 1, 3) + c1 * Math.pow(u - 1, 2); };
  const STAGGER = 0.22;
  const REVEAL_DUR = { 'slide-up': .6, 'pop': .5, 'fade': .55, 'slide-side': .6, 'scale-in': .75 };
  const TRANS_DUR = { 'push-left': .68, 'fade-up': .6, 'iris': .75, 'zoom-blur': .7, 'diagonal-wipe': .62, 'push-up': .62 };

  const stage = document.getElementById('stage');
  let DATA = window.__DATA;

  async function loadJson(u) { const r = await fetch(u); if (!r.ok) throw new Error('Cannot load ' + u); return r.json(); }
  const loadImg = src => new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => rej(new Error('Cannot load image ' + src)); im.src = src; });

  async function init() {
    if (!DATA) {
      const board = await loadJson(Q.get('board'));
      const base = Q.get('board').replace(/[^/\\]*$/, '');
      let tl;
      if (Q.get('tl')) tl = await loadJson(Q.get('tl'));
      else { const n = board.line_count, d = +Q.get('fake') || 3.0; tl = { duration: .6 + n * d + 1, lines: Array.from({ length: n }, (_, i) => ({ start: .6 + i * d, end: .6 + (i + 1) * d - .4, text: '' })) }; }
      DATA = { board, tl, base };
    }
    const { board, tl } = DATA;
    const base = DATA.base || '';
    const colors = board.colors || {};
    document.documentElement.style.setProperty('--accent', '#' + (colors.accent || 'FCA311'));
    document.documentElement.style.setProperty('--text', '#' + (colors.text || 'FFFFFF'));
    const starts = tl.lines.map(l => l.start), ends = tl.lines.map(l => l.end);
    const duration = tl.duration || (ends[ends.length - 1] + 1);
    if (board.line_count !== tl.lines.length) throw new Error(`timeline has ${tl.lines.length} lines, storyboard has ${board.line_count}`);

    // ---- build every slide ----
    const slides = [];
    const events = [];   // sound events: {t, sound, what}
    const canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    for (let i = 0; i < board.slides.length; i++) {
      const s = board.slides[i];
      const t0 = i === 0 ? 0 : starts[s.from_line - 1];
      const t1 = i + 1 < board.slides.length ? starts[board.slides[i + 1].from_line - 1] : duration;
      const el = document.createElement('div'); el.className = 'slide'; el.dataset.id = s.id;
      const kb = document.createElement('div'); kb.className = 'kb';
      const src = base + s.image;
      const im = await loadImg(src);
      const img = document.createElement('img'); img.src = src; kb.appendChild(img);
      ctx.drawImage(im, 0, 0, W, H);
      const pad = s.type === 'table' ? 0 : 8;
      const chips = [];
      s.regions.forEach((v, k) => {
        const [x, y, w, h] = v.bbox;
        const bx = Math.max(0, x - pad), by = Math.max(0, y - pad), bw = Math.min(W - bx, w + 2 * pad), bh = Math.min(H - by, h + 2 * pad);
        // cover colour = median colour of the ring just outside the region (the slide background around it)
        const ring = [];
        for (let xx = bx; xx < bx + bw; xx += 6) { ring.push([xx, Math.max(0, by - 2)]); ring.push([xx, Math.min(H - 1, by + bh + 1)]); }
        for (let yy = by; yy < by + bh; yy += 6) { ring.push([Math.max(0, bx - 2), yy]); ring.push([Math.min(W - 1, bx + bw + 1), yy]); }
        const cols = [[], [], []];
        ring.forEach(([px, py]) => { const d = ctx.getImageData(px, py, 1, 1).data; cols[0].push(d[0]); cols[1].push(d[1]); cols[2].push(d[2]); });
        const med = a => { a.sort((p, q) => p - q); return a[a.length >> 1]; };
        const cover = document.createElement('div'); cover.className = 'cover';
        cover.style.cssText = `left:${bx}px;top:${by}px;width:${bw}px;height:${bh}px;background:rgb(${med(cols[0])},${med(cols[1])},${med(cols[2])})`;
        const chip = document.createElement('div'); chip.className = 'chip';
        chip.style.cssText = `left:${bx}px;top:${by}px;width:${bw}px;height:${bh}px;background-image:url('${src.replace(/'/g, "%27")}');background-position:${-bx}px ${-by}px;opacity:0`;
        kb.appendChild(cover); kb.appendChild(chip);
        chips.push({ chip, cover, k, cx: bx + bw / 2, cy: by + bh / 2, bx, by, bw, bh });
      });
      const fx = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); fx.setAttribute('class', 'fx'); fx.setAttribute('viewBox', `0 0 ${W} ${H}`);
      kb.appendChild(fx);
      el.appendChild(kb);
      stage.appendChild(el);
      const M = s.to_line - s.from_line + 1;
      const lineStart = d => {               // start of "line d" of this slide (d may be fractional)
        if (Number.isInteger(d)) return starts[s.from_line - 1 + clamp(d, 0, M - 1)];
        return t0 + (t1 - t0) * clamp(d / M) * .85;
      };
      const lineEnd = d => ends[s.from_line - 1 + clamp(Math.round(d), 0, M - 1)];
      const nReveals = s.actions.filter(a => a.kind === 'reveal').length;
      const reveals = [], circles = [], zooms = [], countdowns = [];
      s.actions.forEach(a => {
        if (a.kind === 'reveal') {
          const c = chips[a.region]; if (!c) return;
          let T = lineStart(a.line) + (a.stagger || 0) * STAGGER;
          if (i === 0 && a.line === 0) T = .02 + (a.stagger || 0) * .18;   // title slide: show at once so frame 0 is not empty
          if (i > 0 && Number.isInteger(a.line) && a.line === 0 && !a.stagger && nReveals > 1) T += .35;  // wait for the transition to settle
          if (i > 0 && a.stagger !== undefined) T = Math.max(T, t0 + .45 + a.stagger * STAGGER);
          const kind = a.effect || 'fade';
          reveals.push({ c, T, kind, dur: REVEAL_DUR[kind] || .55 });
          if (a.sound) events.push({ t: +(T + .03).toFixed(3), sound: a.sound, what: `${s.id} reveal region ${a.region + 1}` });
        } else if (a.kind === 'circle') {
          const c = chips[a.region]; if (!c) return;
          // when: right after the countdown for an answer, 1 s after the region appears for an automatic circle, else at the line
          let A = a.after_hold ? lineEnd(a.line) + ((s.actions.find(x => x.kind === 'countdown') || {}).seconds || 0) + .1
            : a.auto ? lineStart(a.line) + 1.0 : lineStart(a.line) + .15;
          A = Math.min(A, t1 - 1.0);
          const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
          let d, L;
          if (a.shape === 'ellipse') {
            // hand-drawn ellipse: 1.15 turns, radius wobbles slightly with the angle (seeded by position so re-renders match)
            // radii 1.22x the half-size: an ellipse touching the box would cut through text in the card's corners
            const rx = c.bw / 2 * 1.22 + 6, ry = c.bh / 2 * 1.22 + 6, cx = c.cx, cy = c.cy, pts = [];
            const seed = (c.bx * 7 + c.by * 13) % 97;
            for (let ang = -.6; ang <= Math.PI * 2.3; ang += .12) {
              const w = 1 + .025 * Math.sin(ang * 3 + seed) + .018 * Math.cos(ang * 5 + seed * .7);
              pts.push(`${(cx + rx * w * Math.cos(ang)).toFixed(1)} ${(cy + ry * w * Math.sin(ang) + ang * 1.2).toFixed(1)}`);
            }
            d = 'M ' + pts.join(' L ');
            L = Math.PI * (3 * (rx + ry) - Math.sqrt((3 * rx + ry) * (rx + 3 * ry))) * 1.2 + 40;
            p.setAttribute('transform', `rotate(-2 ${cx} ${cy})`);
          } else {
            const pk = 14, x = c.bx - pk, y = c.by - pk, w = c.bw + 2 * pk, hh = c.bh + 2 * pk, rad = Math.min(34, hh / 2);
            d = `M ${x + rad} ${y} H ${x + w - rad} Q ${x + w} ${y} ${x + w} ${y + rad} V ${y + hh - rad} Q ${x + w} ${y + hh} ${x + w - rad} ${y + hh} H ${x + rad} Q ${x} ${y + hh} ${x} ${y + hh - rad} V ${y + rad} Q ${x} ${y} ${x + rad} ${y} L ${x + rad + 40} ${y - 4}`;
            L = 2 * (w + hh) + 80;
            p.setAttribute('transform', `rotate(-0.7 ${c.cx} ${c.cy})`);
          }
          p.setAttribute('d', d);
          p.setAttribute('fill', 'none'); p.setAttribute('stroke', s.type === 'question' ? '#' + (colors.text || 'FFFFFF') : '#' + (colors.accent || 'FCA311'));
          p.setAttribute('stroke-width', a.shape === 'ellipse' ? '6' : '7'); p.setAttribute('stroke-linecap', 'round'); p.setAttribute('stroke-linejoin', 'round'); p.style.opacity = '0';
          fx.appendChild(p);
          // automatic circles fade after 3.5 s or when the next region appears; deliberate ones stay until the slide ends
          let end = t1;
          if (a.auto) {
            const next = reveals.map(x => x.T).filter(T => T > A + .5).sort((x, y) => x - y)[0];
            end = Math.min(t1 - .2, A + 3.5, next !== undefined ? next - .15 : 1e9);
          }
          circles.push({ el: p, A, L, dur: a.shape === 'ellipse' ? .9 : .75, end, c });
          events.push({ t: +A.toFixed(3), sound: a.sound || 'circle', what: `${s.id} circle region ${a.region + 1}${a.auto ? ' (auto)' : ''}` });
        } else if (a.kind === 'zoom') {
          const c = chips[a.region]; if (!c) return;
          const A = Math.min(lineStart(a.line) + .2, t1 - 2.2);
          zooms.push({ A, cx: c.cx, cy: c.cy, hold: Math.min(3.0, Math.max(1.2, t1 - A - 1.2)), c });
        } else if (a.kind === 'countdown') {
          const T = lineEnd(a.line) + .15;
          countdowns.push({ T, seconds: a.seconds });
          if (a.end_sound) events.push({ t: +(T + a.seconds).toFixed(3), sound: a.end_sound, what: `${s.id} countdown ends` });
        }
      });
      if (i > 0 && s.transition_sound) events.push({ t: +(t0 - .06).toFixed(3), sound: s.transition_sound, what: `transition to ${s.id} (${s.transition})` });
      // Ken Burns: a very slow push on long slides, anchored at the bottom so the footer is never cropped
      const kbX = [.35, .65, .5, .4][i % 4];
      // pointer marks (only when the storyboard enables the cursor; off by default because viewers read it as a stray mouse)
      const marks = [];
      const CURSOR = board.cursor === true;
      if (CURSOR && new Set(reveals.map(r => Math.round(r.T * 10))).size >= 2 && !['title', 'section', 'key-message', 'closing'].includes(s.type))
        reveals.forEach(r => marks.push({ A: r.T + .32, c: r.c }));
      if (CURSOR) circles.forEach(k => marks.push({ A: k.A - .1, c: k.c }));
      if (CURSOR) zooms.forEach(z => marks.push({ A: z.A - .15, c: z.c }));
      marks.sort((x, y) => x.A - y.A);
      slides.push({ s, el, kb, chips, t0, t1, reveals, circles, zooms, countdowns, i, kbOn: s.ken_burns !== false && (t1 - t0) >= 9, kbX, marks });
    }

    // ---- optional cursor: it always rests OUTSIDE the text ----
    // wide rows (w > 1100): just right of the region; medium cards: inside the bottom-right padding; small labels: to the right.
    const restPoint = c => {
      let x, y;
      if (c.bw > 1100) { x = c.bx + c.bw + 14; y = c.cy + 6; if (x > W - 70) { x = c.bx + c.bw - 26; y = c.by + c.bh - 14; } }
      else if (c.bw > 260) { x = c.bx + c.bw - 22; y = c.by + c.bh - 16; }
      else { x = c.bx + c.bw + 14; y = c.cy; }
      return { x: Math.min(Math.max(x, 24), W - 64), y: Math.min(Math.max(y, 24), H - 64) };
    };
    const curLayer = document.createElement('div');
    curLayer.style.cssText = 'position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none;z-index:45;transform-origin:50% 50%';
    const cur = document.createElement('div');
    cur.style.cssText = 'position:absolute;left:0;top:0;width:56px;height:56px;opacity:0;filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))';
    cur.innerHTML = '<svg viewBox="0 0 56 56" width="56" height="56"><path d="M8 5 L8 41 L17 33 L23 47 L31 44 L25 31 L37 31 Z" fill="#fff" stroke="#10203f" stroke-width="3.2" stroke-linejoin="round"/></svg>';
    curLayer.appendChild(cur); stage.appendChild(curLayer);
    const moves = [];
    let pos = { x: 1650, y: 960 }, prevA = -9, turn = 0;
    slides.forEach(X => {
      if (!X.marks.length) { if (X.t0 > 0) moves.push({ hide: true, H: X.t0 + .05, key: X.t0 + .05 }); return; }
      X.marks.forEach(m => {
        const to = restPoint(m.c);
        let S0 = Math.max(m.A - .85, prevA + .18, X.t0 + .2);
        if (m.A - S0 < .32) S0 = Math.max(prevA + .05, m.A - .32);
        const dx = to.x - pos.x, dy = to.y - pos.y, dist = Math.hypot(dx, dy) || 1;
        const off = Math.min(150, dist * .22) * (turn++ % 2 ? 1 : -1);   // curve to one side, alternating like a hand
        moves.push({ S: S0, A: m.A, from: pos, ctl: { x: (pos.x + to.x) / 2 - dy / dist * off, y: (pos.y + to.y) / 2 + dx / dist * off }, to, key: S0 - .22, k: turn });
        pos = to; prevA = m.A;
      });
      const last = X.marks[X.marks.length - 1].A;
      if (X.t1 - last > 2.5) moves.push({ hide: true, H: Math.min(last + 2.2, X.t1 - .3), key: Math.min(last + 2.2, X.t1 - .3) });
    });
    moves.sort((a, b) => a.key - b.key);

    // shared layers: the light streak of push-left and the countdown ring
    const streak = document.createElement('div'); streak.id = 'streak'; stage.appendChild(streak);
    const cd = document.createElement('div'); cd.id = 'countdown';
    cd.innerHTML = `<svg viewBox="0 0 150 150" width="150" height="150"><circle cx="75" cy="75" r="62" fill="rgba(0,0,0,.28)" stroke="rgba(255,255,255,.25)" stroke-width="8"/>
      <circle id="cdring" cx="75" cy="75" r="62" fill="none" stroke="var(--accent)" stroke-width="8" stroke-linecap="round" transform="rotate(-90 75 75)"/></svg><div class="num">0</div>`;
    stage.appendChild(cd);
    const cdRing = cd.querySelector('#cdring'), cdNum = cd.querySelector('.num');
    const RING = 2 * Math.PI * 62;

    // ---- draw one frame ----
    function render(t) {
      t = clamp(t, 0, duration);
      let si = 0;
      for (let i = 0; i < slides.length; i++) if (t >= slides[i].t0) si = i;
      const S = slides[si];
      const kind = S.s.transition || 'fade-up';
      const td = TRANS_DUR[kind] || .65;
      const u = si === 0 ? 1 : clamp((t - S.t0) / td);
      const pi = (si > 0 && u < 1) ? si - 1 : -1;
      const state = [si, (u * 60) | 0];   // frames with the same state are identical, so render.mjs reuses the screenshot
      slides.forEach((x, i) => x.el.classList.toggle('on', i === si || i === pi));
      const E = S.el, P = pi >= 0 ? slides[pi].el : null;
      const q = eIn(u), qo = eOut(clamp((t - S.t0) / (td * .5)));
      E.style.clipPath = ''; E.style.filter = ''; E.style.opacity = '1'; E.style.transform = ''; E.style.zIndex = '2';
      if (P) { P.style.clipPath = ''; P.style.filter = ''; P.style.transform = ''; P.style.opacity = '1'; P.style.zIndex = '1'; }
      let streakA = 0;
      if (u < 1) {
        if (kind === 'push-left') {
          E.style.opacity = String(q); E.style.transform = `translateX(${((1 - q) * 70).toFixed(1)}px) scale(${(.975 + .025 * q).toFixed(4)})`; E.style.filter = `blur(${((1 - q) * 6).toFixed(2)}px)`;
          P.style.opacity = String(Math.pow(1 - qo, 2)); P.style.transform = `translateX(${(-qo * 70).toFixed(1)}px) scale(${(1 + .03 * qo).toFixed(4)})`; P.style.filter = `blur(${(qo * 5).toFixed(2)}px)`;
          streakA = Math.sin(Math.PI * u) * .5;
        } else if (kind === 'fade-up') {
          E.style.opacity = String(q); E.style.transform = `translateY(${((1 - q) * 36).toFixed(1)}px)`;
          P.style.opacity = String(1 - qo);
        } else if (kind === 'iris') {
          E.style.clipPath = `circle(${(8 + 92 * eIO(u)).toFixed(2)}% at 50% 50%)`;
          P.style.opacity = String(1 - clamp((u - .7) / .3));
        } else if (kind === 'zoom-blur') {
          E.style.opacity = String(q); E.style.transform = `scale(${(1.08 - .08 * q).toFixed(4)})`; E.style.filter = `blur(${((1 - q) * 8).toFixed(2)}px)`;
          P.style.opacity = String(1 - qo); P.style.transform = `scale(${(1 - .03 * qo).toFixed(4)})`;
        } else if (kind === 'diagonal-wipe') {
          const k = eIO(u) * (W + H + 200);
          E.style.clipPath = `polygon(0 0, ${k}px 0, ${k - H - 200}px ${H}px, 0 ${H}px)`;
          // the old slide fades and recedes from the start so half-cut text does not stand out
          P.style.opacity = String(1 - .75 * eIO(u)); P.style.filter = `blur(${(4 * u).toFixed(2)}px)`; P.style.transform = `scale(${(1 - .02 * u).toFixed(4)})`;
        } else if (kind === 'push-up') {
          const k = eIO(u);
          E.style.transform = `translateY(${((1 - k) * H).toFixed(1)}px)`;
          P.style.transform = `translateY(${(-k * H * .28).toFixed(1)}px)`; P.style.opacity = String(1 - k * .7);
        }
      }
      streak.style.opacity = String(streakA); streak.style.transform = `translateX(${(-90 + 180 * u).toFixed(1)}%)`;
      for (const X of [S, pi >= 0 ? slides[pi] : null]) {
        if (!X) continue;
        let sc = 1, ox = 50, oy = 50;
        if (X.kbOn) { sc = 1 + .015 * clamp((t - X.t0) / (X.t1 - X.t0)); ox = X.kbX * 100; oy = 100; }
        for (const z of X.zooms) {
          const d = t - z.A, ZI = .55, ZO = .5, ZM = 1.22;
          if (d >= 0 && d < ZI + z.hold + ZO) {
            const zz = d < ZI ? 1 + (ZM - 1) * eIO(d / ZI) : d < ZI + z.hold ? ZM : 1 + (ZM - 1) * (1 - eIO((d - ZI - z.hold) / ZO));
            sc *= zz; ox = z.cx / W * 100; oy = z.cy / H * 100; state.push('z', (zz * 500) | 0);
          }
        }
        X.kb.style.transformOrigin = `${ox}% ${oy}%`;
        X.kb.style.transform = sc === 1 ? '' : `scale(${sc.toFixed(5)})`;
        if (X.kbOn) state.push('k', (sc * 4000) | 0);
        X.reveals.forEach(r => {
          const p = clamp((t - r.T) / r.dur), e = r.c.chip;
          if (t < r.T) { e.style.opacity = '0'; e.style.transform = ''; return; }
          if (p >= 1) { e.style.opacity = '1'; e.style.transform = ''; return; }
          state.push('r', r.c.k, (p * 60) | 0);
          if (r.kind === 'slide-up') { const k = eIn(p); e.style.opacity = String(k); e.style.transform = `translateY(${((1 - k) * 40).toFixed(1)}px)`; }
          else if (r.kind === 'pop') { const k = eBack(p); e.style.opacity = String(clamp(p * 2.5)); e.style.transform = `scale(${(.84 + .16 * k).toFixed(4)})`; }
          else if (r.kind === 'slide-side') { const k = eIn(p), dir = r.c.cx < W / 2 ? -1 : 1; e.style.opacity = String(k); e.style.transform = `translateX(${(dir * (1 - k) * 44).toFixed(1)}px)`; }
          else if (r.kind === 'scale-in') { const k = eIn(p); e.style.opacity = String(k); e.style.transform = `scale(${(1.06 - .06 * k).toFixed(4)})`; }
          else e.style.opacity = String(eIn(p));
        });
        X.circles.forEach(k => {
          if (t < k.A || t > k.end + .35) { k.el.style.opacity = '0'; return; }
          const p = clamp((t - k.A) / k.dur);
          k.el.setAttribute('stroke-dasharray', `${k.L} ${k.L * 2}`);
          k.el.setAttribute('stroke-dashoffset', String(k.L * (1 - eIO(p))));
          const fade = t > k.end ? 1 - clamp((t - k.end) / .35) : 1;
          k.el.style.opacity = String(fade);
          if (p < 1 || fade < 1) state.push('c', (p * 60) | 0, (fade * 20) | 0);
        });
      }
      let cdA = 0;
      for (const d of S.countdowns) {
        const left = d.seconds - (t - d.T);
        if (t >= d.T - .4 && left > -.9) {
          cdA = t < d.T ? clamp((t - d.T + .4) / .4) : left > 0 ? 1 : 1 - clamp((-left) / .9);
          cdRing.setAttribute('stroke-dasharray', `${RING}`); cdRing.setAttribute('stroke-dashoffset', String(RING * (1 - clamp(left / d.seconds))));
          cdNum.textContent = left > 0 ? String(Math.ceil(left - 1e-6)) : '✓';
          state.push('d', (left * 10) | 0);
        }
      }
      cd.style.opacity = String(cdA);
      // cursor
      let alpha = 0;
      for (const e of moves) {
        if (e.hide) { if (t >= e.H) alpha = 1 - clamp((t - e.H) / .25); else break; }
        else { if (t >= e.key) alpha = clamp((t - e.key) / .25); else break; }
      }
      if (cdA > .5 || board.cursor !== true) alpha = 0;
      let last = null;
      for (const e of moves) if (!e.hide && e.S <= t) last = e;
      let cx = 1650, cy = 960, sCur = 1;
      if (last) {
        if (t < last.A) {
          const uu = eIO(clamp((t - last.S) / (last.A - last.S))), v = 1 - uu;
          cx = v * v * last.from.x + 2 * v * uu * last.ctl.x + uu * uu * last.to.x;
          cy = v * v * last.from.y + 2 * v * uu * last.ctl.y + uu * uu * last.to.y;
        } else {
          // on arrival: a small tremor that settles within 3 s (a hand is never perfectly still, nor shaking forever)
          const d0 = t - last.A, j = clamp(d0 / .3), g = clamp((d0 - .35) / .9) * Math.max(0, 1 - Math.max(0, d0 - 1.5) / 3);
          cx = last.to.x + (Math.sin(t * 5.3 + last.k) * 1.4 + Math.sin(t * 2.1) * .9) * j + (Math.sin(t * 1.15 + last.k * 1.7) * 9 + Math.sin(t * .55 + last.k) * 5) * g;
          cy = last.to.y + (Math.cos(t * 4.1 + last.k) * 1.1 + Math.sin(t * 1.7) * .8) * j + Math.cos(t * .95 + last.k * 1.3) * 6 * g;
          if (d0 < .22) sCur = 1 - .12 * Math.sin(Math.PI * d0 / .22);
        }
      }
      curLayer.style.transformOrigin = S.kb.style.transformOrigin || '50% 50%';
      curLayer.style.transform = S.kb.style.transform || '';
      cur.style.opacity = String(alpha);
      cur.style.transform = `translate(${(cx - 8).toFixed(1)}px, ${(cy - 5).toFixed(1)}px) scale(${sCur.toFixed(3)})`;
      if (alpha > 0) state.push('m', Math.round(cx), Math.round(cy), (alpha * 20) | 0);
      return state.join('.');
    }

    window.__render = render;
    window.__info = { duration, slides: slides.map(x => ({ id: x.s.id, t0: x.t0, t1: x.t1 })), events: events.sort((a, b) => a.t - b.t) };
    if (Q.get('mode') === 'render' || window.__DATA_FROM_RENDERER) { stage.style.transform = 'none'; window.__ready = true; render(0); return; }

    // ---- interactive preview in a browser ----
    const fit = () => { const k = Math.min(innerWidth / W, innerHeight / H); stage.style.transform = `scale(${k})`; stage.style.position = 'absolute'; stage.style.left = (innerWidth - W * k) / 2 + 'px'; stage.style.top = (innerHeight - H * k) / 2 + 'px'; };
    fit(); addEventListener('resize', fit);
    const info = document.createElement('div'); info.id = 'hud'; document.body.appendChild(info);
    const audio = Q.get('audio') ? new Audio(Q.get('audio')) : null;
    let playing = false, tStart = 0, tBase = 0;
    const nowT = () => audio ? audio.currentTime : tBase + (playing ? (performance.now() - tStart) / 1000 : 0);
    const toggle = () => { playing = !playing; if (audio) playing ? audio.play() : audio.pause(); else if (playing) tStart = performance.now(); else tBase = nowT(); };
    const seek = d => { const v = clamp(nowT() + d, 0, duration); if (audio) audio.currentTime = v; else { tBase = v; tStart = performance.now(); } };
    addEventListener('keydown', e => { if (e.code === 'Space') { e.preventDefault(); toggle(); } if (e.code === 'ArrowRight') seek(5); if (e.code === 'ArrowLeft') seek(-5); });
    addEventListener('click', toggle);
    const loop = () => { const tt = nowT(); render(tt); info.textContent = `${tt.toFixed(1)} / ${duration.toFixed(1)} s  (Space: play/pause, arrows: seek 5 s)`; requestAnimationFrame(loop); };
    window.__ready = true; loop();
  }
  init().catch(e => { window.__error = String(e && e.stack || e); console.error(e); });
})();

// Render a lesson video with headless Chrome (puppeteer-core) + ffmpeg, from video.html + storyboard.json + timeline.json.
//
//   node render.mjs plan   <storyboard.json> <timeline.json> <events.json>          -> slide times + sound events
//   node render.mjs sheet  <storyboard.json> <timeline.json> <out-folder> [--from a --to b --every s] [seconds ...]
//                                                                                     -> contact sheets, 8 frames each
//   node render.mjs video  <storyboard.json> <timeline.json> <audio.mp3|none> <out.mp4> [--fps 30] [--workers 2] [--crf 18] [--full]
//        INCREMENTAL: one silent segment per slide in _segments/<hash>.mp4; only changed slides are rendered again.
//        --full forces a full re-render.
//
// Frames whose state is identical to the previous frame reuse the previous screenshot, so still slides render fast.
// Chrome or Edge is found automatically; set CHROME_PATH to use another Chromium-based browser.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { pathToFileURL, fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CANDIDATES = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe', 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium',
  path.join(os.homedir(), 'AppData', 'Local', 'Google', 'Chrome', 'Application', 'chrome.exe'),
];
const CHROME = CANDIDATES.find(p => p && fs.existsSync(p));
if (!CHROME) { console.error('Chrome, Chromium or Edge not found. Set CHROME_PATH to the browser executable.'); process.exit(2); }
const [, , cmd, boardPath, tlPath, ...rest] = process.argv;
if (!cmd || !boardPath || !tlPath) { console.error('Commands: plan | sheet | video (see the top of this file)'); process.exit(2); }

const board = JSON.parse(fs.readFileSync(boardPath, 'utf8'));
const tl = JSON.parse(fs.readFileSync(tlPath, 'utf8'));
const base = pathToFileURL(path.resolve(path.dirname(boardPath)) + path.sep).href;
const DATA = { board, tl, base };

const launch = () => puppeteer.launch({
  executablePath: CHROME, headless: true, protocolTimeout: 600000,
  args: ['--allow-file-access-from-files', '--font-render-hinting=none', '--hide-scrollbars', '--force-device-scale-factor=1',
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', '--disable-gpu-vsync'],
});
async function openPage(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
  await page.evaluateOnNewDocument(d => { window.__DATA = d; window.__DATA_FROM_RENDERER = true; }, DATA);
  page.on('pageerror', e => console.error('PAGE ERROR:', e.message));
  await page.goto(pathToFileURL(path.join(HERE, 'video.html')).href + '?mode=render', { waitUntil: 'load' });
  await page.waitForFunction('window.__ready === true || window.__error', { timeout: 60000 });
  const err = await page.evaluate('window.__error');
  if (err) throw new Error('Renderer error: ' + err);
  return page;
}
const num = (opt, k, d) => opt.indexOf(k) >= 0 ? Number(opt[opt.indexOf(k) + 1]) : d;

async function plan() {
  const out = rest[0];
  const b = await launch(); const p = await openPage(b);
  const info = await p.evaluate('window.__info');
  await b.close();
  fs.writeFileSync(out, JSON.stringify(info, null, 1), 'utf8');
  console.log(`plan: ${info.slides.length} slides, ${info.duration.toFixed(1)} s, ${info.events.length} sound events -> ${out}`);
}

async function sheet() {
  const out = rest[0]; fs.mkdirSync(out, { recursive: true });
  const opt = rest.slice(1);
  const b = await launch(); const p = await openPage(b);
  const info = await p.evaluate('window.__info');
  let times;
  const every = num(opt, '--every', 0);
  const nums = opt.filter(x => /^[\d.]+$/.test(x)).map(Number);
  if (every) { times = []; for (let t = num(opt, '--from', 0); t <= num(opt, '--to', info.duration); t += every) times.push(+t.toFixed(2)); }
  else if (nums.length) times = nums;
  else {
    const set = new Set([0]);   // frame 0, then per slide: mid-transition, settled, middle, just before it ends
    info.slides.forEach(s => { if (s.t0 > 0) set.add(+(s.t0 + .3).toFixed(2)); set.add(+(s.t0 + 1.2).toFixed(2)); set.add(+((s.t0 + s.t1) / 2).toFixed(2)); set.add(+Math.max(s.t0, s.t1 - .3).toFixed(2)); });
    times = [...set].filter(t => t <= info.duration).sort((x, y) => x - y);
  }
  const shots = [];
  for (const t of times) {
    await p.evaluate(tt => window.__render(tt), t);
    const b64 = await p.screenshot({ type: 'jpeg', quality: 82, encoding: 'base64' });
    const sl = info.slides.find(s => t >= s.t0 && t < s.t1) || info.slides[info.slides.length - 1];
    shots.push({ t, id: sl.id, b64 });
  }
  const sp = await b.newPage();
  await sp.setViewport({ width: 1928, height: 620, deviceScaleFactor: 1 });
  let n = 0;
  for (let i = 0; i < shots.length; i += 8) {
    const cells = shots.slice(i, i + 8).map(s => `<figure><img src="data:image/jpeg;base64,${s.b64}"><figcaption>${s.t.toFixed(2)} s · ${s.id}</figcaption></figure>`).join('');
    await sp.setContent(`<style>body{margin:0;background:#111;display:grid;grid-template-columns:repeat(4,482px);font:600 18px Arial;color:#fff}figure{margin:0;border:1px solid #333}img{width:480px;height:270px;display:block}figcaption{padding:4px 8px;height:20px}</style>${cells}`);
    const f = path.join(out, `sheet-${String(++n).padStart(2, '0')}.png`);
    await sp.screenshot({ path: f, fullPage: true });
    console.log('sheet', f, ':', shots.slice(i, i + 8).map(s => s.t.toFixed(1)).join(' '));
  }
  await b.close();
}

async function video() {
  // INCREMENTAL RENDERING BY SLIDE: each slide is a silent mp4 segment in _segments/<hash>.mp4. The hash covers the slide
  // image, the slide's storyboard entry, its narration timings (relative), the previous slide (transitions draw it too),
  // the renderer code, fps and crf. Fixing one slide re-renders that segment only; segments are joined with concat
  // (-c copy) and the audio is muxed in, which takes seconds.
  const [audio, outMp4, ...opt] = rest;
  const fps = num(opt, '--fps', 30), workers = num(opt, '--workers', 2), crf = num(opt, '--crf', 18);
  const full = opt.includes('--full');
  const md5 = x => crypto.createHash('md5').update(x).digest('hex');
  const engineHash = md5(fs.readFileSync(path.join(HERE, 'video.js')) + fs.readFileSync(path.join(HERE, 'video.html')));
  const segDir = path.join(path.dirname(path.resolve(outMp4)), '_segments'); fs.mkdirSync(segDir, { recursive: true });
  const browsers = [], pages = [];
  for (let i = 0; i < workers; i++) { const b = await launch(); browsers.push(b); pages.push(await openPage(b)); }
  const info = await pages[0].evaluate('window.__info');
  const { duration } = info;
  const total = Math.ceil(duration * fps);
  const tStart = Date.now();
  const img = rel => md5(fs.readFileSync(path.join(path.dirname(boardPath), rel)));
  const segs = info.slides.map((sl, i) => {
    const f0 = i === 0 ? 0 : Math.ceil(sl.t0 * fps - 1e-6);
    const f1 = i + 1 < info.slides.length ? Math.ceil(info.slides[i + 1].t0 * fps - 1e-6) : total;
    const s = board.slides[i], p = i > 0 ? board.slides[i - 1] : null;
    const lines = tl.lines.slice(s.from_line - 1, s.to_line).map(l => [+(l.start - sl.t0).toFixed(3), +(l.end - sl.t0).toFixed(3),
      +((l.speech_start ?? l.start) - sl.t0).toFixed(3), +((l.speech_end ?? l.end) - sl.t0).toFixed(3)]);
    const key = full ? null : md5(JSON.stringify({
      engineHash, fps, crf, png: img(s.image), slide: s, lines, cursor: board.cursor === true, colors: board.colors,
      span: +(sl.t1 - sl.t0).toFixed(3), phase: +((f0 / fps) - sl.t0).toFixed(4), first: i === 0,
      prev: p ? { png: img(p.image), regions: p.regions, kb: p.ken_burns, type: p.type } : null,
    }));
    return { id: sl.id, f0, f1, file: key ? path.join(segDir, key + '.mp4') : path.join(segDir, `full-${sl.id}.mp4`) };
  });
  const todo = segs.filter(sg => full || !fs.existsSync(sg.file));
  console.log(`${segs.length} segments, ${todo.length} to render, ${segs.length - todo.length} reused`);
  let reused = 0, rendered = 0;
  const renderSegment = async (page, sg) => {
    const tmp = sg.file + '.tmp.mp4';
    const args = ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', 'pipe:0',
      '-c:v', 'libx264', '-preset', 'medium', '-crf', String(crf), '-pix_fmt', 'yuv420p', '-r', String(fps), '-g', String(fps * 2), '-keyint_min', String(fps * 2),
      '-sc_threshold', '0', '-video_track_timescale', String(fps * 1000), '-an', tmp];
    const ff = spawn('ffmpeg', args, { stdio: ['pipe', 'inherit', 'inherit'] });
    const done = new Promise((res, rej) => ff.on('close', c => c === 0 ? res() : rej(new Error('ffmpeg exit ' + c))));
    let prevState = null, prevBuf = null;
    for (let f = sg.f0; f < sg.f1; f++) {
      const st = await page.evaluate(t => window.__render(t), f / fps);
      let b;
      if (st === prevState && prevBuf) { b = prevBuf; reused++; }
      else { b = await page.screenshot({ type: 'jpeg', quality: 92, optimizeForSpeed: true }); prevState = st; prevBuf = b; }
      if (!ff.stdin.write(b)) await new Promise(r => ff.stdin.once('drain', r));
      rendered++;
      if (rendered % 300 === 0) console.log(`frame ${rendered}  ${((Date.now() - tStart) / 1000).toFixed(0)} s, reused ${reused}`);
    }
    ff.stdin.end(); await done;
    fs.renameSync(tmp, sg.file);
    console.log(`segment ${sg.id}: ${sg.f1 - sg.f0} frames -> ${path.basename(sg.file)}`);
  };
  let next = 0;
  await Promise.all(pages.map(async page => { for (;;) { const k = next++; if (k >= todo.length) break; await renderSegment(page, todo[k]); } }));
  await Promise.all(browsers.map(b => b.close()));
  const list = path.join(segDir, 'list.txt');
  const esc = p => p.split(path.sep).join('/').split("'").join("'\\''");
  fs.writeFileSync(list, segs.map(sg => `file '${esc(sg.file)}'`).join('\n') + '\n', 'utf8');
  const hasAudio = audio && audio !== 'none' && fs.existsSync(audio);
  const args = ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list];
  if (hasAudio) args.push('-i', audio, '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-t', String(duration));
  args.push('-c:v', 'copy', '-movflags', '+faststart', outMp4);
  await new Promise((res, rej) => spawn('ffmpeg', args, { stdio: 'inherit' }).on('close', c => c === 0 ? res() : rej(new Error('ffmpeg concat exit ' + c))));
  // keep the 60 most recent unused segments so you can switch back and forth while editing
  const keep = new Set(segs.map(sg => path.basename(sg.file)));
  fs.readdirSync(segDir).filter(f => f.endsWith('.mp4') && !keep.has(f))
    .map(f => ({ f, t: fs.statSync(path.join(segDir, f)).mtimeMs })).sort((a, b) => b.t - a.t)
    .slice(60).forEach(o => fs.unlinkSync(path.join(segDir, o.f)));
  console.log(`done ${outMp4}: ${total} frames, ${duration.toFixed(1)} s; rendered ${todo.length}/${segs.length} segments (${rendered} frames, ${reused} reused) in ${((Date.now() - tStart) / 1000).toFixed(0)} s`);
}

try {
  if (cmd === 'plan') await plan(); else if (cmd === 'sheet') await sheet(); else if (cmd === 'video') await video();
  else { console.error('Commands: plan | sheet | video'); process.exit(2); }
} catch (e) { console.error(e.stack || e); process.exit(1); }

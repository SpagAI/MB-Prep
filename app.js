/* Practical Projector — spotting exam simulator. Plain JS, works from file:// (data comes from bank.js). */
(function () {
  'use strict';

  // ---------------------------------------------------------------- constants
  const BANK = (window.BANK && Array.isArray(window.BANK.items)) ? window.BANK : { items: [], courses: [] };
  const ITEMS = BANK.items;
  const COURSES = BANK.courses || [];
  const TIMER_STEPS = [0, 5, 10, 15, 20, 25, 30, 40, 45, 50, 60, 75, 90, 105, 120, 150, 180, 210, 240, 300,
    360, 420, 480, 540, 600, 720, 900, 1200, 1500, 1800];
  const TIMER_PRESETS = [0, 15, 30, 45, 60, 90, 120, 300, 600, 1800];
  const COUNT_OPTIONS = [10, 20, 30, 50, 'all'];
  const DISTINCTION_DEFAULT = 60;
  const MODE_NAMES = { study: 'Study', easy: 'Easy Money', distinction: 'Distinction' };
  const KEY_SETTINGS = 'pp.settings.v1';
  const KEY_HISTORY = 'pp.history.v1';
  const SEP = '\u0001';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const catKey = (course, cat) => course + SEP + cat;
  const catName = (c) => String(c).replace(/^_+/, '');

  // ---------------------------------------------------------------- storage (always try/catch)
  function load(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }
  function save(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { /* private mode / storage full: ignore */ }
  }

  // ---------------------------------------------------------------- helpers
  function shuffle(arr) { // Fisher-Yates, in place
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      const t = arr[i]; arr[i] = arr[j]; arr[j] = t;
    }
    return arr;
  }

  /** Re-orders a shuffled list so the same course/category never appears twice in a row when avoidable. */
  function spreadByCategory(items, keyFn) {
    keyFn = keyFn || ((it) => catKey(it.course, it.category));
    const groups = new Map();
    for (const it of items) {
      const k = keyFn(it);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(it);
    }
    const out = [];
    let last = null;
    let remaining = items.length;
    while (remaining > 0) {
      const keys = [...groups.keys()].filter((k) => groups.get(k).length);
      let choices = keys.filter((k) => k !== last);
      if (!choices.length) choices = keys; // unavoidable repeat
      // A category holding half (or more) of what is left must go now, or it will be forced to repeat later.
      let pick = choices.find((k) => groups.get(k).length * 2 >= remaining && keys.length > 1);
      if (!pick) {
        let total = 0;
        for (const k of choices) total += groups.get(k).length;
        let r = Math.random() * total;
        for (const k of choices) {
          r -= groups.get(k).length;
          if (r < 0) { pick = k; break; }
        }
        if (!pick) pick = choices[choices.length - 1];
      }
      out.push(groups.get(pick).shift());
      last = pick;
      remaining--;
    }
    return out;
  }

  function courseColor(name) {
    const n = String(name).toLowerCase();
    if (/histo/.test(n)) return 'var(--c-histo)';
    if (/chem/.test(n)) return 'var(--c-chem)';
    if (/mmp|micro|parasit/.test(n)) return 'var(--c-mmp)';
    if (/haem|hem/.test(n)) return 'var(--c-haem)';
    const pal = ['#4c51bf', '#2b6cb0', '#805ad5', '#319795', '#d53f8c'];
    let h = 0;
    for (const ch of n) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return pal[h % pal.length];
  }

  function fmtTime(sec) {
    if (!sec) return 'Off';
    if (sec < 60) return sec + 's';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return s ? `${m} min ${s}s` : `${m} min`;
  }
  function fmtClock(ms) {
    const total = Math.ceil(ms / 1000);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m + ':' + String(s).padStart(2, '0');
  }
  function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

  // ---------------------------------------------------------------- settings
  const defaults = {
    courses: [],
    cats: [], // catKey list
    mode: 'easy',
    timer: 60,
    count: 20,
    beep: true,
    studyShuffle: false,
    countMode: 'total', // 'total' = one number for everything, 'per' = a number for each practical
    perCourse: {}, // course name -> number | 'all'
    order: 'mixed', // 'mixed' = practicals shuffled together, 'blocks' = one practical after another
    answerBoxes: false, // Distinction: off = write answers on paper (default, like the real exam)
  };
  const settings = Object.assign({}, defaults, load(KEY_SETTINGS, {}));
  const knownCats = new Set();
  for (const c of COURSES) for (const cat of c.categories) knownCats.add(catKey(c.name, cat.name));
  let selCourses = new Set(settings.courses.filter((c) => COURSES.some((x) => x.name === c)));
  let selCats = new Set(settings.cats.filter((k) => knownCats.has(k)));
  if (!['study', 'easy', 'distinction'].includes(settings.mode)) settings.mode = 'easy';
  if (!TIMER_STEPS.includes(settings.timer)) settings.timer = nearestStep(settings.timer);
  if (!COUNT_OPTIONS.includes(settings.count)) settings.count = 20;
  if (!['total', 'per'].includes(settings.countMode)) settings.countMode = 'total';
  if (!['mixed', 'blocks'].includes(settings.order)) settings.order = 'mixed';
  if (!settings.perCourse || typeof settings.perCourse !== 'object') settings.perCourse = {};
  const PER_DEFAULT = 10;

  function nearestStep(v) {
    v = Number(v) || 0;
    let best = TIMER_STEPS[0];
    for (const s of TIMER_STEPS) if (Math.abs(s - v) < Math.abs(best - v)) best = s;
    return best;
  }
  function persistSettings() {
    settings.courses = [...selCourses];
    settings.cats = [...selCats];
    save(KEY_SETTINGS, settings);
  }

  // ---------------------------------------------------------------- home screen
  function renderHome() {
    $('#bank-total').textContent = ITEMS.length ? plural(ITEMS.length, 'image') + ' in your bank' : 'empty bank';
    $('#bank-missing').hidden = ITEMS.length > 0;
    renderCourses();
    renderModes();
    renderTimer();
    renderCounts();
    renderSummary();
    renderHistory();
    $('#beep-toggle').checked = !!settings.beep;
    $('#study-shuffle').checked = !!settings.studyShuffle;
    $('#answer-boxes').checked = !!settings.answerBoxes;
  }

  function renderCourses() {
    const wrap = $('#course-buttons');
    wrap.innerHTML = '';
    for (const c of COURSES) {
      const n = c.categories.reduce((s, x) => s + x.count, 0);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'course-btn' + (selCourses.has(c.name) ? ' on' : '') + (n ? '' : ' empty');
      b.style.setProperty('--c', courseColor(c.name));
      b.setAttribute('aria-pressed', selCourses.has(c.name));
      b.innerHTML = `${esc(c.name)}<small>${plural(n, 'image')}</small>`;
      b.addEventListener('click', () => toggleCourse(c.name));
      wrap.appendChild(b);
    }
    const panels = $('#category-panels');
    panels.innerHTML = '';
    for (const c of COURSES) {
      if (!selCourses.has(c.name)) continue;
      const color = courseColor(c.name);
      const panel = document.createElement('div');
      panel.className = 'cat-panel';
      panel.style.setProperty('--c', color);
      const allOn = c.categories.every((x) => selCats.has(catKey(c.name, x.name)));
      panel.innerHTML = `<div class="cat-panel-head"><h3>${esc(c.name)} categories</h3>
        <button type="button" class="link-btn" data-all>${allOn ? 'Clear categories' : 'Select all categories'}</button></div>
        <div class="chips"></div>`;
      const chips = $('.chips', panel);
      for (const cat of c.categories) {
        const k = catKey(c.name, cat.name);
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'chip' + (selCats.has(k) ? ' on' : '');
        chip.style.setProperty('--c', color);
        chip.setAttribute('aria-pressed', selCats.has(k));
        chip.innerHTML = `${esc(catName(cat.name))}<span class="n">${cat.count}</span>`;
        chip.addEventListener('click', () => {
          if (selCats.has(k)) selCats.delete(k); else selCats.add(k);
          persistSettings(); renderCourses(); renderSummary();
        });
        chips.appendChild(chip);
      }
      $('[data-all]', panel).addEventListener('click', () => {
        for (const cat of c.categories) {
          const k = catKey(c.name, cat.name);
          if (allOn) selCats.delete(k); else selCats.add(k);
        }
        persistSettings(); renderCourses(); renderSummary();
      });
      panels.appendChild(panel);
    }
    const allCourses = COURSES.length && COURSES.every((c) => selCourses.has(c.name));
    $('#courses-all').textContent = allCourses ? 'Clear all' : 'Select all';
  }

  function selectAllCats(course) {
    const c = COURSES.find((x) => x.name === course);
    if (c) for (const cat of c.categories) selCats.add(catKey(c.name, cat.name));
  }
  function toggleCourse(name) {
    if (selCourses.has(name)) {
      selCourses.delete(name);
    } else {
      selCourses.add(name);
      const c = COURSES.find((x) => x.name === name);
      if (c && !c.categories.some((x) => selCats.has(catKey(name, x.name)))) selectAllCats(name);
    }
    persistSettings(); renderCourses(); renderSummary();
  }

  function renderModes() {
    for (const b of $$('.mode-btn')) {
      const on = b.dataset.mode === settings.mode;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on);
    }
    document.body.classList.toggle('mode-study', settings.mode === 'study');
    document.body.classList.toggle('mode-distinction', settings.mode === 'distinction');
  }

  function renderTimer() {
    const slider = $('#timer-slider');
    const dist = settings.mode === 'distinction';
    if (dist && !settings.timer) settings.timer = DISTINCTION_DEFAULT;
    slider.max = TIMER_STEPS.length - 1;
    slider.min = dist ? 1 : 0;
    slider.value = TIMER_STEPS.indexOf(settings.timer);
    $('#timer-readout').textContent = settings.timer ? fmtTime(settings.timer) : 'Off (manual Next)';
    const presets = $('#timer-presets');
    presets.innerHTML = '';
    for (const p of TIMER_PRESETS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pill' + (p === settings.timer ? ' on' : '');
      b.textContent = p === 0 ? 'Off' : p < 60 ? p + 's' : (p / 60) + ' min';
      b.disabled = dist && p === 0;
      b.addEventListener('click', () => { settings.timer = p; persistSettings(); renderTimer(); renderSummary(); });
      presets.appendChild(b);
    }
    $('#timer-note').textContent = dist
      ? 'Distinction mode: the timer must be on. Next moves forward only.'
      : (settings.timer ? 'The slide moves on automatically when time runs out.' : 'No countdown. Use Next to move on.');
  }

  function renderCounts() {
    for (const b of $$('[data-countmode]')) b.classList.toggle('on', b.dataset.countmode === settings.countMode);
    for (const b of $$('[data-order]')) b.classList.toggle('on', b.dataset.order === settings.order);
    const per = settings.countMode === 'per';
    const wrap = $('#count-buttons');
    wrap.hidden = per;
    wrap.innerHTML = '';
    for (const c of COUNT_OPTIONS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'pill' + (c === settings.count ? ' on' : '');
      b.textContent = c === 'all' ? 'All' : String(c);
      b.addEventListener('click', () => { settings.count = c; persistSettings(); renderCounts(); renderSummary(); });
      wrap.appendChild(b);
    }
    // One row per selected practical
    const pc = $('#per-course');
    pc.hidden = !per;
    pc.innerHTML = '';
    const groups = usableByCourse();
    if (per) {
      if (!groups.size) pc.innerHTML = '<p class="note">Choose courses above first.</p>';
      for (const [course, list] of groups) {
        const cur = perCourseValue(course);
        const row = document.createElement('div');
        row.className = 'pc-row';
        row.style.setProperty('--c', courseColor(course));
        row.innerHTML = `<span class="pc-name">${esc(course)}<small>${plural(list.length, 'image')} available</small></span>` +
          [5, 10, 20].map((n) => `<button type="button" class="pill ${cur === n ? 'on' : ''}" data-n="${n}" ${n > list.length ? 'disabled' : ''}>${n}</button>`).join('') +
          `<button type="button" class="pill ${cur === 'all' ? 'on' : ''}" data-n="all">All</button>
          <input type="number" min="0" max="${list.length}" step="1" value="${cur === 'all' ? list.length : Math.min(cur, list.length)}" aria-label="Slides from ${esc(course)}">`;
        row.addEventListener('click', (e) => {
          const b = e.target.closest('button[data-n]');
          if (!b) return;
          settings.perCourse[course] = b.dataset.n === 'all' ? 'all' : +b.dataset.n;
          persistSettings(); renderCounts(); renderSummary();
        });
        $('input', row).addEventListener('change', (e) => {
          let v = Math.round(Number(e.target.value));
          if (!isFinite(v) || v < 0) v = 0;
          settings.perCourse[course] = v >= list.length ? 'all' : v;
          persistSettings(); renderCounts(); renderSummary();
        });
        pc.appendChild(row);
      }
    }
    // Order only matters with more than one practical
    const multi = groups.size > 1;
    $('#order-row').hidden = !multi || (settings.mode === 'study' && !settings.studyShuffle);
    $('#order-note').textContent = settings.order === 'mixed'
      ? 'Slides from all the selected practicals are shuffled together, so the session jumps between them.'
      : 'Each practical is done as its own block (in the order above), shuffled inside the block.';
  }

  function perCourseValue(course) {
    const v = settings.perCourse[course];
    return v === 'all' || (typeof v === 'number' && v >= 0) ? v : PER_DEFAULT;
  }

  /** Usable items (exam modes skip unlabelled ones) grouped by course, in course order. */
  function usableByCourse(items) {
    items = items || selectedItems();
    const exam = settings.mode !== 'study';
    const map = new Map();
    for (const c of COURSES) {
      const list = items.filter((i) => i.course === c.name && (!exam || !i.unlabelled));
      if (list.length) map.set(c.name, list);
    }
    return map;
  }

  /** How many slides to take from each practical. Same total = spread evenly across practicals. */
  function planCounts(groups, cfg) {
    const plan = new Map();
    if (cfg.countMode === 'per') {
      for (const [course, list] of groups) {
        const v = cfg.perCourse[course];
        const n = v === 'all' ? list.length : Math.min(typeof v === 'number' ? v : PER_DEFAULT, list.length);
        if (n > 0) plan.set(course, n);
      }
      return plan;
    }
    const avail = [...groups.values()].reduce((s, l) => s + l.length, 0);
    let left = cfg.count === 'all' ? avail : Math.min(cfg.count, avail);
    for (const c of groups.keys()) plan.set(c, 0);
    while (left > 0) { // round-robin: one from each practical in turn until the total is reached
      let progressed = false;
      for (const [c, list] of groups) {
        if (left > 0 && plan.get(c) < list.length) { plan.set(c, plan.get(c) + 1); left--; progressed = true; }
      }
      if (!progressed) break;
    }
    for (const [c, n] of [...plan]) if (!n) plan.delete(c);
    return plan;
  }

  /** Items matching the current selection. */
  function selectedItems() {
    return ITEMS.filter((it) => selCourses.has(it.course) && selCats.has(catKey(it.course, it.category)));
  }

  function selectionText(items) {
    const byCourse = new Map();
    for (const it of items) {
      if (!byCourse.has(it.course)) byCourse.set(it.course, new Set());
      byCourse.get(it.course).add(it.category);
    }
    const parts = [];
    for (const c of COURSES) {
      if (!byCourse.has(c.name)) continue;
      const cats = byCourse.get(c.name);
      const all = c.categories.every((x) => cats.has(x.name));
      parts.push(all && c.categories.length > 1
        ? `${c.name} (all ${c.categories.length} categories)`
        : `${c.name} (${[...cats].map(catName).join(', ')})`);
    }
    return parts.join(' + ');
  }

  function renderSummary() {
    renderCounts(); // per-practical rows depend on the course/category selection and mode
    const items = selectedItems();
    const exam = settings.mode !== 'study';
    const usable = exam ? items.filter((i) => !i.unlabelled) : items;
    const el = $('#summary');
    const start = $('#start-btn');
    if (!items.length) {
      el.innerHTML = '<span class="warn-text">Choose at least one course and category.</span>';
      start.disabled = true;
      return;
    }
    if (!usable.length) {
      el.innerHTML = '<span class="warn-text">The selected images are all unlabelled. Use Study mode, or rename them first.</span>';
      start.disabled = true;
      return;
    }
    const plan = planCounts(usableByCourse(items), settings);
    const n = [...plan.values()].reduce((a, b) => a + b, 0);
    if (!n) {
      el.innerHTML = '<span class="warn-text">Set at least one practical to more than 0 slides.</span>';
      start.disabled = true;
      return;
    }
    let txt = `<strong>${plural(usable.length, 'image')}</strong> from ${esc(selectionText(usable))}`;
    txt += ` · <strong>${n}</strong> slide${n === 1 ? '' : 's'}`;
    if (plan.size > 1) {
      txt += ` (${[...plan].map(([c, k]) => `${esc(c)} ${k}`).join(', ')})`;
      if (!(settings.mode === 'study' && !settings.studyShuffle)) txt += settings.order === 'mixed' ? ' · practicals mixed' : ' · one practical at a time';
    }
    txt += ` · ${MODE_NAMES[settings.mode]} · ${settings.timer ? fmtTime(settings.timer) + ' per slide' : 'no timer'}`;
    const skipped = items.length - usable.length;
    if (skipped) txt += ` <span class="note">(${skipped} unlabelled skipped)</span>`;
    el.innerHTML = txt;
    start.disabled = false;
  }

  function renderHistory() {
    const hist = load(KEY_HISTORY, []);
    const wrap = $('#history');
    $('#history-clear').hidden = !hist.length;
    if (!hist.length) {
      wrap.innerHTML = '<p class="note">No sessions yet.</p>';
      return;
    }
    wrap.innerHTML = hist.slice(0, 30).map((h) => {
      const d = new Date(h.date);
      const when = isNaN(d) ? '' : d.toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
      const score = h.unmarked ? 'not marked' : h.possible ? `${fmtNum(h.earned)}/${h.possible} (${Math.round((h.earned / h.possible) * 100)}%)` : '—';
      return `<div class="history-row"><span>${esc(when)} · <strong>${esc(MODE_NAMES[h.mode] || h.mode)}</strong> · ${plural(h.slides, 'slide')}${h.retry ? ' · retry' : ''}</span>
        <span class="h-score">${score}</span><span class="h-meta">${esc(h.cats || '')}</span></div>`;
    }).join('');
  }
  const fmtNum = (n) => (Math.round(n * 10) / 10).toString();

  // ---------------------------------------------------------------- session building
  const S = {
    config: null, // {mode, timer, beep, items (ids) | null, retry}
    slides: [], // {item, qs:[{q,a,hint,options,correctIdx,identify}], ans:[] }
    allSlides: null, // study mode unfiltered
    idx: 0,
    maxIdx: 0,
    histId: null,
    lastNav: 0,
  };

  function isIdentify(q, item) {
    if (q.auto) return true;
    if (/^\s*(identify|spot|name the (specimen|slide|organism|lesion|condition|item|equipment|cell)|what is (this|the (specimen|slide|organism|lesion|condition)))/i.test(q.q)) return true;
    return norm(q.a) && norm(q.a) === norm(item.label);
  }

  function distractors(correct, item, need) {
    const target = norm(correct);
    const seen = new Set([target]);
    const out = [];
    const tiers = [
      ITEMS.filter((x) => x.course === item.course && x.category === item.category),
      ITEMS.filter((x) => x.course === item.course && x.category !== item.category),
      ITEMS.filter((x) => x.course !== item.course),
    ];
    for (const tier of tiers) {
      for (const x of shuffle(tier.slice())) {
        if (out.length >= need) return out;
        if (x.unlabelled) continue;
        const n = norm(x.label);
        if (!n || seen.has(n)) continue;
        seen.add(n);
        out.push(x.label);
      }
    }
    return out;
  }

  function buildQuestions(item, mode) {
    let src = item.questions && item.questions.length ? item.questions : null;
    if (!src) {
      const kind = item.type || 'specimen';
      src = [{ q: `Identify this ${kind}`, a: item.label, auto: true }];
    }
    return src.map((q) => {
      const out = { q: q.q, a: q.a || '', hint: q.hint || '', identify: isIdentify(q, item) };
      if (!out.hint && out.identify && item.label) {
        const where = catName(item.category) + (item.sub ? ' › ' + item.sub : '');
        out.hint = `Area: ${where}. The answer starts with “${String(out.a || item.label).trim().charAt(0).toUpperCase()}”.`;
      }
      if (mode === 'easy') {
        let opts = null;
        if (Array.isArray(q.options) && q.options.length >= 2) {
          opts = q.options.slice();
          if (!opts.some((o) => norm(o) === norm(out.a))) opts.push(out.a);
        } else if (out.identify && out.a) {
          opts = [out.a].concat(distractors(out.a, item, 3));
        }
        if (opts && opts.length >= 2) {
          // Same look for every option: first letter capital, so none stands out.
          opts = opts.map((o) => { o = String(o).trim(); return o.charAt(0).toUpperCase() + o.slice(1); });
          shuffle(opts);
          out.options = opts;
          out.correctIdx = opts.findIndex((o) => norm(o) === norm(out.a));
        }
      }
      return out;
    });
  }

  function startSession(config) {
    S.config = config;
    let pool;
    if (config.itemIds) {
      pool = config.itemIds.map((id) => ITEMS[id]).filter(Boolean);
    } else {
      const groups = usableByCourse();
      const plan = planCounts(groups, config);
      pool = [];
      for (const [course, n] of plan) pool = pool.concat(shuffle(groups.get(course).slice()).slice(0, n));
    }
    if (!pool.length) return;
    let ordered;
    if (config.mode === 'study' && !config.studyShuffle) {
      const rank = (c) => COURSES.findIndex((x) => x.name === c);
      ordered = pool.slice().sort((a, b) => rank(a.course) - rank(b.course) || a.category.localeCompare(b.category) ||
        String(a.sub || '').localeCompare(String(b.sub || '')) || a.label.localeCompare(b.label));
    } else {
      // Each practical: shuffled, no two slides from the same category in a row.
      const rank = (c) => COURSES.findIndex((x) => x.name === c);
      const courses = [...new Set(pool.map((i) => i.course))].sort((a, b) => rank(a) - rank(b));
      const blocks = courses.map((c) => spreadByCategory(shuffle(pool.filter((i) => i.course === c))));
      ordered = config.order === 'blocks'
        ? [].concat(...blocks) // one practical after another
        : spreadByCategory([].concat(...blocks), (it) => it.course); // interleave practicals, keeping each block's order
    }
    S.blockCount = new Set(ordered.map((i) => i.course)).size;
    S.slides = ordered.map((item) => ({ item, qs: buildQuestions(item, config.mode), ans: [], hints: false }));
    S.allSlides = config.mode === 'study' ? S.slides.slice() : null;
    S.idx = 0;
    S.maxIdx = 0;
    S.histId = null;
    S.finished = false;
    setupExamChrome();
    showScreen('exam');
    showSlide(0);
  }

  function configFromSettings() {
    return {
      mode: settings.mode,
      timer: settings.mode === 'distinction' && !settings.timer ? DISTINCTION_DEFAULT : settings.timer,
      beep: settings.beep,
      count: settings.count,
      countMode: settings.countMode,
      perCourse: Object.assign({}, settings.perCourse),
      order: settings.order,
      studyShuffle: settings.studyShuffle,
      answerBoxes: !!settings.answerBoxes,
      selection: selectionText(selectedItems()),
      itemIds: null,
    };
  }

  // ---------------------------------------------------------------- screens
  function showScreen(name) {
    for (const id of ['home', 'exam', 'results']) $('#' + id).hidden = id !== name;
    document.body.className = document.body.className.replace(/\bscreen-\w+/g, '').trim() + ' screen-' + name;
    if (name === 'home') renderModes();
    window.scrollTo(0, 0);
  }

  function setupExamChrome() {
    const m = S.config.mode;
    $('#prev-btn').hidden = m === 'distinction';
    $('#hint-btn').hidden = m !== 'easy';
    $('#pause-btn').hidden = m === 'distinction' || !S.config.timer;
    $('#study-filter').hidden = m !== 'study';
    $('#boxes-btn').hidden = m !== 'distinction';
    $('#boxes-btn').classList.toggle('on', !!S.config.answerBoxes);
    if (m === 'study') {
      const sel = $('#study-filter');
      const counts = new Map();
      for (const s of S.allSlides) {
        const k = catKey(s.item.course, s.item.category);
        counts.set(k, (counts.get(k) || 0) + 1);
      }
      sel.innerHTML = `<option value="">All categories (${S.allSlides.length})</option>` +
        [...counts.entries()].map(([k, n]) => {
          const [c, cat] = k.split(SEP);
          return `<option value="${esc(k)}">${esc(c)} › ${esc(catName(cat))} (${n})</option>`;
        }).join('');
      sel.value = '';
    }
  }

  // ---------------------------------------------------------------- exam display
  const img = $('#slide-img');
  let preloadImg = null;

  function showSlide(i) {
    stopTimer();
    resetZoom();
    setPaused(false);
    S.idx = i;
    S.maxIdx = Math.max(S.maxIdx, i);
    S.lastNav = Date.now();
    const slide = S.slides[i];
    const it = slide.item;
    const m = S.config.mode;
    const exam = m !== 'study';

    $('#progress').textContent = `Slide ${i + 1} / ${S.slides.length}`;
    showBlockToast(i);
    const tag = $('#course-tag');
    tag.textContent = exam ? it.course : `${it.course} › ${catName(it.category)}`;
    tag.style.setProperty('--c', courseColor(it.course));

    // Image — never put the label in alt/title during exam modes.
    $('#img-loading').hidden = false;
    $('#img-loading').textContent = 'Loading…';
    img.style.visibility = 'hidden';
    img.alt = exam ? `Exam image ${i + 1}` : it.label;
    img.removeAttribute('title');
    img.onload = () => { $('#img-loading').hidden = true; img.style.visibility = 'visible'; };
    img.onerror = () => { $('#img-loading').textContent = 'Image could not be loaded. Re-run node build-bank.js'; };
    img.src = it.src;
    // Preload only the next slide.
    const next = S.slides[i + 1];
    if (next) { preloadImg = new Image(); preloadImg.src = next.item.src; }

    // Study label
    const lab = $('#study-label');
    lab.hidden = exam;
    if (!exam) {
      const typ = it.type ? it.type.charAt(0).toUpperCase() + it.type.slice(1) : '';
      lab.innerHTML = `${esc(it.label)}<span class="meta">${esc(it.course)} › ${esc(catName(it.category))}${it.sub ? ' › ' + esc(it.sub) : ''}${typ ? ' · ' + esc(typ) : ''}</span>`;
    }
    const notes = $('#study-notes');
    notes.hidden = exam || !(it.notes && it.notes.length);
    if (!notes.hidden) notes.innerHTML = '<strong>Notes</strong><ul>' + it.notes.map((n) => `<li>${esc(n)}</li>`).join('') + '</ul>';

    renderQuestions();
    $('#panel').scrollTop = 0;

    $('#prev-btn').disabled = i === 0;
    $('#next-btn').textContent = i === S.slides.length - 1 ? (m === 'study' ? 'Finish' : 'Finish ✓') : 'Next →';
    $('#hint-btn').disabled = !slide.qs.some((q) => q.hint);
    $('#hint-btn').textContent = slide.hints ? '💡 Hide hint' : '💡 Hint';
    startTimer();
  }

  let toastTimer = null;
  function showBlockToast(i) {
    const toast = $('#block-toast');
    const cur = S.slides[i].item.course;
    const prevCourse = i > 0 ? S.slides[i - 1].item.course : null;
    if (S.config.order !== 'blocks' || S.blockCount < 2 || cur === prevCourse || S.config.mode === 'study') {
      if (i === 0 || cur !== prevCourse) toast.hidden = true;
      return;
    }
    const n = [...new Set(S.slides.slice(0, i + 1).map((s) => s.item.course))].length;
    toast.textContent = `Practical ${n} of ${S.blockCount}: ${cur}`;
    toast.style.setProperty('--c', courseColor(cur));
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 3000);
  }

  function renderQuestions() {
    const slide = S.slides[S.idx];
    const m = S.config.mode;
    const list = $('#questions');
    list.innerHTML = '';
    const paper = m === 'distinction' && !S.config.answerBoxes;
    let note = $('#paper-note');
    if (!note) {
      note = document.createElement('p');
      note.id = 'paper-note';
      note.className = 'paper-note';
      list.parentNode.insertBefore(note, list);
    }
    note.hidden = !paper;
    if (paper) note.textContent = `✎ Write your answers on paper as “Slide ${S.idx + 1}”. All answers are shown at the end.`;
    slide.qs.forEach((q, qi) => {
      const li = document.createElement('li');
      const a = slide.ans[qi] || {};
      let html = `<div class="q-text">${esc(q.q)}</div>`;
      if (m === 'study') {
        html += `<div class="q-answer">${esc(q.a || '—')}</div>`;
        if (q.hint && !q.identify) html += `<div class="q-hint">${esc(q.hint)}</div>`;
      } else if (m === 'easy') {
        if (q.options) {
          html += '<div class="options">' + q.options.map((o, oi) => {
            let cls = 'opt';
            if (a.choice != null) {
              if (oi === q.correctIdx) cls += ' correct';
              else if (oi === a.choice) cls += ' wrong';
              else cls += ' dim';
            }
            return `<button type="button" class="${cls}" data-q="${qi}" data-o="${oi}" ${a.choice != null ? 'disabled' : ''}><span class="k">${oi + 1}</span><span>${esc(o)}</span></button>`;
          }).join('') + '</div>';
          if (a.choice != null) {
            html += a.correct ? '<div class="feedback ok">✓ Correct</div>'
              : `<div class="feedback bad">✗ Wrong — answer: ${esc(q.a)}</div>`;
          }
        } else {
          // Open question: reveal, then self-mark.
          if (!a.revealed) {
            html += `<div class="reveal-row"><button type="button" data-reveal="${qi}">Show answer</button></div>`;
          } else {
            html += `<div class="q-answer">${esc(q.a || '—')}</div>
              <div class="reveal-row"><button type="button" class="yes ${a.self === true ? 'on' : ''}" data-self="${qi}" data-v="1">✓ I got it</button>
              <button type="button" class="no ${a.self === false ? 'on' : ''}" data-self="${qi}" data-v="0">✗ I missed it</button></div>`;
          }
        }
        if (slide.hints && q.hint) html += `<div class="q-hint">💡 ${esc(q.hint)}</div>`;
      } else if (S.config.answerBoxes) {
        html += `<textarea class="answer-box" data-q="${qi}" rows="2" placeholder="Type your answer (optional)" autocomplete="off" autocorrect="off" spellcheck="false"></textarea>`;
      }
      li.innerHTML = html;
      list.appendChild(li);
      const ta = $('textarea', li);
      if (ta) {
        ta.value = a.text || '';
        ta.addEventListener('input', () => { slide.ans[qi] = Object.assign(slide.ans[qi] || {}, { text: ta.value }); });
      }
    });
  }

  function pickOption(qi, oi) {
    const slide = S.slides[S.idx];
    const q = slide.qs[qi];
    if (!q || !q.options || (slide.ans[qi] && slide.ans[qi].choice != null)) return;
    slide.ans[qi] = { choice: oi, correct: oi === q.correctIdx };
    renderQuestions();
  }

  $('#questions').addEventListener('click', (e) => {
    const opt = e.target.closest('.opt');
    if (opt && !opt.disabled) { pickOption(+opt.dataset.q, +opt.dataset.o); return; }
    const rev = e.target.closest('[data-reveal]');
    if (rev) {
      const slide = S.slides[S.idx];
      const qi = +rev.dataset.reveal;
      slide.ans[qi] = Object.assign(slide.ans[qi] || {}, { revealed: true });
      renderQuestions();
      return;
    }
    const self = e.target.closest('[data-self]');
    if (self) {
      const slide = S.slides[S.idx];
      const qi = +self.dataset.self;
      slide.ans[qi] = Object.assign(slide.ans[qi] || {}, { self: self.dataset.v === '1' });
      renderQuestions();
    }
  });

  function next(auto) {
    if (!S.slides.length || $('#exam').hidden) return;
    // Guard against an accidental double-tap skipping a slide in Distinction.
    if (!auto && S.config.mode === 'distinction' && Date.now() - S.lastNav < 700) return;
    if (S.idx < S.slides.length - 1) {
      showSlide(S.idx + 1);
    } else if (auto || S.config.mode === 'study' || window.confirm('Finish the session and see your results?')) {
      finish();
    }
  }
  function prev() {
    if (S.config.mode === 'distinction') return; // forward only
    if (S.idx > 0) showSlide(S.idx - 1);
  }
  function toggleHint() {
    if (S.config.mode !== 'easy') return;
    const slide = S.slides[S.idx];
    slide.hints = !slide.hints;
    if (slide.hints) slide.hintUsed = true;
    $('#hint-btn').textContent = slide.hints ? '💡 Hide hint' : '💡 Hint';
    renderQuestions();
  }

  $('#next-btn').addEventListener('click', () => next(false));
  $('#prev-btn').addEventListener('click', prev);
  $('#hint-btn').addEventListener('click', toggleHint);
  $('#end-btn').addEventListener('click', () => {
    if (S.config.mode === 'study') { stopTimer(); exitFullscreen(); showScreen('home'); renderHome(); return; }
    if (window.confirm('End this session now? Slides you have not reached will not be scored.')) finish(true);
  });
  $('#study-filter').addEventListener('change', (e) => {
    const k = e.target.value;
    S.slides = k ? S.allSlides.filter((s) => catKey(s.item.course, s.item.category) === k) : S.allSlides.slice();
    S.maxIdx = 0;
    showSlide(0);
  });

  // ---------------------------------------------------------------- timer
  const T = { total: 0, endAt: 0, remaining: 0, paused: false, iv: null, beeped: {} };
  const timerEl = $('#timer');

  function startTimer() {
    T.total = S.config.timer * 1000;
    T.beeped = {};
    timerEl.className = 'timer';
    if (!T.total) {
      timerEl.textContent = S.config.mode === 'study' ? '' : 'No timer';
      timerEl.classList.add('off');
      return;
    }
    T.endAt = Date.now() + T.total;
    T.paused = false;
    tick();
    T.iv = setInterval(tick, 200);
  }
  function stopTimer() {
    if (T.iv) clearInterval(T.iv);
    T.iv = null;
  }
  function tick() {
    if (T.paused || !T.total) return;
    const rem = Math.max(0, T.endAt - Date.now());
    timerEl.textContent = fmtClock(rem);
    timerEl.classList.toggle('red', rem <= 10000);
    timerEl.classList.toggle('amber', rem > 10000 && rem <= T.total * 0.25);
    const secs = Math.ceil(rem / 1000);
    if (S.config.beep) {
      if (secs === 10 && T.total > 12000 && !T.beeped[10]) { T.beeped[10] = 1; beep(880, 0.15); }
      if (secs <= 3 && secs >= 1 && !T.beeped[secs]) { T.beeped[secs] = 1; beep(660, 0.08); }
    }
    if (rem <= 0) {
      stopTimer();
      if (S.config.beep) beep(440, 0.45);
      next(true);
    }
  }
  function setPaused(p) {
    if (p && (S.config.mode === 'distinction' || !T.total)) return;
    if (p === T.paused) { $('#pause-overlay').hidden = !p; return; }
    T.paused = p;
    if (p) {
      T.remaining = Math.max(0, T.endAt - Date.now());
    } else if (T.total) {
      T.endAt = Date.now() + T.remaining;
    }
    $('#pause-overlay').hidden = !p;
    timerEl.classList.toggle('paused', p);
    $('#pause-btn').textContent = p ? '▶' : '❚❚';
  }
  $('#pause-btn').addEventListener('click', () => setPaused(!T.paused));
  $('#boxes-btn').addEventListener('click', () => {
    // Switch answer boxes on/off mid-exam; anything already typed is kept.
    S.config.answerBoxes = !S.config.answerBoxes;
    settings.answerBoxes = S.config.answerBoxes;
    persistSettings();
    $('#boxes-btn').classList.toggle('on', S.config.answerBoxes);
    renderQuestions();
  });
  $('#resume-btn').addEventListener('click', () => setPaused(false));

  let audioCtx = null;
  function unlockAudio() {
    try {
      if (!audioCtx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) audioCtx = new AC();
      }
      if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    } catch (e) { audioCtx = null; }
  }
  function beep(freq, dur) {
    try {
      if (!audioCtx) return;
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.frequency.value = freq;
      o.type = 'sine';
      g.gain.setValueAtTime(0.0001, audioCtx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.3, audioCtx.currentTime + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + dur);
      o.connect(g); g.connect(audioCtx.destination);
      o.start(); o.stop(audioCtx.currentTime + dur + 0.05);
    } catch (e) { /* ignore */ }
  }

  // ---------------------------------------------------------------- zoom (click / pinch / wheel / drag)
  const stage = $('#stage');
  const Z = { s: 1, x: 0, y: 0 };
  const pointers = new Map();
  let gesture = null;

  function applyZoom() {
    const w = stage.clientWidth;
    const h = stage.clientHeight;
    Z.s = Math.min(8, Math.max(1, Z.s));
    Z.x = Math.min(0, Math.max(w - w * Z.s, Z.x));
    Z.y = Math.min(0, Math.max(h - h * Z.s, Z.y));
    img.style.transform = Z.s === 1 ? '' : `translate(${Z.x}px, ${Z.y}px) scale(${Z.s})`;
    stage.classList.toggle('zoomed', Z.s > 1);
  }
  function zoomAt(newS, px, py) {
    newS = Math.min(8, Math.max(1, newS));
    Z.x = px - (px - Z.x) * (newS / Z.s);
    Z.y = py - (py - Z.y) * (newS / Z.s);
    Z.s = newS;
    applyZoom();
  }
  function resetZoom() { Z.s = 1; Z.x = 0; Z.y = 0; applyZoom(); }
  function localPoint(e) {
    const r = stage.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  stage.addEventListener('contextmenu', (e) => e.preventDefault());
  stage.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button')) return;
    stage.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, localPoint(e));
    if (pointers.size === 1) {
      const p = localPoint(e);
      gesture = { type: 'pan', sx: p.x, sy: p.y, ox: Z.x, oy: Z.y, t: Date.now(), moved: false };
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      gesture = { type: 'pinch', d: Math.hypot(a.x - b.x, a.y - b.y) || 1, s: Z.s, moved: true };
    }
  });
  stage.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId) || !gesture) return;
    pointers.set(e.pointerId, localPoint(e));
    if (gesture.type === 'pinch' && pointers.size >= 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      zoomAt(gesture.s * (d / gesture.d), (a.x + b.x) / 2, (a.y + b.y) / 2);
    } else if (gesture.type === 'pan') {
      const p = localPoint(e);
      const dx = p.x - gesture.sx;
      const dy = p.y - gesture.sy;
      if (Math.abs(dx) + Math.abs(dy) > 6) gesture.moved = true;
      if (Z.s > 1) { Z.x = gesture.ox + dx; Z.y = gesture.oy + dy; applyZoom(); }
    }
  });
  function endPointer(e) {
    if (!pointers.has(e.pointerId)) return;
    const p = localPoint(e);
    pointers.delete(e.pointerId);
    if (gesture && gesture.type === 'pan' && !gesture.moved && Date.now() - gesture.t < 400 && e.type === 'pointerup') {
      if (Z.s > 1) resetZoom(); else zoomAt(2.5, p.x, p.y);
    }
    if (pointers.size === 1) {
      const rest = [...pointers.values()][0];
      gesture = { type: 'pan', sx: rest.x, sy: rest.y, ox: Z.x, oy: Z.y, t: 0, moved: true };
    } else if (!pointers.size) {
      gesture = null;
    }
  }
  stage.addEventListener('pointerup', endPointer);
  stage.addEventListener('pointercancel', endPointer);
  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    const p = localPoint(e);
    zoomAt(Z.s * (e.deltaY < 0 ? 1.2 : 1 / 1.2), p.x, p.y);
  }, { passive: false });
  $$('.zoom-ctrls button').forEach((b) => b.addEventListener('click', () => {
    const w = stage.clientWidth / 2;
    const h = stage.clientHeight / 2;
    if (b.dataset.zoom === 'in') zoomAt(Z.s * 1.5, w, h);
    else if (b.dataset.zoom === 'out') zoomAt(Z.s / 1.5, w, h);
    else resetZoom();
  }));
  window.addEventListener('resize', applyZoom);

  // ---------------------------------------------------------------- fullscreen
  function isFullscreen() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }
  function toggleFullscreen() {
    try {
      if (isFullscreen()) { exitFullscreen(); return; }
      const el = document.documentElement;
      const req = el.requestFullscreen || el.webkitRequestFullscreen;
      if (req) {
        const r = req.call(el);
        if (r && r.catch) r.catch(() => {});
      }
    } catch (e) { /* not supported (e.g. iPhone Safari) */ }
  }
  function exitFullscreen() {
    try {
      if (!isFullscreen()) return;
      const ex = document.exitFullscreen || document.webkitExitFullscreen;
      if (ex) { const r = ex.call(document); if (r && r.catch) r.catch(() => {}); }
    } catch (e) { /* ignore */ }
  }
  $('#fs-btn').addEventListener('click', toggleFullscreen);

  // ---------------------------------------------------------------- results
  function slideScore(slide) {
    const m = S.config.mode;
    let earned = 0;
    let possible = 0;
    let unmarked = 0;
    slide.qs.forEach((q, qi) => {
      const a = slide.ans[qi] || {};
      possible += 1;
      if (m === 'easy') {
        if (q.options) earned += a.correct ? 1 : 0;
        else earned += a.self === true ? 1 : 0;
      } else if (m === 'distinction') {
        if (a.mark == null) unmarked++;
        else earned += a.mark;
      }
    });
    return { earned, possible, unmarked };
  }

  function scoredSlides() {
    return S.slides.slice(0, S.maxIdx + 1);
  }

  function finish() {
    stopTimer();
    setPaused(false);
    S.finished = true;
    exitFullscreen();
    if (S.config.mode === 'study') { showScreen('home'); renderHome(); return; }
    S.histId = 'h' + Date.now();
    renderResults();
    showScreen('results');
  }

  function totals() {
    let earned = 0;
    let possible = 0;
    let unmarked = 0;
    const byCourse = new Map();
    const byCat = new Map();
    for (const s of scoredSlides()) {
      const sc = slideScore(s);
      earned += sc.earned; possible += sc.possible; unmarked += sc.unmarked;
      const add = (map, k) => {
        const v = map.get(k) || { e: 0, p: 0 };
        v.e += sc.earned; v.p += sc.possible; map.set(k, v);
      };
      add(byCourse, s.item.course);
      add(byCat, catKey(s.item.course, s.item.category));
    }
    return { earned, possible, unmarked, byCourse, byCat };
  }

  function saveHistory() {
    const t = totals();
    const hist = load(KEY_HISTORY, []);
    const rec = {
      id: S.histId,
      date: new Date(parseInt(S.histId.slice(1), 10)).toISOString(),
      mode: S.config.mode,
      earned: t.earned,
      possible: t.possible,
      slides: scoredSlides().length,
      cats: selectionText(scoredSlides().map((s) => s.item)),
      retry: !!S.config.retry,
      unmarked: S.config.mode === 'distinction' && t.possible > 0 && t.unmarked === t.possible,
    };
    const i = hist.findIndex((h) => h.id === rec.id);
    if (i >= 0) hist[i] = rec; else hist.unshift(rec);
    save(KEY_HISTORY, hist.slice(0, 100));
  }

  function bdTable(title, map, labelFn) {
    const rows = [...map.entries()].sort((a, b) => (a[1].e / a[1].p) - (b[1].e / b[1].p));
    return `<div class="card"><h2>${title}</h2><table class="bd-table"><tbody>` + rows.map(([k, v]) => {
      const pct = v.p ? Math.round((v.e / v.p) * 100) : 0;
      const cls = pct >= 70 ? '' : pct >= 50 ? 'mid' : 'low';
      return `<tr><td>${labelFn(k)}${pct < 50 ? '<span class="weak">weak</span>' : ''}</td>
        <td style="width:35%"><div class="bar ${cls}"><span style="width:${pct}%"></span></div></td>
        <td class="num">${fmtNum(v.e)}/${v.p} · ${pct}%</td></tr>`;
    }).join('') + '</tbody></table></div>';
  }

  function updateScoreHeader() {
    const t = totals();
    const pct = t.possible ? Math.round((t.earned / t.possible) * 100) : 0;
    const nothingMarked = S.config.mode === 'distinction' && t.possible > 0 && t.unmarked === t.possible;
    $('#breakdown').hidden = nothingMarked;
    if (nothingMarked) {
      // Paper answers not checked yet: don't show a misleading 0% or "weak" everywhere.
      $('#score-big').textContent = '—';
      $('#score-sub').textContent = `${plural(scoredSlides().length, 'slide')} · mark your answers against the answer key below to get a score` +
        (scoredSlides().length < S.slides.length ? ` · ended early (${S.slides.length - scoredSlides().length} not reached)` : '');
      $('#retry-wrong').disabled = true;
      saveHistory();
      return;
    }
    $('#score-big').textContent = `${pct}%`;
    let sub = `${fmtNum(t.earned)} / ${t.possible} marks · ${plural(scoredSlides().length, 'slide')}`;
    if (S.config.mode === 'distinction' && t.unmarked) sub += ` · ${t.unmarked} answer${t.unmarked === 1 ? '' : 's'} still to mark`;
    if (scoredSlides().length < S.slides.length) sub += ` · ended early (${S.slides.length - scoredSlides().length} not reached)`;
    $('#score-sub').textContent = sub;
    $('#breakdown').innerHTML = '<div class="breakdown">' +
      bdTable('By course', t.byCourse, (k) => esc(k)) +
      bdTable('By category', t.byCat, (k) => { const [c, cat] = k.split(SEP); return `${esc(catName(cat))} <span class="note">${esc(c)}</span>`; }) +
      '</div>';
    $('#retry-wrong').disabled = !scoredSlides().some((s) => { const sc = slideScore(s); return sc.earned < sc.possible; });
    saveHistory();
  }

  function renderResults() {
    const m = S.config.mode;
    $('#results-title').textContent = `${MODE_NAMES[m]} results`;
    const typed = scoredSlides().some((s) => s.ans.some((a) => a && (a.text || '').trim()));
    const showTyped = m === 'distinction' && (S.config.answerBoxes || typed);
    $('#review-title').textContent = m === 'distinction' ? 'Answer key' : 'Review';
    $('#review-help').textContent = m !== 'distinction'
      ? 'Every slide with the correct answers. Wrong answers are marked in red.'
      : (showTyped
        ? 'Compare your answers with the correct ones and mark each: ✓ = full mark, ½ = half, ✗ = wrong. The score updates as you mark.'
        : 'Check the answers you wrote on paper against this key (slide numbers match). Mark each one ✓ / ½ / ✗ if you want a score.');
    const wrap = $('#review');
    wrap.innerHTML = '';
    scoredSlides().forEach((s, si) => {
      const it = s.item;
      const div = document.createElement('div');
      div.className = 'review-item';
      let html = `<div class="pic"><img loading="lazy" src="${esc(it.src)}" alt="${esc(it.label)}" data-full="${esc(it.src)}"></div><div>
        <div class="r-label">Slide ${si + 1}: ${esc(it.label)}</div>
        <div class="r-meta">${esc(it.course)} › ${esc(catName(it.category))}${it.type ? ' · ' + esc(it.type) : ''}${s.hintUsed ? ' · hint used' : ''}</div>`;
      s.qs.forEach((q, qi) => {
        const a = s.ans[qi] || {};
        html += `<div class="r-q"><div class="qq"><span class="qnum">${qi + 1}.</span>${esc(q.q)}</div>
          <div class="row"><span class="k">Answer</span><span class="ans">${esc(q.a || '—')}</span></div>`;
        if (m === 'easy') {
          let yours;
          let tag;
          if (q.options) {
            yours = a.choice != null ? esc(q.options[a.choice]) : '<span class="yours blank">Not answered</span>';
            tag = a.correct ? '<span class="tag ok">✓</span>' : '<span class="tag bad">✗</span>';
          } else {
            yours = a.self === true ? 'Self-marked correct' : a.self === false ? 'Self-marked wrong' : '<span class="yours blank">Not answered</span>';
            tag = a.self === true ? '<span class="tag ok">✓</span>' : '<span class="tag bad">✗</span>';
          }
          html += `<div class="row"><span class="k">You</span><span>${yours} ${tag}</span></div>`;
        } else {
          const txt = (a.text || '').trim();
          if (showTyped) {
            html += `<div class="row"><span class="k">You wrote</span><span class="yours ${txt ? '' : 'blank'}">${txt ? esc(txt) : 'Nothing typed'}</span></div>`;
          }
          html += `<div class="mark-row" data-s="${si}" data-q="${qi}">
              <button type="button" data-v="1" class="${a.mark === 1 ? 'on' : ''}" aria-label="Correct">✓</button>
              <button type="button" data-v="0.5" class="${a.mark === 0.5 ? 'on' : ''}" aria-label="Half">½</button>
              <button type="button" data-v="0" class="${a.mark === 0 ? 'on' : ''}" aria-label="Wrong">✗</button></div>`;
        }
        html += '</div>';
      });
      html += '</div>';
      div.innerHTML = html;
      wrap.appendChild(div);
    });
    updateScoreHeader();
  }

  $('#review').addEventListener('click', (e) => {
    const b = e.target.closest('.mark-row button');
    if (b) {
      const row = b.parentElement;
      const s = scoredSlides()[+row.dataset.s];
      const qi = +row.dataset.q;
      s.ans[qi] = Object.assign(s.ans[qi] || {}, { mark: parseFloat(b.dataset.v) });
      $$('button', row).forEach((x) => x.classList.toggle('on', x === b));
      updateScoreHeader();
      return;
    }
    const im = e.target.closest('img[data-full]');
    if (im) { $('#lightbox-img').src = im.dataset.full; $('#lightbox').hidden = false; }
  });
  $('#lightbox').addEventListener('click', () => { $('#lightbox').hidden = true; });

  $('#retry-wrong').addEventListener('click', () => {
    const ids = scoredSlides().filter((s) => { const sc = slideScore(s); return sc.earned < sc.possible; }).map((s) => s.item.id);
    if (!ids.length) return;
    unlockAudio();
    startSession(Object.assign({}, S.config, { itemIds: ids, retry: true }));
  });
  $('#retry-all').addEventListener('click', () => {
    unlockAudio();
    const cfg = Object.assign({}, S.config);
    if (cfg.retry) cfg.itemIds = S.slides.map((s) => s.item.id);
    startSession(cfg);
  });
  $('#go-home').addEventListener('click', () => { showScreen('home'); renderHome(); });

  // ---------------------------------------------------------------- home events
  $('#courses-all').addEventListener('click', () => {
    const all = COURSES.every((c) => selCourses.has(c.name));
    if (all) {
      selCourses.clear();
    } else {
      for (const c of COURSES) {
        if (!selCourses.has(c.name)) { selCourses.add(c.name); selectAllCats(c.name); }
      }
    }
    persistSettings(); renderCourses(); renderSummary();
  });
  $$('.mode-btn').forEach((b) => b.addEventListener('click', () => {
    settings.mode = b.dataset.mode;
    persistSettings(); renderModes(); renderTimer(); renderSummary();
  }));
  $('#timer-slider').addEventListener('input', (e) => {
    settings.timer = TIMER_STEPS[+e.target.value] || 0;
    if (settings.mode === 'distinction' && !settings.timer) settings.timer = TIMER_STEPS[1];
    persistSettings(); renderTimer(); renderSummary();
  });
  $('#beep-toggle').addEventListener('change', (e) => { settings.beep = e.target.checked; persistSettings(); });
  $('#study-shuffle').addEventListener('change', (e) => { settings.studyShuffle = e.target.checked; persistSettings(); renderSummary(); });
  $$('[data-countmode]').forEach((b) => b.addEventListener('click', () => {
    settings.countMode = b.dataset.countmode; persistSettings(); renderCounts(); renderSummary();
  }));
  $$('[data-order]').forEach((b) => b.addEventListener('click', () => {
    settings.order = b.dataset.order; persistSettings(); renderCounts(); renderSummary();
  }));
  $('#answer-boxes').addEventListener('change', (e) => { settings.answerBoxes = e.target.checked; persistSettings(); });
  $('#review-pics').addEventListener('change', (e) => { $('#review').classList.toggle('no-pics', !e.target.checked); });
  $('#history-clear').addEventListener('click', () => {
    if (window.confirm('Delete all past session scores?')) { save(KEY_HISTORY, []); renderHistory(); }
  });
  $('#start-btn').addEventListener('click', () => {
    unlockAudio();
    startSession(configFromSettings());
  });

  // ---------------------------------------------------------------- keyboard
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (e.target && e.target.tagName) || '';
    if (tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT') {
      if (e.key === 'Escape') e.target.blur();
      return;
    }
    const k = e.key;
    if (k === 'f' || k === 'F') { toggleFullscreen(); e.preventDefault(); return; }
    if (!$('#lightbox').hidden && k === 'Escape') { $('#lightbox').hidden = true; return; }
    if ($('#exam').hidden) return;
    const m = S.config.mode;
    if (k === 'ArrowRight' || k === 'PageDown') { e.preventDefault(); if (!T.paused) next(false); }
    else if (k === 'ArrowLeft' || k === 'PageUp') { e.preventDefault(); if (!T.paused) prev(); }
    else if (k === ' ' || k === 'Spacebar') {
      e.preventDefault();
      if (m !== 'distinction') setPaused(!T.paused);
    } else if ((k === 'h' || k === 'H') && m === 'easy') toggleHint();
    else if (/^[1-9]$/.test(k) && m === 'easy' && !T.paused) {
      const slide = S.slides[S.idx];
      const qi = slide.qs.findIndex((q, i) => q.options && !(slide.ans[i] && slide.ans[i].choice != null));
      if (qi >= 0 && +k <= slide.qs[qi].options.length) pickOption(qi, +k - 1);
    } else if (k === 'Escape') resetZoom();
  });

  // Warn before leaving mid-exam
  window.addEventListener('beforeunload', (e) => {
    if (!$('#exam').hidden && S.config && S.config.mode !== 'study') { e.preventDefault(); e.returnValue = ''; }
  });

  // Test hook (used by the automated checks; harmless otherwise)
  window.__PP = { S, T, spreadByCategory, distractors, buildQuestions, ITEMS };

  renderHome();
})();

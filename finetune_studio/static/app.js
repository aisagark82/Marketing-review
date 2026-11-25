/* Fine-Tune Studio — front end (vanilla JS, no build step). Every form is rendered from /api/schema. */
'use strict';

// ───────────────────────── icons (Lucide-style strokes) ─────────────────────────
const ICONS = {
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  'git-merge': '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M6 21V9a9 9 0 0 0 9 9"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  server: '<rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><path d="M6 6h.01M6 18h.01"/>',
  'git-branch': '<path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
  'check-circle': '<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/><path d="M22 4 12 14l-3-3"/>',
  package: '<path d="m16.5 9.4-9-5.2M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.3 7 12 12l8.7-5M12 22V12"/>',
  radio: '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.5M7.8 16.2a6 6 0 0 1 0-8.5M19.1 4.9a10 10 0 0 1 0 14.2M4.9 19.1a10 10 0 0 1 0-14.2"/>',
  code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
  sparkles: '<path d="M12 3l1.9 5.8L20 10.7l-6.1 1.9L12 18.5l-1.9-5.9L4 10.7l6.1-1.9z"/><path d="M19 3v4M21 5h-4M5 17v4M7 19H3"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  alert: '<path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3z"/><path d="M12 9v4M12 17h.01"/>',
  error: '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
  contrast: '<circle cx="12" cy="12" r="10"/><path d="M12 2v20a10 10 0 0 0 0-20z" fill="currentColor"/>',
  reset: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  arrowR: '<path d="M5 12h14M12 5l7 7-7 7"/>',
  arrowL: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  circle: '<circle cx="12" cy="12" r="9"/>',
  flask: '<path d="M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21.5h11.6a2 2 0 0 0 1.7-3L14 9V3"/><path d="M7 15h10"/>',
};
const icon = (n) => `<i data-icon="${n}"><svg viewBox="0 0 24 24">${ICONS[n] || ''}</svg></i>`;
function hydrateIcons(root = document) {
  root.querySelectorAll('i[data-icon]:not(:has(svg))').forEach((el) => { el.innerHTML = `<svg viewBox="0 0 24 24">${ICONS[el.dataset.icon] || ''}</svg>`; });
}

// ───────────────────────── utilities ─────────────────────────
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).error; } catch { /* */ } throw new Error(m); }
  return r.json();
}
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
const fmtB = (n) => n >= 1e9 ? (n / 1e9).toFixed(n >= 1e10 ? 1 : 2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(Math.round(n));
const fmtTok = (n) => n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : (n / 1e3).toFixed(0) + 'K';
const fmtH = (h) => h < 1 / 60 ? '< 1 min' : h < 1 ? Math.round(h * 60) + ' min' : h < 48 ? h.toFixed(1) + ' h' : (h / 24).toFixed(1) + ' days';
const fmtUSD = (x) => x < 10 ? '$' + x.toFixed(2) : '$' + Math.round(x).toLocaleString();
function fmtVal(v) {
  if (Array.isArray(v)) return v.join(', ') || '—';
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  if (typeof v === 'number' && v !== 0 && Math.abs(v) < 1e-3) return v.toExponential().replace('e-', 'e-');
  return v === null || v === '' ? '—' : String(v);
}
function toast(msg) {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg;
  $('#toasts').append(t); setTimeout(() => t.remove(), 2600);
}

// ───────────────────────── state ─────────────────────────
const S = {
  schema: null, fields: {}, stageOf: {}, defaults: {},
  cfg: {}, mode: store.get('fts-mode', 'essential'), stage: store.get('fts-stage', 'objective'),
  analysis: null, issuesByKey: {}, files: null, fileTab: 'train.py',
};
const PHASES = [['Plan', ['objective', 'data', 'model']], ['Build', ['technique', 'alignment', 'training', 'compute', 'tracking']],
  ['Validate', ['ft_testing', 'evaluation']], ['Ship', ['export', 'deploy']]];
const CARD_KEYS = new Set(['method', 'objective', 'data_kind', 'task_type']);

function matches(show, cfg) {
  if (!show) return true;
  return Object.entries(show).every(([k, vals]) => {
    const v = cfg[k];
    return Array.isArray(v) ? v.some((x) => vals.includes(x)) : vals.includes(v);
  });
}
const isModified = (k) => !same(S.cfg[k], S.defaults[k]);
const fieldShown = (f, cfg = S.cfg) => matches(f.show, cfg) && (S.mode === 'expert' || !f.adv || isModified(f.key));

function saveCfg() { store.set('fts-config', S.cfg); }
function setValue(key, value, { silent = false } = {}) {
  S.cfg[key] = value;
  saveCfg();
  if (key === 'project_name') $('#projectName').value = value;
  if (!silent) { refreshVisibility(); refreshModified(key); scheduleAnalyze(); }
}
function applyPatch(patch, label) {
  Object.entries(patch).forEach(([k, v]) => { if (k in S.fields || k in S.defaults) S.cfg[k] = v; });
  saveCfg(); $('#projectName').value = S.cfg.project_name || '';
  renderStage(); analyze();
  if (label) toast(label);
}

// ───────────────────────── rail ─────────────────────────
function renderRail() {
  const counts = {};
  Object.entries(S.issuesByKey).forEach(([k, list]) => list.forEach((i) => {
    const st = S.stageOf[k] || i.stage; counts[st] = counts[st] || { error: 0, warn: 0 };
    if (i.level in counts[st]) counts[st][i.level]++;
  }));
  const mods = {};
  Object.keys(S.fields).forEach((k) => { if (isModified(k)) mods[S.stageOf[k]] = (mods[S.stageOf[k]] || 0) + 1; });
  const stages = Object.fromEntries(S.schema.stages.map((s) => [s.id, s]));
  let n = 0, html = '';
  for (const [phase, ids] of PHASES) {
    html += `<div class="phase">${phase}</div>`;
    for (const id of ids) {
      const st = stages[id]; n++;
      const c = counts[id] || {};
      html += `<button class="step ${S.stage === id ? 'active' : ''}" data-stage="${id}" title="${esc(st.summary)}">
        <span class="num">${n}</span><span class="label">${esc(st.title)}</span><span class="badges">
        ${c.error ? `<span class="pill err" title="${c.error} error(s)">${c.error}</span>` : c.warn ? `<span class="pill warn" title="${c.warn} warning(s)">${c.warn}</span>` : ''}
        ${!c.error && !c.warn && mods[id] ? `<span class="pill mod" title="${mods[id]} changed from default">${mods[id]}</span>` : ''}</span></button>`;
    }
  }
  html += `<button class="step gen ${S.stage === 'generate' ? 'active' : ''}" data-stage="generate"><span class="num">${icon('code')}</span><span class="label">Generate pipeline</span></button>`;
  $('#rail').innerHTML = html;
}

// ───────────────────────── fields ─────────────────────────
function control(f, get, set) {
  const v = get(f.key);
  const opts = f.options || [];
  const wrap = document.createElement('div');
  wrap.className = 'ctl';
  const optIndex = (val) => opts.findIndex((o) => String(o.value) === String(val));

  if (f.type === 'select' && CARD_KEYS.has(f.key) && !f.compact) {
    wrap.className = 'choices';
    wrap.innerHTML = opts.map((o, i) => `<button type="button" class="choice ${same(o.value, v) ? 'on' : ''}" data-i="${i}"><b>${esc(o.label)}</b>${o.hint ? `<span>${esc(o.hint)}</span>` : ''}</button>`).join('');
    wrap.addEventListener('click', (e) => {
      const b = e.target.closest('.choice'); if (!b) return;
      $$('.choice', wrap).forEach((x) => x.classList.toggle('on', x === b));
      set(opts[+b.dataset.i].value);
    });
  } else if (f.type === 'select' && opts.length <= 4 && opts.every((o) => o.label.length <= 16) && !f.compact) {
    wrap.className = 'segf';
    wrap.setAttribute('role', 'radiogroup');
    wrap.innerHTML = opts.map((o, i) => `<button type="button" role="radio" aria-checked="${same(o.value, v)}" class="${same(o.value, v) ? 'on' : ''}" data-i="${i}" ${o.hint ? `data-tip="${esc(o.hint)}"` : ''}>${esc(o.label)}</button>`).join('');
    wrap.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      $$('button', wrap).forEach((x) => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); });
      set(opts[+b.dataset.i].value);
    });
  } else if (f.type === 'select') {
    const s = document.createElement('select');
    s.className = 'select'; s.id = 'f-' + f.key;
    s.innerHTML = opts.map((o, i) => `<option value="${i}" ${same(o.value, v) ? 'selected' : ''}>${esc(o.label)}${o.hint ? ' — ' + esc(o.hint) : ''}</option>`).join('');
    if (optIndex(v) < 0 && v != null) s.insertAdjacentHTML('afterbegin', `<option selected disabled>${esc(v)}</option>`);
    s.addEventListener('change', () => set(opts[+s.value].value));
    wrap.append(s);
  } else if (f.type === 'multiselect') {
    wrap.className = 'chips';
    const cur = new Set(Array.isArray(v) ? v : []);
    wrap.innerHTML = opts.map((o, i) => `<button type="button" class="chip ${cur.has(o.value) ? 'on' : ''}" aria-pressed="${cur.has(o.value)}" data-i="${i}">${esc(o.label)}</button>`).join('');
    wrap.addEventListener('click', (e) => {
      const b = e.target.closest('.chip'); if (!b) return;
      const val = opts[+b.dataset.i].value;
      const now = new Set(Array.isArray(get(f.key)) ? get(f.key) : []);
      now.has(val) ? now.delete(val) : now.add(val);
      b.classList.toggle('on', now.has(val)); b.setAttribute('aria-pressed', now.has(val));
      set(opts.map((o) => o.value).filter((x) => now.has(x)));
    });
  } else if (f.type === 'toggle') {
    wrap.innerHTML = `<label class="switch"><input type="checkbox" id="f-${f.key}" ${v ? 'checked' : ''}><span>${v ? 'On' : 'Off'}</span></label>`;
    const cb = $('input', wrap);
    cb.addEventListener('change', () => { $('span', wrap).textContent = cb.checked ? 'On' : 'Off'; set(cb.checked); });
  } else if (f.type === 'slider' && opts.length) {
    wrap.className = 'segf';
    wrap.innerHTML = opts.map((o, i) => `<button type="button" class="${same(o.value, v) ? 'on' : ''}" data-i="${i}">${esc(o.label)}</button>`).join('');
    wrap.addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      $$('button', wrap).forEach((x) => x.classList.toggle('on', x === b));
      set(opts[+b.dataset.i].value);
    });
  } else if (f.type === 'slider') {
    wrap.className = 'slider';
    wrap.innerHTML = `<input type="range" id="f-${f.key}" min="${f.min ?? 0}" max="${f.max ?? 1}" step="${f.step ?? 0.01}" value="${v ?? f.default}"><output>${v ?? f.default}</output>`;
    const r = $('input', wrap);
    r.addEventListener('input', () => { $('output', wrap).textContent = r.value; set(parseFloat(r.value)); });
  } else if (f.type === 'textarea') {
    wrap.innerHTML = `<textarea class="textarea" id="f-${f.key}" spellcheck="false">${esc(v ?? '')}</textarea>`;
    $('textarea', wrap).addEventListener('input', (e) => set(e.target.value));
  } else if (f.type === 'number' || f.type === 'int') {
    const shown = v == null ? '' : f.log ? fmtVal(v) : String(v);
    wrap.innerHTML = `<input class="input num" id="f-${f.key}" inputmode="decimal" spellcheck="false" value="${esc(shown)}" placeholder="${f.default == null ? 'auto' : esc(fmtVal(f.default))}">`;
    const inp = $('input', wrap);
    inp.addEventListener('input', () => {
      const t = inp.value.trim();
      if (t === '') return set(null);
      const n = f.type === 'int' ? Number.parseInt(t, 10) : Number(t);
      const bad = !Number.isFinite(n) || (f.type === 'int' && !/^-?\d+$/.test(t)) || (f.min != null && n < f.min) || (f.max != null && n > f.max);
      inp.style.borderColor = bad ? 'var(--err)' : '';
      inp.title = bad ? `Enter ${f.type === 'int' ? 'an integer' : 'a number'}${f.min != null ? ' ≥ ' + f.min : ''}${f.max != null ? ' ≤ ' + f.max : ''}` : '';
      if (!bad) set(n);
    });
  } else {
    wrap.innerHTML = `<input class="input" id="f-${f.key}" spellcheck="false" value="${esc(v ?? '')}">`;
    $('input', wrap).addEventListener('input', (e) => set(e.target.value));
  }
  return wrap;
}

function fieldEl(f, { get = (k) => S.cfg[k], set = (val) => setValue(f.key, val), compact = false } = {}) {
  const el = document.createElement('div');
  const wide = f.type === 'textarea' || (CARD_KEYS.has(f.key) && !compact) || (f.type === 'multiselect' && (f.options || []).length > 5);
  el.className = 'field' + (wide ? ' wide' : '');
  el.dataset.key = f.key;
  el.innerHTML = `<div class="f-label"><label for="f-${f.key}">${esc(f.label)}</label>
    ${f.help ? `<span class="info" data-tip="${esc(f.help)}" tabindex="0" aria-label="${esc(f.help)}">${icon('info')}</span>` : ''}
    ${f.adv && !compact ? '<span class="adv-tag">EXPERT</span>' : ''}
    ${compact ? '' : '<span class="modified" hidden title="Changed from default"></span><button class="reset" type="button" hidden>Reset</button>'}</div>`;
  el.append(control(compact ? { ...f, compact: true } : f, get, set));
  if (!compact) {
    el.insertAdjacentHTML('beforeend', '<div class="f-msgs"></div>');
    $('.reset', el).addEventListener('click', () => { setValue(f.key, structuredClone(S.defaults[f.key])); rerenderField(f.key); });
  }
  return el;
}
function rerenderField(key) {
  const old = $(`.field[data-key="${CSS.escape(key)}"]`, $('#main'));
  if (!old) return;
  const fresh = fieldEl(S.fields[key]);
  old.replaceWith(fresh); refreshModified(key); paintInlineIssues();
}
function refreshModified(key) {
  const keys = key ? [key] : Object.keys(S.fields);
  keys.forEach((k) => {
    const el = $(`.field[data-key="${CSS.escape(k)}"]`, $('#main')); if (!el) return;
    const m = isModified(k);
    const dot = $('.modified', el), rb = $('.reset', el);
    if (dot) dot.hidden = !m; if (rb) rb.hidden = !m;
  });
}
function refreshVisibility() {
  $$('.card[data-sec]', $('#main')).forEach((card) => {
    const sec = S.secIndex[card.dataset.sec];
    let any = false;
    $$('.field', card).forEach((el) => { const vis = fieldShown(S.fields[el.dataset.key]); el.hidden = !vis; any = any || vis; });
    card.hidden = !matches(sec.show, S.cfg) || !any;
  });
}

// ───────────────────────── stage view ─────────────────────────
function goto(id) {
  S.stage = id; store.set('fts-stage', id);
  renderRail(); renderStage(); $('#main').scrollTop = 0;
}
function renderStage() {
  const main = $('#main');
  if (S.stage === 'generate') return renderGenerate();
  const stages = S.schema.stages;
  const idx = stages.findIndex((s) => s.id === S.stage);
  const st = stages[idx] || stages[0];
  const all = PHASES.flatMap((p) => p[1]);
  const pos = all.indexOf(st.id);
  main.innerHTML = `<div class="stage-head"><div><div class="eyebrow">Step ${pos + 1} of ${all.length}</div><h1>${esc(st.title)}</h1><p>${esc(st.summary)}</p></div></div><div class="cards"></div>`;
  const cards = $('.cards', main);
  if (st.id === 'data') cards.append(profilerCard());
  let hiddenAdv = 0;
  st.sections.forEach((sec, si) => {
    const card = document.createElement('section');
    card.className = 'card'; card.dataset.sec = `${st.id}:${si}`;
    card.innerHTML = `<div class="card-head"><div><h3>${esc(sec.title)}</h3>${sec.desc ? `<p class="card-desc">${esc(sec.desc)}</p>` : ''}</div></div><div class="card-body"><div class="grid"></div></div>`;
    const grid = $('.grid', card);
    sec.fields.forEach((f) => { grid.append(fieldEl(f)); if (f.adv && S.mode !== 'expert' && matches(sec.show, S.cfg) && matches(f.show, S.cfg) && !isModified(f.key)) hiddenAdv++; });
    cards.append(card);
  });
  if (hiddenAdv) {
    main.insertAdjacentHTML('beforeend', `<div class="adv-note">${icon('sliders')}<span>${hiddenAdv} expert setting${hiddenAdv > 1 ? 's' : ''} hidden on this step.</span><button class="btn sm" id="showExpert">Show expert settings</button></div>`);
    $('#showExpert').onclick = () => setMode('expert');
  }
  const prev = all[pos - 1], next = all[pos + 1] || 'generate';
  main.insertAdjacentHTML('beforeend', `<div class="stage-nav">
    ${prev ? `<button class="btn" data-goto="${prev}">${icon('arrowL')}${esc(stages.find((s) => s.id === prev).title)}</button>` : '<span></span>'}
    <button class="btn primary" data-goto="${next}">${next === 'generate' ? 'Generate pipeline' : esc(stages.find((s) => s.id === next).title)}${icon('arrowR')}</button></div>`);
  refreshVisibility(); refreshModified(); paintInlineIssues();
}

function paintInlineIssues() {
  $$('.field', $('#main')).forEach((el) => {
    const list = S.issuesByKey[el.dataset.key] || [];
    el.classList.toggle('has-error', list.some((i) => i.level === 'error'));
    el.classList.toggle('has-warn', !list.some((i) => i.level === 'error') && list.some((i) => i.level === 'warn'));
    const box = $('.f-msgs', el);
    if (box) box.innerHTML = list.map((i) => `<div class="f-msg ${i.level}">${icon(i.level === 'error' ? 'error' : i.level === 'warn' ? 'alert' : 'info')}<span>${esc(i.msg)}</span></div>`).join('');
  });
}

function flashField(key) {
  const st = S.stageOf[key];
  const f = S.fields[key];
  if (f && f.adv && S.mode !== 'expert') setMode('expert', true);
  if (st && st !== S.stage) goto(st);
  requestAnimationFrame(() => {
    const el = $(`.field[data-key="${CSS.escape(key)}"]`, $('#main'));
    if (!el) return toast('That setting is hidden by another choice on this step');
    if (el.hidden) { toast('Hidden: depends on another setting on this step'); }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1400);
    const focusable = $('input, select, textarea, button.choice, .segf button, .chip', el);
    focusable?.focus({ preventScroll: true });
  });
}

// ───────────────────────── data profiler ─────────────────────────
function profilerCard() {
  const card = document.createElement('section');
  card.className = 'card';
  card.innerHTML = `<div class="card-head"><h3>Profile a dataset</h3><span class="muted" style="font-size:12px">JSONL · JSON · CSV · TSV — stays on this machine</span></div>
    <div class="card-body"><div class="drop" tabindex="0" role="button">${icon('upload')}<div><b>Drop a file</b> or click to choose. Detects schema, length distribution, duplicates, PII and label balance.</div></div>
    <input type="file" accept=".jsonl,.json,.csv,.tsv,.txt" hidden><div class="prof-out"></div></div>`;
  const drop = $('.drop', card), inp = $('input', card), out = $('.prof-out', card);
  const run = async (file) => {
    if (!file) return;
    out.innerHTML = '<div class="loading">Profiling…</div>';
    const MAX = 40 * 1024 * 1024;
    let text = await file.slice(0, MAX).text();
    if (file.size > MAX) text = text.slice(0, text.lastIndexOf('\n'));
    try { renderProfile(out, await api('/api/profile', { name: file.name, text }), file.size > MAX); }
    catch (e) { out.innerHTML = `<div class="f-msg error" style="margin-top:12px">${icon('error')}${esc(e.message)}</div>`; }
  };
  drop.onclick = () => inp.click();
  drop.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inp.click(); } };
  inp.onchange = () => run(inp.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); run(e.dataTransfer.files[0]); };
  return card;
}
function renderProfile(out, p, truncated) {
  const maxC = Math.max(1, ...p.histogram.map((h) => h.count));
  const lab = (n) => n >= 1e9 ? '∞' : n >= 1024 ? (n / 1024) + 'k' : n;
  const dist = Object.keys(p.labels).length ? p.labels : p.roles;
  const distTitle = Object.keys(p.labels).length ? 'Label distribution' : 'Role counts';
  out.innerHTML = `
    <div class="profile">
      <div class="stat"><div class="k">Records${truncated ? ' (first 40 MB)' : ''}</div><div class="v">${p.rows.toLocaleString()}</div></div>
      <div class="stat"><div class="k">Detected schema</div><div class="v mono" style="font-size:13px">${esc(p.schema)}</div><div class="s">${esc(p.data_kind)}</div></div>
      <div class="stat"><div class="k">Tokens avg / p95</div><div class="v">${p.tokens.avg} / ${p.tokens.p95}</div><div class="s">max ${p.tokens.max.toLocaleString()} · ≈4 chars/token</div></div>
      <div class="stat"><div class="k">Duplicates</div><div class="v">${p.duplicates}</div><div class="s">${p.avg_turns ? p.avg_turns + ' turns avg' : p.empty_records + ' with empty fields'}</div></div>
    </div>
    <div class="ins-title" style="margin-top:16px">Length distribution (tokens per record)</div>
    <div class="hist" role="img" aria-label="Histogram of record lengths">${p.histogram.map((h) => `<div class="b" style="height:${(h.count / maxC) * 100}%" data-tip="${lab(h.lo)}–${lab(h.hi)} tokens: ${h.count.toLocaleString()} records (${(100 * h.count / p.rows).toFixed(1)}%)"><span>${lab(h.lo)}</span></div>`).join('')}</div>
    ${Object.keys(dist).length ? `<details style="margin-top:12px"><summary class="muted" style="cursor:pointer;font-size:13px">${distTitle} & bins as a table</summary>
      <table class="tbl" style="margin-top:8px"><tr><th>${distTitle.split(' ')[0]}</th><th>Count</th></tr>${Object.entries(dist).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="mono">${v}</td></tr>`).join('')}</table>
      <table class="tbl" style="margin-top:8px"><tr><th>Tokens</th><th>Records</th></tr>${p.histogram.map((h) => `<tr><td class="mono">${lab(h.lo)}–${lab(h.hi)}</td><td class="mono">${h.count}</td></tr>`).join('')}</table></details>` : ''}
    <div class="flags">${p.flags.map((f) => `<div class="f-msg ${f.level}">${icon(f.level === 'error' ? 'error' : f.level === 'warn' ? 'alert' : 'info')}<span>${esc(f.msg)}</span></div>`).join('')}</div>
    <div class="row" style="margin-top:14px;justify-content:space-between"><span class="muted" style="font-size:12.5px">Will set: ${Object.entries(p.patch).map(([k, v]) => `<span class="mono">${esc(k)}=${esc(fmtVal(v))}</span>`).join(', ')}</span>
      <button class="btn primary sm" id="applyProfile">${icon('check')}Apply detected settings</button></div>`;
  $('#applyProfile', out).onclick = () => { applyPatch(p.patch, 'Dataset settings applied'); };
}

// ───────────────────────── analysis + inspector ─────────────────────────
let analyzeSeq = 0;
async function analyze() {
  const seq = ++analyzeSeq;
  try {
    const a = await api('/api/analyze', { config: S.cfg });
    if (seq !== analyzeSeq) return;
    S.analysis = a;
    S.issuesByKey = {};
    a.issues.forEach((i) => (S.issuesByKey[i.key] = S.issuesByKey[i.key] || []).push(i));
    renderInspector(); renderRail(); paintInlineIssues();
    if (S.stage === 'generate') S.files = null;
  } catch (e) { $('#inspector').innerHTML = `<div class="f-msg error">${icon('error')}Cannot reach the server: ${esc(e.message)}</div>`; }
}
const scheduleAnalyze = debounce(analyze, 220);

const MEM_PARTS = [
  ['weights', 'Model weights', 'var(--s1)'], ['grads', 'Gradients', 'var(--s2)'], ['optimizer', 'Optimizer states', 'var(--s3)'],
  ['activations', 'Activations', 'var(--s4)'], ['logits', 'Logits / loss', 'var(--s5)'], ['extra', 'Extra models', 'var(--s7)'], ['overhead', 'CUDA + fragmentation', 'var(--s-neutral)'],
];
function renderInspector() {
  const e = S.analysis.estimate, m = e.memory;
  const scale = Math.max(m.total_gb, m.gpu_mem_gb) * 1.04;
  const ratio = m.total_gb / m.gpu_mem_gb;
  const status = !m.fits ? ['bad', 'Out of memory'] : ratio > 0.85 ? ['tight', 'Tight fit'] : ['ok', 'Fits'];
  const errs = S.analysis.issues.filter((i) => i.level === 'error').length;
  const parts = MEM_PARTS.filter(([k]) => m.parts[k] > 0.005);
  $('#inspector').innerHTML = `
    <div class="ins-section">
      <div class="ins-title"><span>GPU memory / device</span><span class="status ${status[0]}">${status[1]}</span></div>
      <div class="mem-head"><span class="big">${m.total_gb.toFixed(1)} GB</span><span class="of">of ${m.gpu_mem_gb} GB · ${esc(e.gpu)}</span></div>
      <div class="membar" role="img" aria-label="Memory breakdown, ${m.total_gb.toFixed(1)} of ${m.gpu_mem_gb} gigabytes">
        ${parts.map(([k, l, c]) => `<div class="seg-m" data-part="${k}" style="width:${(m.parts[k] / scale) * 100}%;background:${c}" data-tip="${l}: ${m.parts[k].toFixed(2)} GB (${(100 * m.parts[k] / m.total_gb).toFixed(0)}%)"></div>`).join('')}
        <div class="cap" style="left:${(m.gpu_mem_gb / scale) * 100}%" data-tip="GPU capacity ${m.gpu_mem_gb} GB"></div>
      </div>
      <div class="mem-scale"><span>0</span><span>${Math.round(scale)} GB</span></div>
      <ul class="legend">${parts.map(([k, l, c]) => `<li data-part="${k}"><span class="sw" style="background:${c}"></span>${l}${k === 'extra' && m.extra_note ? ` <span class="muted">(${esc(m.extra_note)})</span>` : ''}<span class="v">${m.parts[k].toFixed(1)}</span></li>`).join('')}</ul>
      ${m.cpu_offload_gb ? `<div class="hint-line" style="margin-top:6px">+ ${m.cpu_offload_gb.toFixed(1)} GB optimizer state offloaded to CPU RAM</div>` : ''}
    </div>
    <div class="ins-section">
      <div class="ins-title"><span>Run estimate</span><span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500" data-tip="First-order estimates (±20–30%). Time assumes ${Math.round(e.mfu * 100)}% MFU.">±25%</span></div>
      <div class="stats">
        <div class="stat"><div class="k">Trainable params</div><div class="v">${fmtB(e.trainable_params)}</div><div class="s">${e.trainable_pct < 0.01 ? e.trainable_pct.toExponential(1) : e.trainable_pct.toFixed(e.trainable_pct < 1 ? 2 : 0)}% of ${e.params_b}B</div></div>
        <div class="stat"><div class="k">Effective batch</div><div class="v">${e.eff_batch}</div><div class="s">${fmtTok(e.tokens_per_step)} tokens/step</div></div>
        <div class="stat"><div class="k">Optimizer steps</div><div class="v">${e.steps.toLocaleString()}</div><div class="s">${fmtTok(e.train_tokens)} train tokens</div></div>
        <div class="stat"><div class="k">Strategy</div><div class="v" style="font-size:14px">${esc({ single: 'Single GPU', ddp: 'DDP', fsdp: 'FSDP', zero1: 'ZeRO-1', zero2: 'ZeRO-2', zero3: 'ZeRO-3', zero3_offload: 'ZeRO-3 + offload' }[e.strategy] || e.strategy)}</div><div class="s">${e.world_size} GPU${e.world_size > 1 ? 's' : ''}</div></div>
        <div class="stat"><div class="k">Wall-clock</div><div class="v">${fmtH(e.hours)}</div><div class="s">${e.gpu_hours.toFixed(1)} GPU-hours${e.gen_tokens ? ' · incl. rollouts' : ''}</div></div>
        <div class="stat"><div class="k">Compute cost</div><div class="v">${fmtUSD(e.cost)}</div><div class="s">@ $${e.cost_per_gpu_hour}/GPU-h</div></div>
        ${e.adapter_mb != null ? `<div class="stat" style="grid-column:1/-1"><div class="k">Adapter artifact</div><div class="v">${e.adapter_mb < 1 ? (e.adapter_mb * 1024).toFixed(0) + ' KB' : e.adapter_mb.toFixed(0) + ' MB'}</div><div class="s">vs ${(e.params_b * 2).toFixed(1)} GB for a full bf16 checkpoint</div></div>` : ''}
      </div>
    </div>
    ${testPlanHtml(S.analysis.testing)}
    <div class="ins-section">
      <div class="ins-title"><span>Preflight checks</span><span>${errs ? `<span class="pill err">${errs}</span>` : ''}</span></div>
      <div class="issues">${S.analysis.issues.length ? S.analysis.issues.map((i, n) => `<button class="issue ${i.level}" data-issue="${n}"><span class="ic">${icon(i.level === 'error' ? 'error' : i.level === 'warn' ? 'alert' : 'info')}</span><span>${esc(i.msg)}<small>${esc((S.schema.stages.find((s) => s.id === (S.stageOf[i.key] || i.stage)) || {}).title || '')} › ${esc(S.fields[i.key]?.label || i.key)}</small></span></button>`).join('')
        : `<div class="allclear">${icon('check-circle')}All checks pass — ready to generate.</div>`}</div>
    </div>`;
}

function testPlanHtml(t) {
  if (!t) return '';
  const pts = (x) => (x * 100).toFixed(x < 0.1 ? 1 : 0) + ' pts';
  return `<div class="ins-section">
      <div class="ins-title"><span>Test plan</span><span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">${t.covered}/${t.coverage.length} layers</span></div>
      <div class="stats">
        <div class="stat" data-tip="Held-out items = num_examples × test_ratio"><div class="k">Held-out test items</div><div class="v">${t.n_test.toLocaleString()}</div><div class="s">need ≈${t.required_n.toLocaleString()} for ${pts(t.mde)}</div></div>
        <div class="stat" data-tip="Smallest absolute change in the primary metric detectable at α=${t.alpha}, 80% power, baseline ${t.baseline_p.toFixed(2)}">
          <div class="k">Detectable change</div><div class="v" style="color:${t.adequate ? 'var(--ok)' : 'var(--warn)'}">± ${pts(t.detectable)}</div><div class="s">${t.adequate ? 'adequately powered' : 'under-powered'}</div></div>
      </div>
      ${['Fine-tuning tests', 'Evaluation'].map((g) => { const items = t.coverage.filter((c) => c.group === g);
        return `<div class="cov-group">${g} <span>${items.filter((c) => c.on).length}/${items.length}</span></div><ul class="coverage">${items.map((c) => `<li><button class="${c.on ? 'on' : ''}" data-jump="${esc(c.key)}" title="${c.on ? 'Enabled' : 'Not planned'} — click to configure">${icon(c.on ? 'check' : 'circle')}<span>${esc(c.label)}</span></button></li>`).join('')}</ul>`; }).join('')}
    </div>`;
}

// ───────────────────────── advisor ─────────────────────────
const ADV_KEYS = ['task_type', 'data_kind', 'num_examples', 'avg_tokens', 'p95_tokens', 'domain_shift', 'preserve_general', 'model_variant',
  'base_model', 'gpu_type', 'num_gpus', 'priority', 'deploy_target', 'latency_p95_ms', 'license_constraint', 'data_privacy'];
const A = { cfg: {}, res: null, force: null };
function openAdvisor() {
  A.cfg = structuredClone(S.cfg); A.force = null;
  const box = $('#advInputs'); box.innerHTML = '';
  ADV_KEYS.forEach((k) => {
    const f = S.fields[k];
    box.append(fieldEl(f, { compact: true, get: (key) => A.cfg[key], set: (v) => { A.cfg[k] = v; A.force = null; runAdvisor(); } }));
  });
  $('#advisor').hidden = false;
  runAdvisor.now();
  setTimeout(() => $('#advInputs select, #advInputs input')?.focus(), 50);
}
async function runAdvisorNow() {
  const r = $('#advResults');
  try {
    A.res = await api('/api/recommend', { config: { ...A.cfg, ...(A.force ? { _force_method: A.force } : {}) } });
    renderAdvice();
  } catch (e) { r.innerHTML = `<div class="f-msg error">${icon('error')}${esc(e.message)}</div>`; }
}
const runAdvisor = debounce(runAdvisorNow, 250); runAdvisor.now = runAdvisorNow;

function renderAdvice() {
  const r = A.res, top = r.patch.method;
  const box = $('#advResults');
  const e = r.estimate;
  box.innerHTML = `
    ${r.warnings.map((w) => `<div class="warnbox">${icon('alert')}<span>${esc(w)}</span></div>`).join('')}
    <h4>Recommended objective</h4>
    <div class="obj-card"><div class="t">${esc(r.objective.name)}</div><p>${r.objective.why.map(esc).join(' ')}</p>
      <div class="pipeline">${r.objective.pipeline.map((p, i) => `${i ? icon('chevron') : ''}<span>${esc(p)}</span>`).join('')}</div>
      ${r.objective.alternatives.length ? `<div class="alts">Alternatives: ${r.objective.alternatives.map((a) => esc(a.name)).join(' · ')}</div>` : ''}</div>
    <h4>Fine-tuning techniques, ranked for your inputs</h4>
    <div class="muted" style="font-size:12.5px;margin:-4px 0 10px">Score 0–100 · memory per GPU at the recommended settings · click a row for the reasoning.</div>
    ${r.techniques.map((t, i) => `<div class="tech ${t.id === top ? 'top' : ''} ${t.fits ? '' : 'nofit'}" data-tech="${t.id}">
      <div class="tech-head" role="button" tabindex="0" aria-expanded="${t.id === top}"><span class="rank">${i + 1}</span><span class="nm">${esc(t.name)} ${t.id === top ? '<span class="badge top">Selected</span>' : ''} ${t.fits ? '' : '<span class="badge nofit">OOM</span>'}</span>
        <div class="score" aria-hidden="true"><div style="width:${t.score}%"></div></div><span class="sv">${t.score}</span><span class="mem">${t.mem_gb} GB</span></div>
      <div class="tech-body" ${t.id === top ? '' : 'hidden'}>
        <div class="pc"><div><b style="color:var(--ok)">+</b> ${esc(t.pro)}</div><div><b style="color:var(--err)">−</b> ${esc(t.con)}</div></div>
        ${t.reasons.map((x) => `<div class="reason"><span class="d ${x.delta > 0 ? 'pos' : 'neg'}">${x.delta > 0 ? '+' : ''}${x.delta}</span><span>${esc(x.text)}</span></div>`).join('') || '<div class="muted">Baseline score; no adjustments apply.</div>'}
        ${t.id !== top && t.fits ? `<button class="btn sm" style="margin-top:8px" data-force="${t.id}">Use ${esc(t.name)} instead</button>` : ''}
      </div></div>`).join('')}
    <h4>Settings to apply</h4>
    ${adviceTable(r.rationale)}
    <h4>Base models that fit (${r.models.size_band[0]}–${r.models.size_band[1]}B suggested for your constraints)</h4>
    <table class="tbl"><thead><tr><th>Model</th><th>Params</th><th>Licence</th><th>Memory/GPU</th><th></th></tr></thead><tbody>
    ${r.models.models.map((mm) => `<tr><td class="mono">${esc(mm.id)}${mm.id === A.cfg.base_model ? ' <span class="badge top">current</span>' : ''}</td><td class="mono">${mm.params_b}B</td><td>${esc(mm.license)}</td>
      <td class="mono">${mm.mem_gb} GB ${mm.fits ? '' : '<span class="badge nofit">OOM</span>'}</td><td>${mm.id !== A.cfg.base_model && mm.fits ? `<button class="btn sm" data-model="${esc(mm.id)}">Use</button>` : ''}</td></tr>`).join('')}</tbody></table>
    <h4>Projected run</h4>
    <div class="stats" style="grid-template-columns:repeat(4,1fr)">
      <div class="stat"><div class="k">Memory / GPU</div><div class="v">${e.memory.total_gb.toFixed(1)} GB</div><div class="s">of ${e.memory.gpu_mem_gb} GB</div></div>
      <div class="stat"><div class="k">Wall-clock</div><div class="v">${fmtH(e.hours)}</div><div class="s">${e.steps.toLocaleString()} steps</div></div>
      <div class="stat"><div class="k">Cost</div><div class="v">${fmtUSD(e.cost)}</div><div class="s">${e.gpu_hours.toFixed(1)} GPU-h</div></div>
      <div class="stat"><div class="k">Trainable</div><div class="v">${fmtB(e.trainable_params)}</div><div class="s">${e.trainable_pct.toFixed(2)}%</div></div>
    </div>`;
  updateAdvCount();
}
function adviceTable(rows) {
  const order = S.schema.stages.map((st) => st.id);
  const titles = Object.fromEntries(S.schema.stages.map((st) => [st.id, st.title]));
  const items = rows.map((x, i) => ({ ...x, i, stage: S.stageOf[x.key] || 'objective', changed: !same(S.cfg[x.key], x.value) }));
  const row = (x) => `<tr style="${x.changed ? '' : 'opacity:.55'}"><td><input type="checkbox" data-row="${x.i}" ${x.changed ? 'checked' : ''} aria-label="Apply ${esc(x.key)}"></td>
    <td>${esc(S.fields[x.key]?.label || x.key)}<div class="muted mono" style="font-size:11px">${esc(x.key)}</div></td>
    <td>${x.changed ? `<span class="from">${esc(fmtVal(S.cfg[x.key]))}</span> → ` : ''}<span class="to">${esc(fmtVal(x.value))}</span></td>
    <td class="why">${esc(x.why)}</td></tr>`;
  const changed = items.filter((x) => x.changed), same_ = items.filter((x) => !x.changed);
  let html = `<table class="tbl"><thead><tr><th style="width:28px"><input type="checkbox" id="advAll" checked aria-label="Select all"></th><th>Setting</th><th>Change</th><th>Why</th></tr></thead>`;
  for (const st of order) {
    const g = changed.filter((x) => x.stage === st);
    if (g.length) html += `<tbody><tr class="grp"><td colspan="4">${esc(titles[st])} <span class="muted">· ${g.length} change${g.length > 1 ? 's' : ''}</span></td></tr>${g.map(row).join('')}</tbody>`;
  }
  if (!changed.length) html += '<tbody><tr><td colspan="4" class="muted">Your configuration already matches every recommendation.</td></tr></tbody>';
  if (same_.length) html += `<tbody><tr class="grp"><td colspan="4"><button class="btn sm ghost" id="advSame">${icon('chevron')}${same_.length} already match your config</button></td></tr></tbody><tbody id="advSameRows" hidden>${same_.map(row).join('')}</tbody>`;
  return html + '</table>';
}
function updateAdvCount() {
  const n = $$('#advResults input[data-row]:checked').length;
  const inputs = ADV_KEYS.filter((k) => !same(A.cfg[k], S.cfg[k])).length;
  $('#advCount').textContent = `${n} recommendation${n === 1 ? '' : 's'}${inputs ? ` + ${inputs} answer${inputs === 1 ? '' : 's'}` : ''} will be applied`;
}
function applyAdvice() {
  const patch = {};
  ADV_KEYS.forEach((k) => { if (!same(A.cfg[k], S.cfg[k])) patch[k] = A.cfg[k]; });
  $$('#advResults input[data-row]:checked').forEach((cb) => { const x = A.res.rationale[+cb.dataset.row]; patch[x.key] = x.value; });
  closeOverlays();
  applyPatch(patch, `Applied ${Object.keys(patch).length} settings from the advisor`);
}

// ───────────────────────── generate view ─────────────────────────
function highlight(code, file) {
  const yaml = /\.ya?ml$/.test(file), json = /\.jsonl?$/.test(file), txt = /\.(txt|md)$/.test(file);
  const KW = 'def|return|if|else|elif|for|in|import|from|as|try|except|with|class|None|True|False|and|or|not|lambda|raise|while|is|pass|export|then|fi|true|false|null|set';
  const re = new RegExp(`(${json ? '(?!)' : '#.*$'})|("""[\\s\\S]*?"""|"(?:[^"\\\\\\n]|\\\\.)*"|'(?:[^'\\\\\\n]|\\\\.)*')|(\\b\\d+(?:\\.\\d+)?(?:e-?\\d+)?\\b)|(\\b(?:${KW})\\b)|(${yaml ? '^\\s*[\\w.-]+(?=:)' : '(?!)'})`, 'gm');
  return code.split('\n').map((line) => {
    if (txt) return `<span class="ln">${esc(line)}</span>`;
    let out = '', last = 0, m;
    re.lastIndex = 0;
    while ((m = re.exec(line))) {
      if (m[0] === '') { re.lastIndex++; continue; }
      out += esc(line.slice(last, m.index));
      const cls = m[1] ? 't-com' : m[2] ? (json && line.slice(m.index + m[0].length).trimStart().startsWith(':') ? 't-key' : 't-str') : m[3] ? 't-num' : m[4] ? 't-kw' : 't-key';
      out += `<span class="${cls}">${esc(m[0])}</span>`;
      last = m.index + m[0].length;
    }
    return `<span class="ln">${out + esc(line.slice(last))}</span>`;
  }).join('');
}
async function renderGenerate() {
  const main = $('#main');
  const errs = (S.analysis?.issues || []).filter((i) => i.level === 'error');
  main.innerHTML = `<div class="stage-head"><div><div class="eyebrow">Output</div><h1>Generate pipeline</h1>
    <p>A runnable project: training script (Transformers + PEFT + TRL), distributed config, launch, evaluation, export and serving.</p></div>
    <div class="row"><button class="btn" id="dlJson">${icon('file')}config.json</button><button class="btn primary" id="dlZip">${icon('download')}Download .zip</button></div></div>
    ${errs.length ? `<div class="warnbox" style="max-width:1040px;margin-bottom:14px;background:var(--err-soft);color:var(--err)">${icon('error')}<span>${errs.length} preflight error${errs.length > 1 ? 's' : ''} — the code is generated but will likely fail. Fix them in the inspector first.</span></div>` : ''}
    <div class="code-wrap"><div class="tabs" role="tablist"></div><div class="code-tools"><span class="file-desc"></span><div class="row"><button class="btn sm" id="copyFile">${icon('copy')}Copy</button><button class="btn sm" id="dlFile">${icon('download')}File</button></div></div><pre class="code"><div class="loading">Generating…</div></pre></div>`;
  $('#dlZip').onclick = downloadZip; $('#dlJson').onclick = downloadJson;
  try { S.files = await api('/api/generate', { config: S.cfg }); }
  catch (e) { $('pre.code', main).innerHTML = `<span class="t-com">${esc(e.message)}</span>`; return; }
  if (!S.files[S.fileTab]) S.fileTab = 'train.py';
  const DESC = { 'train.py': 'Training entry point', 'config.yaml': 'Full configuration (source of truth)', 'accelerate_config.yaml': 'Accelerate launcher config',
    'ds_config.json': 'DeepSpeed ZeRO config', 'launch.sh': 'Launch command', 'eval.sh': 'Benchmarks + regression vs base', 'eval_task.py': 'Task metrics on your test split',
    'export.sh': 'Merge, quantize, convert', 'serve.sh': 'Serving + rollout', 'requirements.txt': 'Dependencies',
    'eval_suite.py': 'All test layers, paired significance tests, release gates (exit 1 on failure)', 'TEST_PLAN.md': 'Testing methodology & acceptance criteria',
    'gates.json': 'Release-gate thresholds', 'loadtest.sh': 'Latency / throughput load test', 'redteam.sh': 'Safety suites & automated red teaming',
    'tests/golden.example.jsonl': 'Example behavioural tests (MFT / INV / DIR)',
    'ft_checks.py': 'Pre-training sanity checks on the real pipeline (exit 1 on failure)', 'ft_monitor.py': 'In-training failure-mode monitors (callback)',
    'ft_diagnostics.py': 'Checkpoint selection + post-training, objective- and technique-specific tests', 'sweep.py': 'HPO, learning curve, ablations, seeds, noisy-label audit',
    'tests/knowledge_probes.example.jsonl': 'Example injected-knowledge probes', 'soup.mergekit.yaml': 'Checkpoint weight-soup recipe', 'tests/safety.example.jsonl': 'Example safety & prompt-injection cases' };
  const draw = () => {
    $('.tabs', main).innerHTML = Object.keys(S.files).map((f) => `<button class="tab ${f === S.fileTab ? 'on' : ''}" role="tab" aria-selected="${f === S.fileTab}" data-file="${esc(f)}">${esc(f)}</button>`).join('');
    const content = S.files[S.fileTab];
    $('.file-desc', main).textContent = `${DESC[S.fileTab] || ''} · ${content.split('\n').length - 1} lines`;
    $('pre.code', main).innerHTML = highlight(content.replace(/\n$/, ''), S.fileTab);
  };
  draw();
  $('.tabs', main).onclick = (e) => { const b = e.target.closest('.tab'); if (b) { S.fileTab = b.dataset.file; draw(); } };
  $('#copyFile').onclick = async () => { try { await navigator.clipboard.writeText(S.files[S.fileTab]); toast('Copied ' + S.fileTab); } catch { toast('Clipboard unavailable'); } };
  $('#dlFile').onclick = () => saveBlob(new Blob([S.files[S.fileTab]], { type: 'text/plain' }), S.fileTab);
}
function saveBlob(blob, name) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
async function downloadZip() {
  try {
    const r = await fetch('/api/export.zip', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ config: S.cfg }) });
    if (!r.ok) throw new Error((await r.json()).error);
    saveBlob(await r.blob(), (S.cfg.project_name || 'finetune') + '.zip');
    toast('Pipeline downloaded');
  } catch (e) { toast('Export failed: ' + e.message); }
}
function downloadJson() { saveBlob(new Blob([JSON.stringify(S.cfg, null, 2)], { type: 'application/json' }), (S.cfg.project_name || 'finetune') + '.config.json'); }

// ───────────────────────── command palette ─────────────────────────
const P = { items: [], sel: 0 };
function openPalette() {
  $('#palette').hidden = false; const inp = $('#paletteInput'); inp.value = ''; renderPalette(''); inp.focus();
}
function renderPalette(q) {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const stages = Object.fromEntries(S.schema.stages.map((s) => [s.id, s.title]));
  const all = Object.values(S.fields).map((f) => {
    const hay = `${f.label} ${f.key} ${f.help} ${stages[S.stageOf[f.key]]} ${(f.options || []).map((o) => o.label).join(' ')}`.toLowerCase();
    let score = 0;
    for (const t of terms) { if (!hay.includes(t)) return null; score += f.label.toLowerCase().includes(t) ? 3 : f.key.includes(t) ? 2 : 1; }
    return { f, score };
  }).filter(Boolean);
  all.sort((a, b) => b.score - a.score);
  const quick = [{ act: 'advisor', label: 'Open advisor', sub: 'Recommend technique & settings' }, { act: 'generate', label: 'Generate pipeline', sub: 'View & download code' }]
    .filter((x) => !terms.length || terms.every((t) => (x.label + x.sub).toLowerCase().includes(t)));
  P.items = [...quick, ...all.slice(0, 40)]; P.sel = 0;
  $('#paletteList').innerHTML = P.items.map((it, i) => it.act
    ? `<li data-i="${i}" class="${i === 0 ? 'sel' : ''}" role="option">${icon(it.act === 'advisor' ? 'sparkles' : 'code')}<div><div class="pl">${esc(it.label)}</div><div class="ps">${esc(it.sub)}</div></div></li>`
    : `<li data-i="${i}" class="${i === 0 ? 'sel' : ''}" role="option"><div><div class="pl">${esc(it.f.label)}${it.f.adv ? ' <span class="adv-tag" style="font-size:10px;color:var(--text-3)">EXPERT</span>' : ''}</div><div class="ps">${esc(stages[S.stageOf[it.f.key]])} · <span class="mono">${esc(it.f.key)}</span></div></div><span class="pv">${esc(fmtVal(S.cfg[it.f.key]))}</span></li>`).join('')
    || '<li class="ps" style="cursor:default">No matching settings</li>';
}
function pickPalette(i) {
  const it = P.items[i]; if (!it) return;
  closeOverlays();
  if (it.act === 'advisor') return openAdvisor();
  if (it.act === 'generate') return goto('generate');
  flashField(it.f.key);
}

// ───────────────────────── chrome: menus, modes, theme ─────────────────────────
function setMode(mode, quiet) {
  S.mode = mode; store.set('fts-mode', mode);
  $$('#modeSeg button').forEach((b) => b.setAttribute('aria-checked', b.dataset.mode === mode));
  if (S.stage !== 'generate') renderStage();
  if (!quiet) toast(mode === 'expert' ? 'Expert mode: every setting visible' : 'Essential mode: expert settings hidden unless changed');
}
function toggleTheme() {
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('fts-theme', next); } catch { /* */ }
}
function closeOverlays() { $$('.overlay').forEach((o) => (o.hidden = true)); $$('.menu').forEach((m) => (m.hidden = true)); }

function wireChrome() {
  $('#projectName').addEventListener('input', (e) => setValue('project_name', e.target.value));
  $$('#modeSeg button').forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
  $('#searchBtn').onclick = openPalette;
  $('#advisorBtn').onclick = openAdvisor;
  $('#exportBtn').onclick = () => goto('generate');
  $('#advApply').onclick = applyAdvice;
  $$('[data-close]').forEach((b) => (b.onclick = closeOverlays));
  $$('.overlay').forEach((o) => o.addEventListener('mousedown', (e) => { if (e.target === o) closeOverlays(); }));

  const presetMenu = $('#presetMenu');
  presetMenu.innerHTML = S.schema.presets.map((p, i) => `<button data-p="${i}"><span><span class="m-title">${esc(p.name)}</span><span class="m-desc">${esc(p.desc)}</span></span></button>`).join('');
  $('#presetBtn').onclick = (e) => { e.stopPropagation(); $('#moreMenu').hidden = true; presetMenu.hidden = !presetMenu.hidden; };
  presetMenu.onclick = (e) => { const b = e.target.closest('[data-p]'); if (!b) return; const p = S.schema.presets[+b.dataset.p]; presetMenu.hidden = true; applyPatch(p.patch, `Preset applied: ${p.name}`); };
  $('#moreBtn').onclick = (e) => { e.stopPropagation(); presetMenu.hidden = true; $('#moreMenu').hidden = !$('#moreMenu').hidden; };
  $('#moreMenu').onclick = (e) => {
    const b = e.target.closest('[data-act]'); if (!b) return; $('#moreMenu').hidden = true;
    const act = b.dataset.act;
    if (act === 'import') $('#importFile').click();
    if (act === 'exportJson') downloadJson();
    if (act === 'theme') toggleTheme();
    if (act === 'reset' && confirm('Reset every setting to its default?')) { S.cfg = structuredClone(S.defaults); applyPatch({}, 'Reset to defaults'); }
  };
  $('#importFile').onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try { const obj = JSON.parse(await f.text()); S.cfg = { ...structuredClone(S.defaults), ...obj }; applyPatch({}, `Imported ${f.name}`); }
    catch { toast('Not a valid JSON config'); }
    e.target.value = '';
  };
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.menu-wrap')) $$('.menu').forEach((m) => (m.hidden = true));
    const g = e.target.closest('[data-goto], .rail [data-stage]');
    if (g) goto(g.dataset.goto || g.dataset.stage);
    const jb = e.target.closest('[data-jump]');
    if (jb) flashField(jb.dataset.jump);
    const iss = e.target.closest('[data-issue]');
    if (iss) flashField(S.analysis.issues[+iss.dataset.issue].key);
    const th = e.target.closest('.tech-head');
    if (th) { const body = th.nextElementSibling; body.hidden = !body.hidden; th.setAttribute('aria-expanded', !body.hidden); }
    if (e.target.closest('#advSame')) { const t = $('#advSameRows'); t.hidden = !t.hidden; }
    const fb = e.target.closest('[data-force]');
    if (fb) { A.force = fb.dataset.force; runAdvisor.now(); }
    const mb = e.target.closest('[data-model]');
    if (mb) { A.cfg.base_model = mb.dataset.model; const sel = $('#advInputs .field[data-key="base_model"]'); if (sel) sel.replaceWith(fieldEl(S.fields.base_model, { compact: true, get: (k) => A.cfg[k], set: (v) => { A.cfg.base_model = v; runAdvisor(); } })); runAdvisor.now(); }
  });
  $('#advResults').addEventListener('change', (e) => {
    if (e.target.id === 'advAll') $$('#advResults input[data-row]').forEach((cb) => (cb.checked = e.target.checked));
    updateAdvCount();
  });
  $('#advResults').addEventListener('keydown', (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('tech-head')) { e.preventDefault(); e.target.click(); } });

  const pin = $('#paletteInput');
  pin.addEventListener('input', () => renderPalette(pin.value));
  pin.addEventListener('keydown', (e) => {
    const lis = $$('#paletteList li[data-i]');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); P.sel = (P.sel + (e.key === 'ArrowDown' ? 1 : -1) + lis.length) % Math.max(lis.length, 1);
      lis.forEach((l, i) => l.classList.toggle('sel', i === P.sel)); lis[P.sel]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') { e.preventDefault(); pickPalette(P.sel); }
  });
  $('#paletteList').onclick = (e) => { const li = e.target.closest('li[data-i]'); if (li) pickPalette(+li.dataset.i); };

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
    else if (e.key === 'Escape') closeOverlays();
    else if (e.altKey && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      const all = [...PHASES.flatMap((p) => p[1]), 'generate'];
      const i = all.indexOf(S.stage) + (e.key === 'ArrowDown' ? 1 : -1);
      if (all[i]) { e.preventDefault(); goto(all[i]); }
    }
  });

  // tooltips + legend/bar linked hover
  const tip = $('#tooltip');
  document.addEventListener('mouseover', (e) => {
    const t = e.target.closest('[data-tip]');
    $$('[data-part].hl').forEach((x) => x.classList.remove('hl'));
    const part = e.target.closest('[data-part]');
    if (part) $$(`[data-part="${part.dataset.part}"]`).forEach((x) => x.classList.add('hl'));
    if (!t) { tip.hidden = true; return; }
    tip.textContent = t.dataset.tip; tip.hidden = false;
    const r = t.getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
    tip.style.top = (r.top - h - 8 < 8 ? r.bottom + 8 : r.top - h - 8) + 'px';
  });
  document.addEventListener('focusin', (e) => { if (!e.target.closest('[data-tip]')) tip.hidden = true; });
  document.addEventListener('scroll', () => (tip.hidden = true), true);
}

// ───────────────────────── boot ─────────────────────────
async function boot() {
  hydrateIcons();
  try { S.schema = await api('/api/schema'); }
  catch (e) { $('#main').innerHTML = `<div class="f-msg error">${icon('error')}Could not load schema. Is server.py running? (${esc(e.message)})</div>`; return; }
  S.defaults = S.schema.defaults;
  S.secIndex = {};
  S.schema.stages.forEach((st) => st.sections.forEach((sec, si) => {
    S.secIndex[`${st.id}:${si}`] = sec;
    sec.fields.forEach((f) => { S.fields[f.key] = f; S.stageOf[f.key] = st.id; });
  }));
  S.cfg = { ...structuredClone(S.defaults), ...store.get('fts-config', {}) };
  if (S.stage !== 'generate' && !S.schema.stages.some((s) => s.id === S.stage)) S.stage = 'objective';
  $('#projectName').value = S.cfg.project_name || '';
  $$('#modeSeg button').forEach((b) => b.setAttribute('aria-checked', b.dataset.mode === S.mode));
  wireChrome();
  renderRail(); renderStage();
  await analyze();
}
boot();

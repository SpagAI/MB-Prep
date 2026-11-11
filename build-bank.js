#!/usr/bin/env node
/*
 * build-bank.js — scans the /bank folder and writes bank.js
 *
 *   node build-bank.js
 *
 * Folder layout:  bank/<Course>/<Category>/[<Sub-category>/...]<image>.jpg
 * Optional sidecar JSON with the same base name adds a label, type and questions.
 * The generated bank.js sets window.BANK so index.html works from file:// (no fetch).
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const BANK_DIR = path.join(ROOT, 'bank');
const OUT_FILE = path.join(ROOT, 'bank.js');
const IMAGE_EXT = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif']);
const COURSE_ORDER = ['Histopathology', 'Chemical Pathology', 'MMP', 'Haematology'];
const VALID_TYPES = new Set(['slide', 'pot', 'photomicrograph', 'specimen', 'case', 'apparatus', 'diagram', 'viva', 'drill', 'cue card']);

/**
 * "hepatocellular-carcinoma" -> "Hepatocellular carcinoma"
 * Sentence case, so species names read correctly ("Staphylococcus aureus") and every option
 * in Easy Money looks the same (no option stands out because of its capitals).
 * Words typed with capitals inside them (HbSS, CD4, H&E) and common acronyms stay in capitals.
 */
const ACRONYMS = new Set(['hiv', 'aids', 'tb', 'afb', 'edta', 'esr', 'pcv', 'cml', 'cll', 'aml', 'dna', 'rna', 'hbv',
  'hcv', 'hpv', 'ebv', 'cmv', 'rbc', 'wbc', 'g6pd', 'hbs', 'hbss', 'hbsc', 'pas', 'gtt', 'ogtt', 'csf', 'dic', 'itp',
  'ttp', 'hus', 'sle', 'zn', 'hpf', 'lpf', 'ecg', 'abo', 'rh', 'mcv', 'mch', 'mchc', 'cpda', 'acd', 'ldh', 'alp', 'ast',
  'alt', 'ggt', 'ck', 'tsh', 'crp', 'hcg', 'psa', 'afp', 'cea', 'gp', 'hb', 'ptt', 'pt', 'inr', 'h&e', 'cin', 'dcis']);
function cleanLabel(base) {
  const s = base
    .replace(/__\d+$/, '')            // cirrhosis__2  (extract.py duplicate-name suffix)
    .replace(/\s*\(\d+\)$/, '')       // cirrhosis (2) (OS copy suffix)
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const words = s.split(' ').map((w) => {
    if (/[A-Z]/.test(w.slice(1)) || /\d/.test(w)) return w; // keep HbS, CD4, x40
    const lw = w.toLowerCase();
    if (ACRONYMS.has(lw)) return lw.toUpperCase();
    return lw;
  });
  if (words.length && words[0]) words[0] = words[0].charAt(0).toUpperCase() + words[0].slice(1);
  return words.join(' ');
}

function encodePath(rel) {
  return rel.split(path.sep).join('/').split('/').map(encodeURIComponent).join('/');
}

function readSidecar(file, warnings) {
  if (!fs.existsSync(file)) return null;
  try {
    const raw = fs.readFileSync(file, 'utf8').replace(/^﻿/, '');
    if (!raw.trim()) return null;
    return JSON.parse(raw);
  } catch (e) {
    warnings.push(`Could not read ${path.relative(ROOT, file)}: ${e.message}`);
    return null;
  }
}

function cleanQuestions(list, rel, warnings) {
  if (!Array.isArray(list)) return [];
  const out = [];
  for (const q of list) {
    if (!q || typeof q !== 'object') continue;
    const text = String(q.q || '').trim();
    const ans = String(q.a || '').trim();
    if (!text) continue; // blank template rows are ignored
    if (!ans) warnings.push(`${rel}: question "${text}" has no answer`);
    const item = { q: text, a: ans };
    if (q.added) item.added = true; // answer written by Lengible (no source file answered it)
    if (q.badge && String(q.badge).trim()) item.badge = String(q.badge).trim().slice(0, 30); // e.g. 'Marking scheme'
    if (q.hint && String(q.hint).trim()) item.hint = String(q.hint).trim();
    if (Array.isArray(q.options)) {
      const opts = q.options.map((o) => String(o).trim()).filter(Boolean);
      if (opts.length >= 2) item.options = opts;
    }
    out.push(item);
  }
  return out;
}

/** "cirrhosis__2" and "cirrhosis (2)" are extra photos (variants) of "cirrhosis". */
function variantBase(base) {
  return base.replace(/__\d+$/, '').replace(/\s*\(\d+\)$/, '');
}

function walk(dir, parts, items, warnings) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    return;
  }
  entries.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  const groups = new Map(); // variant base -> image file names
  const jsons = [];
  for (const ent of entries) {
    if (ent.name.startsWith('.')) continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      walk(full, parts.concat(ent.name), items, warnings);
      continue;
    }
    const ext = path.extname(ent.name).toLowerCase();
    if (ext === '.json') { jsons.push(ent.name); continue; }
    if (!IMAGE_EXT.has(ext)) continue;
    if (/\.fig\d+$/i.test(path.basename(ent.name, ext))) continue; // figure inside a case sheet, not a slide of its own
    if (parts.length < 1) {
      warnings.push(`Skipped ${path.relative(ROOT, full)}: images must be inside bank/<Course>/<Category>/`);
      continue;
    }
    const key = variantBase(path.basename(ent.name, ext));
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(ent.name);
  }

  for (const [key, files] of groups) {
    const course = parts[0];
    const category = parts.length >= 2 ? parts[1] : 'General';
    const sub = parts.slice(2).join(' / ');
    // primary = the file without a __N suffix (else the first one)
    files.sort((a, b) => (variantBase(path.basename(a, path.extname(a))) === path.basename(a, path.extname(a)) ? -1 : 0) -
      (variantBase(path.basename(b, path.extname(b))) === path.basename(b, path.extname(b)) ? -1 : 0) || a.localeCompare(b, undefined, { numeric: true }));
    const primary = files[0];
    const base = path.basename(primary, path.extname(primary));
    let side = readSidecar(path.join(dir, key + '.json'), warnings) || readSidecar(path.join(dir, base + '.json'), warnings) || {};
    const rel = path.relative(ROOT, path.join(dir, primary));

    // photo order: an explicit "images" list in the JSON wins, then any other variants in the folder
    let images = [];
    if (Array.isArray(side.images)) {
      for (const im of side.images) {
        const f = typeof im === 'string' ? im : im && im.file;
        if (f && files.includes(f)) images.push({ file: f, studyOnly: !!(im && im.studyOnly) });
      }
    }
    for (const f of files) if (!images.some((x) => x.file === f)) images.push({ file: f, studyOnly: false });

    // extract.py records which file a label was written for; if you renamed the picture, the new name wins.
    const renamed = side.image && !files.includes(side.image);
    const sideLabel = !renamed && side.label && String(side.label).trim() ? String(side.label).trim() : '';
    const label = sideLabel || cleanLabel(key);
    let type = side.type ? String(side.type).trim().toLowerCase() : '';
    if (type && !VALID_TYPES.has(type)) {
      if (type.includes('|')) type = ''; // untouched template value "slide | pot | photomicrograph"
      else if (/micro/.test(type)) type = 'photomicrograph';
      else if (/pot|gross|jar/.test(type)) type = 'pot';
    }
    const unlabelled = /^unlabel+ed\b/i.test(key) && !sideLabel;
    const imgs = images.map((x) => (x.studyOnly ? { src: encodePath(path.relative(ROOT, path.join(dir, x.file))), studyOnly: true }
      : { src: encodePath(path.relative(ROOT, path.join(dir, x.file))) }));
    const examImg = imgs.find((x) => !x.studyOnly);

    const item = {
      id: items.length,
      course,
      category,
      src: (examImg || imgs[0]).src,
      label,
      questions: cleanQuestions(side.questions, rel, warnings),
    };
    if (imgs.length > 1) item.images = imgs;
    if (sub) item.sub = sub;
    if (type) item.type = type;
    if (unlabelled) item.unlabelled = true;
    if (side.studyOnly === true || !examImg) item.studyOnly = true; // e.g. the answer is written on every photo
    addExtras(item, side, dir);
    items.push(item);
  }

  // Case slides: a JSON file with a "case" (scenario + result tables) and no picture of its own.
  for (const name of jsons) {
    const key = path.basename(name, '.json');
    if (groups.has(key) || groups.has(variantBase(key)) || parts.length < 1) continue;
    const side = readSidecar(path.join(dir, name), warnings);
    if (!side || !(side.case || side.stem)) continue;
    const rel = path.relative(ROOT, path.join(dir, name));
    const item = {
      id: items.length,
      course: parts[0],
      category: parts.length >= 2 ? parts[1] : 'General',
      label: side.label && String(side.label).trim() ? String(side.label).trim() : cleanLabel(key),
      questions: cleanQuestions(side.questions, rel, warnings),
    };
    if (parts.length > 2) item.sub = parts.slice(2).join(' / ');
    const type = side.type ? String(side.type).trim().toLowerCase() : '';
    if (VALID_TYPES.has(type)) item.type = type;
    if (side.studyOnly === true) item.studyOnly = true;
    addExtras(item, side.case ? side : Object.assign({}, side, { case: { stem: side.stem } , stem: undefined }), dir);
    items.push(item);
  }
}

/** Notes, case sheet, scenario line and option settings shared by picture slides and case slides. */
function addExtras(item, side, dir) {
  if (Array.isArray(side.notes) && side.notes.length) item.notes = side.notes.map(String).filter(Boolean).slice(0, 40);
  else if (typeof side.notes === 'string' && side.notes.trim()) item.notes = [side.notes.trim()];
  if (side.stem && String(side.stem).trim()) item.stem = String(side.stem).trim();
  if (side.test && String(side.test).trim() && !side.case) item.test = String(side.test).trim();
  if (side.noOptions) item.noOptions = true;
  if (side.case && typeof side.case === 'object') {
    const c = {};
    for (const k of ['test', 'stem', 'after']) if (side.case[k]) c[k] = String(side.case[k]);
    if (Array.isArray(side.case.tables)) c.tables = side.case.tables;
    if (Array.isArray(side.case.figs)) {
      c.figs = side.case.figs.filter((f) => f && f.file && fs.existsSync(path.join(dir, f.file)))
        .map((f) => Object.assign({ src: encodePath(path.relative(ROOT, path.join(dir, f.file))) }, f.caption ? { caption: String(f.caption) } : {}));
      if (!c.figs.length) delete c.figs;
    }
    if (Object.keys(c).length) item.case = c;
  }
}

function main() {
  if (!fs.existsSync(BANK_DIR)) {
    console.error('No /bank folder found next to build-bank.js. Create bank/<Course>/<Category>/ and add images.');
    process.exit(1);
  }
  const items = [];
  const warnings = [];
  walk(BANK_DIR, [], items, warnings);

  // Course + category summary (courses in the usual order, then anything else alphabetically)
  const courseMap = new Map();
  for (const it of items) {
    if (!courseMap.has(it.course)) courseMap.set(it.course, new Map());
    const cats = courseMap.get(it.course);
    cats.set(it.category, (cats.get(it.category) || 0) + 1);
  }
  const rank = (n) => {
    const i = COURSE_ORDER.indexOf(n);
    return i === -1 ? 100 : i;
  };
  const courses = [...courseMap.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((name) => ({
      name,
      categories: [...courseMap.get(name).entries()]
        .sort((a, b) => (a[0].startsWith('_') - b[0].startsWith('_')) || a[0].localeCompare(b[0]))
        .map(([cat, count]) => ({ name: cat, count })),
    }));

  const bank = {
    generated: new Date().toISOString(),
    count: items.length,
    courses,
    items,
  };
  const js =
    '/* Generated by build-bank.js — do not edit by hand. Re-run: node build-bank.js */\n' +
    'window.BANK = ' + JSON.stringify(bank) + ';\n';
  fs.writeFileSync(OUT_FILE, js);

  const photos = items.reduce((n, i) => n + (i.images ? i.images.length : i.src ? 1 : 0), 0);
  const cases = items.filter((i) => !i.src).length;
  console.log(`bank.js written: ${items.length} slides, ${photos} photos${cases ? `, ${cases} case sheets` : ''}`);
  for (const c of courses) {
    const n = c.categories.reduce((s, x) => s + x.count, 0);
    console.log(`  ${c.name}: ${n} slides in ${c.categories.length} categories (${c.categories.map((x) => `${x.name} ${x.count}`).join(', ')})`);
  }
  const unl = items.filter((i) => i.unlabelled).length;
  if (unl) console.log(`  ${unl} unlabelled image(s): shown in Study mode only. Rename them to use them in exams.`);
  const so = items.filter((i) => i.studyOnly).length;
  if (so) console.log(`  ${so} slide(s) marked "studyOnly" (answer visible, or a study card): Study mode only.`);
  if (warnings.length) {
    console.log(`\n${warnings.length} warning(s):`);
    warnings.slice(0, 50).forEach((w) => console.log('  - ' + w));
  }
}

if (require.main === module) main();
module.exports = { cleanLabel };

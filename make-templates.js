#!/usr/bin/env node
/*
 * make-templates.js — creates a blank sidecar JSON next to every image in /bank that has none.
 *
 *   node make-templates.js
 *
 * Fill in the questions, then run `node build-bank.js` again.
 * Questions left blank are ignored, so it is safe to fill in only some of them.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { cleanLabel } = require('./build-bank.js');

const BANK_DIR = path.join(__dirname, 'bank');
const IMAGE_EXT = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif']);

let created = 0;
let updated = 0;
let skipped = 0;

function blankQuestions(label) {
  return [
    { q: 'Identify the specimen', a: label, hint: '' },
    { q: '', a: '', hint: '' },
    { q: '', a: '', hint: '' },
  ];
}

function walk(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (e) {
    return;
  }
  for (const ent of entries) {
    if (ent.name.startsWith('.')) continue;
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      walk(full);
      continue;
    }
    const ext = path.extname(ent.name).toLowerCase();
    if (!IMAGE_EXT.has(ext)) continue;
    const base = path.basename(ent.name, ext);
    // "name__2.jpg" is an extra photo of "name.jpg": its questions live in name.json
    const vbase = base.replace(/__\d+$/, '').replace(/\s*\(\d+\)$/, '');
    if (vbase !== base) continue;
    const jsonPath = path.join(dir, base + '.json');
    if (fs.existsSync(jsonPath)) {
      // A JSON made by extract.py (label/type only): add blank question slots, keep everything else.
      let side = null;
      try {
        side = JSON.parse(fs.readFileSync(jsonPath, 'utf8').replace(/^\uFEFF/, ''));
      } catch (e) {
        side = null;
      }
      if (side && typeof side === 'object' && !(Array.isArray(side.questions) && side.questions.length)) {
        const renamed = side.image && side.image !== ent.name;
        const lab = (!renamed && side.label) || (/^unlabel+ed/i.test(base) ? '' : cleanLabel(base));
        side.questions = blankQuestions(lab);
        fs.writeFileSync(jsonPath, JSON.stringify(side, null, 2) + '\n');
        updated++;
      } else {
        skipped++;
      }
      continue;
    }
    const label = /^unlabel+ed/i.test(base) ? '' : cleanLabel(base);
    const template = {
      type: 'slide | pot | photomicrograph',
      label,
      questions: blankQuestions(label),
    };
    fs.writeFileSync(jsonPath, JSON.stringify(template, null, 2) + '\n');
    created++;
  }
}

if (!fs.existsSync(BANK_DIR)) {
  console.error('No /bank folder found.');
  process.exit(1);
}
walk(BANK_DIR);
console.log(`Created ${created} new template(s), added question slots to ${updated} existing JSON file(s). ${skipped} already had questions.`);
if (created || updated) console.log('Fill them in, then run: node build-bank.js');

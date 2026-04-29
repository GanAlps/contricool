#!/usr/bin/env node
/**
 * Phase 2d bundle-size gate.
 * Gzips the largest JS chunk in dist/_expo/static/js/web/ and asserts:
 *   - WARN if largest chunk > 250 KB gz
 *   - FAIL if largest chunk > 300 KB gz
 *
 * Run after `expo export -p web` from apps/client/.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

const BUNDLE_DIR = 'dist/_expo/static/js/web';
const WARN_KB = 250;
const FAIL_KB = 300;

let dirContents;
try {
  dirContents = readdirSync(BUNDLE_DIR);
} catch (err) {
  console.error(`[bundle-size] missing ${BUNDLE_DIR}; did you run \`expo export -p web\`?`);
  process.exit(1);
}

const jsFiles = dirContents.filter((f) => f.endsWith('.js'));
if (jsFiles.length === 0) {
  console.error(`[bundle-size] no .js files in ${BUNDLE_DIR}`);
  process.exit(1);
}

let largest = { name: '', bytes: 0 };
for (const f of jsFiles) {
  const p = join(BUNDLE_DIR, f);
  const buf = readFileSync(p);
  const gz = gzipSync(buf);
  if (gz.byteLength > largest.bytes) {
    largest = { name: f, bytes: gz.byteLength };
  }
}

const kb = largest.bytes / 1024;
const sizeStr = kb.toFixed(1);
console.log(`[bundle-size] largest chunk: ${largest.name} = ${sizeStr} KB gz`);

if (kb > FAIL_KB) {
  console.error(`[bundle-size] FAIL: ${sizeStr} KB > ${FAIL_KB} KB hard limit`);
  process.exit(2);
}
if (kb > WARN_KB) {
  console.warn(`[bundle-size] WARN: ${sizeStr} KB > ${WARN_KB} KB warning threshold`);
}
process.exit(0);

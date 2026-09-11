#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

function usage() {
  console.error('Usage: node src/clean.mjs <tmp-dir> <file> [file ...]');
  process.exitCode = 2;
}

const [directory, ...files] = process.argv.slice(2);
if (!directory || files.length === 0) {
  usage();
} else {
  const root = path.resolve(directory);
  const removed = [];
  for (const file of files) {
    const target = path.resolve(root, file);
    const relative = path.relative(root, target);
    if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
      throw new Error(`File must be inside the temporary directory: ${file}`);
    }
    if (fs.existsSync(target) && fs.statSync(target).isFile()) {
      fs.rmSync(target);
      removed.push(relative);
    }
  }
  console.log(JSON.stringify({ directory: root, removed }, null, 2));
}
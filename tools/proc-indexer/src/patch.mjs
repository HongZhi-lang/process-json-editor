#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { parseTree, findNodeAtLocation, getNodeValue, modify, applyEdits } from 'jsonc-parser';
import { fileURLToPath, pathToFileURL } from 'node:url';

const indexerPath = path.join(path.dirname(fileURLToPath(import.meta.url)), 'cli.mjs');
const { createIndex } = await import(pathToFileURL(indexerPath).href);

function usage() {
  console.error('Usage: node src/patch.mjs <PROC_*.json> <patch-plan.json> [--out <file>] [--in-place]');
  process.exitCode = 2;
}

function hash(buffer, algorithm) {
  return crypto.createHash(algorithm).update(buffer).digest('hex');
}

function decode(buffer) {
  if (buffer.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf]))) return buffer.subarray(3).toString('utf8');
  return buffer.toString('utf8');
}

function encode(text, original) {
  if (original.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf]))) return Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(text, 'utf8')]);
  return Buffer.from(text, 'utf8');
}

function pointer(pathText) {
  return pathText.split('.').filter(Boolean);
}

function locate(root, target) {
  if (target.entity === 'process') {
    const processPath = target.path === 'processName' ? ['processInfo', 'processName'] : pointer(target.path);
    return processPath;
  }
  if (target.entity === 'node') {
    const nodes = Array.isArray(root.nodeConf) ? root.nodeConf : [];
    const index = nodes.findIndex((node) => node?.actNodeId === target.id);
    if (index < 0) throw new Error(`Node ID not found: ${target.id}`);
    if (target.path === 'name' || target.path === 'actNodeName') return ['nodeConf', index, 'actNodeName'];
    return ['nodeConf', index, ...pointer(target.path)];
  }
  if (target.entity === 'tab') {
    const tabs = Array.isArray(root.tabConfig) ? root.tabConfig : [];
    const index = tabs.findIndex((tab) => tab?.id === target.id);
    if (index < 0) throw new Error(`Tab ID not found: ${target.id}`);
    return ['tabConfig', index, ...pointer(target.path)];
  }
  throw new Error(`Unsupported entity: ${target.entity}`);
}

function valueAt(root, jsonPath) {
  let value = root;
  for (const segment of jsonPath) value = value?.[segment];
  return value;
}

function replaceJsonValue(text, jsonPath, value) {
  const edits = modify(text, jsonPath, value, { formattingOptions: { insertSpaces: true, tabSize: 2, eol: '\n' } });
  return applyEdits(text, edits);
}

function replaceXmlNodeName(xml, nodeId, newName) {
  const escaped = nodeId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`(<(?:bpmn|cw):[\\w]+\\b(?=[^>]*\\bid=["']${escaped}["'])[^>]*\\bname=["'])([^"']*)(["'])`);
  if (!re.test(xml)) throw new Error(`XML node name not found for ID: ${nodeId}`);
  const xmlValue = String(newName).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return xml.replace(re, `$1${xmlValue.replace(/[$\\]/g, '\\$&')}$3`);
}

function assertPlan(plan, original) {
  if (plan?.schemaVersion !== 1 || !Array.isArray(plan.operations)) throw new Error('Patch plan must have schemaVersion 1 and operations[]');
  if (plan.fileSha256 && plan.fileSha256 !== hash(original, 'sha256')) throw new Error('Patch plan fileSha256 does not match the input file');
}

function replaceDestination(temp, destination, inPlace) {
  if (!inPlace) {
    fs.renameSync(temp, destination);
    return;
  }
  const backup = `${destination}.bak-${process.pid}`;
  fs.renameSync(destination, backup);
  try {
    fs.renameSync(temp, destination);
    fs.rmSync(backup, { force: true });
  } catch (error) {
    if (!fs.existsSync(destination) && fs.existsSync(backup)) fs.renameSync(backup, destination);
    throw error;
  }
}

function applyPlan(filePath, plan, outPath, inPlace) {
  const absolute = path.resolve(filePath);
  const original = fs.readFileSync(absolute);
  assertPlan(plan, original);
  let text = decode(original);
  let root = JSON.parse(text);
  const changes = [];
  for (const operation of plan.operations) {
    if (operation.op === 'replace') {
      const jsonPath = locate(root, operation.target);
      const oldValue = valueAt(root, jsonPath);
      if (JSON.stringify(oldValue) !== JSON.stringify(operation.expectedOldValue)) throw new Error(`expectedOldValue mismatch at ${jsonPath.join('.')}`);
      text = replaceJsonValue(text, jsonPath, operation.newValue);
      root = JSON.parse(text);
      if (operation.target.entity === 'node' && (operation.target.path === 'name' || operation.target.path === 'actNodeName')) {
        const xml = root.processInfo?.processXml;
        root.processInfo.processXml = replaceXmlNodeName(xml, operation.target.id, operation.newValue);
        text = replaceJsonValue(text, ['processInfo', 'processXml'], root.processInfo.processXml);
        root = JSON.parse(text);
      }
      changes.push(operation);
    } else if (operation.op === 'append') {
      const jsonPath = pointer(operation.target.path);
      const current = valueAt(root, jsonPath);
      if (!Array.isArray(current)) throw new Error(`Append target is not an array: ${operation.target.path}`);
      text = replaceJsonValue(text, [...jsonPath, current.length], operation.value);
      root = JSON.parse(text);
      changes.push(operation);
    } else {
      throw new Error(`Unsupported operation: ${operation.op}`);
    }
  }
  const result = encode(text, original);
  const destination = inPlace ? absolute : path.resolve(outPath ?? `${absolute}.patched.json`);
  if (!inPlace && destination === absolute) throw new Error('Output path must differ from the input path');
  const temp = `${destination}.tmp-${process.pid}`;
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(temp, result);
  try {
    const check = createIndex(temp);
    if (check.references.missingXmlNodeIds.length || check.references.missingTabIds.length) throw new Error('Patched file has unresolved node or Tab references');
    replaceDestination(temp, destination, inPlace);
  } catch (error) {
    fs.rmSync(temp, { force: true });
    throw error;
  }
  return { output: destination, sha256: hash(result, 'sha256'), md5: hash(result, 'md5'), changes: changes.length };
}

async function main(argv) {
  const args = [...argv];
  const filePath = args.shift();
  const planPath = args.shift();
  const outIndex = args.indexOf('--out');
  const outPath = outIndex >= 0 ? args[outIndex + 1] : null;
  const inPlace = args.includes('--in-place');
  if (!filePath || !planPath || (outIndex >= 0 && !outPath) || (inPlace && outPath)) return usage();
  const plan = JSON.parse(decode(fs.readFileSync(path.resolve(planPath))));
  console.log(JSON.stringify(applyPlan(filePath, plan, outPath, inPlace), null, 2));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await main(process.argv.slice(2)); }
  catch (error) { console.error(`proc-patch: ${error.message}`); process.exitCode = 1; }
}

export { applyPlan };

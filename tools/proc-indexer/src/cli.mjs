#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const XML_NS = 'http://www.omg.org/spec/BPMN/20100524/MODEL';

function usage() {
  console.error('Usage: node src/cli.mjs <PROC_*.json> [--node <id-or-name>] [--out <file>]');
  process.exitCode = 2;
}

function hash(buffer, algorithm) {
  return crypto.createHash(algorithm).update(buffer).digest('hex');
}

function detectEncoding(buffer) {
  if (buffer.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf]))) return 'utf8-bom';
  if (buffer.subarray(0, 2).equals(Buffer.from([0xff, 0xfe]))) return 'utf16le-bom';
  return 'utf8';
}

function decode(buffer, encoding) {
  return encoding === 'utf8-bom' ? buffer.subarray(3).toString('utf8') : buffer.toString('utf8');
}

function parseAttributes(raw) {
  const attrs = Object.create(null);
  const re = /([:\w-]+)\s*=\s*("[^"]*"|'[^']*')/g;
  for (const match of raw.matchAll(re)) attrs[match[1]] = match[2].slice(1, -1);
  return attrs;
}

function parseXmlIndex(xml) {
  const elements = [];
  const byId = new Map();
  const flows = new Map();
  const tagRe = /<(?:bpmn|cw):([\w]+)\b([^>]*?)(\/?>)/g;
  for (const match of xml.matchAll(tagRe)) {
    const type = match[1];
    const attrs = parseAttributes(match[2]);
    if (type === 'incoming' || type === 'outgoing' || type === 'conditionExpression') continue;
    const id = attrs.id;
    if (!id) continue;
    const item = { id, type, name: attrs.name ?? null, sourceRef: attrs.sourceRef ?? null, targetRef: attrs.targetRef ?? null };
    elements.push(item);
    if (byId.has(id)) throw new Error(`Duplicate XML id: ${id}`);
    byId.set(id, item);
    if (type === 'sequenceFlow') flows.set(id, item);
  }
  const incoming = new Map();
  const outgoing = new Map();
  for (const flow of flows.values()) {
    if (!incoming.has(flow.targetRef)) incoming.set(flow.targetRef, []);
    if (!outgoing.has(flow.sourceRef)) outgoing.set(flow.sourceRef, []);
    incoming.get(flow.targetRef).push(flow.id);
    outgoing.get(flow.sourceRef).push(flow.id);
  }
  return { elements, byId, flows, incoming, outgoing };
}

function asArray(value) {
  return value == null ? [] : Array.isArray(value) ? value : [value];
}

function collectFieldCodes(data) {
  return asArray(data.formDef?.fieldList).map((field) => ({
    code: field.fieldCode ?? null,
    name: field.fieldName ?? null,
    type: field.fieldType ?? null,
  }));
}

function nodeCard(node, xml) {
  const xmlNode = xml.byId.get(node.actNodeId);
  const flowIds = [...asArray(node.applyConf).map((item) => item?.actLineId).filter(Boolean)];
  const tabIds = asArray(node.nodeFormConf?.actTabGroupInfo).flatMap((group) => asArray(group?.tabIds)).filter(Boolean);
  const formGroups = Object.keys(node.nodeFormConf?.actFormInfo ?? {});
  return {
    id: node.actNodeId ?? null,
    name: node.actNodeName ?? null,
    type: node.actNodeType ?? null,
    xml: xmlNode ? { type: xmlNode.type, name: xmlNode.name } : null,
    incoming: asArray(xml.incoming.get(node.actNodeId)),
    outgoing: asArray(xml.outgoing.get(node.actNodeId)),
    gatewayLines: flowIds,
    formId: node.nodeFormConf?.mdlFormId ?? null,
    formGroups,
    tabIds: [...new Set(tabIds)],
  };
}

function createIndex(filePath) {
  const absolutePath = path.resolve(filePath);
  const buffer = fs.readFileSync(absolutePath);
  const encoding = detectEncoding(buffer);
  const text = decode(buffer, encoding);
  const data = JSON.parse(text);
  const xmlText = data.processInfo?.processXml;
  if (typeof xmlText !== 'string') throw new Error('processInfo.processXml is missing or is not a string');
  const xml = parseXmlIndex(xmlText);
  const nodes = asArray(data.nodeConf).map((node) => nodeCard(node, xml));
  const nodeConfIds = new Set(nodes.map((node) => node.id).filter(Boolean));
  const missingNodeConfIds = nodes.filter((node) => !node.xml).map((node) => node.id);
  const referencedTabs = [...new Set(nodes.flatMap((node) => node.tabIds))];
  const tabs = asArray(data.tabConfig).map((tab) => ({ id: tab.id ?? null, name: tab.tabName ?? null, alias: tab.tabAlias ?? null }));
  const tabIds = new Set(tabs.map((tab) => tab.id).filter(Boolean));
  return {
    schemaVersion: 1,
    file: {
      path: absolutePath,
      bytes: buffer.byteLength,
      sha256: hash(buffer, 'sha256'),
      md5: hash(buffer, 'md5'),
      encoding,
      newline: text.includes('\r\n') ? 'CRLF' : text.includes('\n') ? 'LF' : 'none',
    },
    process: {
      id: data.processInfo?.id ?? null,
      name: data.processInfo?.processName ?? null,
      type: data.processInfo?.processType ?? null,
      firstNodeId: data.firstNodeId ?? null,
      xmlLength: xmlText.length,
      xmlElementCount: xml.elements.length,
      sequenceFlowCount: xml.flows.size,
    },
    nodes,
    fields: collectFieldCodes(data),
    tabs,
    references: {
      nodeConfCount: nodeConfIds.size,
      missingXmlNodeIds: missingNodeConfIds,
      missingTabIds: referencedTabs.filter((id) => !tabIds.has(id)),
    },
  };
}

export { createIndex };

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`proc-index: ${error.message}`);
    process.exitCode = 1;
  }
}

function main(argv) {
  const args = [...argv];
  const filePath = args.shift();
  if (!filePath || filePath.startsWith('-')) return usage();
  const nodeFilterIndex = args.indexOf('--node');
  const nodeFilter = nodeFilterIndex >= 0 ? args[nodeFilterIndex + 1] : null;
  const outIndex = args.indexOf('--out');
  const outPath = outIndex >= 0 ? args[outIndex + 1] : null;
  if ((nodeFilterIndex >= 0 && !nodeFilter) || (outIndex >= 0 && !outPath)) return usage();
  const result = createIndex(filePath);
  if (nodeFilter) {
    result.nodes = result.nodes.filter((node) => node.id === nodeFilter || node.name === nodeFilter);
    if (result.nodes.length === 0) throw new Error(`No node matched: ${nodeFilter}`);
  }
  const output = JSON.stringify(result, null, 2) + '\n';
  if (outPath) fs.writeFileSync(path.resolve(outPath), output, 'utf8');
  else process.stdout.write(output);
}

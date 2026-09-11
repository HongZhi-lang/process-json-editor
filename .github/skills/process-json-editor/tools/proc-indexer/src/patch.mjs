#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { parseTree, findNodeAtLocation, getNodeValue, modify, applyEdits } from 'jsonc-parser';
import { fileURLToPath, pathToFileURL } from 'node:url';

const indexerPath = path.join(path.dirname(fileURLToPath(import.meta.url)), 'cli.mjs');
const { createIndex } = await import(pathToFileURL(indexerPath).href);
const validatorPath = path.join(path.dirname(fileURLToPath(import.meta.url)), 'validate.mjs');
const { validate } = await import(pathToFileURL(validatorPath).href);

function usage() {
  console.error('Usage: node src/patch.mjs <PROC_*.json> <patch-plan.json> [--out <file>] [--in-place] [--cleanup <file> ...]');
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

function parseXmlTopology(xml) {
  const elements = [];
  const byId = new Map();
  const flows = new Map();
  const tagRe = /<(?:bpmn|cw):([\w]+)\b([^>]*?)(\/?>)/g;
  for (const match of xml.matchAll(tagRe)) {
    const attrs = Object.fromEntries([...match[2].matchAll(/([:\w-]+)\s*=\s*(["'])(.*?)\2/g)].map((item) => [item[1], item[3]]));
    if (!attrs.id || ['incoming', 'outgoing', 'conditionExpression'].includes(match[1])) continue;
    const item = { id: attrs.id, type: match[1], name: attrs.name ?? null, sourceRef: attrs.sourceRef ?? null, targetRef: attrs.targetRef ?? null };
    elements.push(item);
    byId.set(item.id, item);
    if (item.type === 'sequenceFlow') flows.set(item.id, item);
  }
  const incoming = new Map();
  const outgoing = new Map();
  for (const flow of flows.values()) {
    if (!incoming.has(flow.targetRef)) incoming.set(flow.targetRef, []);
    if (!outgoing.has(flow.sourceRef)) outgoing.set(flow.sourceRef, []);
    incoming.get(flow.targetRef).push(flow);
    outgoing.get(flow.sourceRef).push(flow);
  }
  return { elements, byId, flows, incoming, outgoing };
}

function parseXmlElements(xml) {
  const elements = [];
  const stack = [];
  const tagRe = /<\/?((?:bpmn|cw|bpmndi|dc|di):[\w]+)\b([^>]*?)>/g;
  for (const match of xml.matchAll(tagRe)) {
    const raw = match[0];
    const name = match[1];
    if (raw.startsWith('</')) {
      const opening = stack.pop();
      if (opening && opening.name === name) {
        opening.end = match.index + raw.length;
        elements.push(opening);
      }
      continue;
    }
    const attrs = Object.fromEntries([...match[2].matchAll(/([:\w-]+)\s*=\s*(["'])(.*?)\2/g)].map((item) => [item[1], item[3]]));
    const item = { name, attrs, start: match.index, openEnd: match.index + raw.length, end: match.index + raw.length };
    if (/\/\s*>$/.test(raw)) elements.push(item);
    else stack.push(item);
  }
  return elements;
}

function findXmlElement(xml, predicate) {
  return parseXmlElements(xml).find((element) => predicate(element)) ?? null;
}

function removeXmlSpan(xml, element, label) {
  if (!element) throw new Error(`XML element not found: ${label}`);
  return `${xml.slice(0, element.start)}${xml.slice(element.end)}`;
}

function removeXmlElement(xml, id) {
  return removeXmlSpan(xml, findXmlElement(xml, (element) => element.attrs.id === id), id);
}

function removeXmlDiagramElement(xml, bpmnElement) {
  const element = findXmlElement(xml, (item) => item.attrs.bpmnElement === bpmnElement);
  return element ? removeXmlSpan(xml, element, bpmnElement) : xml;
}

function removeXmlReference(xml, nodeId, direction, flowId) {
  const escapedFlow = flowId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const tag = direction === 'incoming' ? 'incoming' : 'outgoing';
  return xml.replace(new RegExp(`\\s*<(?:bpmn|cw):${tag}>${escapedFlow}<\\/(?:bpmn|cw):${tag}>`, 'g'), '');
}

function addXmlReference(xml, nodeId, direction, flowId) {
  const escapedNode = nodeId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const tag = direction === 'incoming' ? 'incoming' : 'outgoing';
  const selfClosingRe = new RegExp(`<((?:bpmn|cw):[\\w]+)\\b(?=[^>]*\\bid=["']${escapedNode}["'])[^>]*\\/>`, 'm');
  const selfClosing = selfClosingRe.exec(xml);
  if (selfClosing) {
    const opening = selfClosing[0].replace(/\s*\/>$/, '>');
    const prefix = selfClosing[1].split(':')[0];
    const replacement = `${opening}\n      <${prefix}:${tag}>${flowId}</${prefix}:${tag}>\n    </${selfClosing[1]}>`;
    return xml.replace(selfClosingRe, replacement);
  }
  const nodeRe = new RegExp(`<((?:bpmn|cw):[\\w]+)\\b[^>]*\\bid=["']${escapedNode}["'][^>]*>`, 'm');
  const match = nodeRe.exec(xml);
  if (!match) throw new Error(`XML node not found for ${direction} reference: ${nodeId}`);
  const prefix = match[1].split(':')[0];
  return xml.replace(nodeRe, `${match[0]}\n      <${prefix}:${tag}>${flowId}</${prefix}:${tag}>`);
}

function createXmlNode(id, name, xmlType, incoming, outgoing) {
  const [prefix, localType] = xmlType.includes(':') ? xmlType.split(':', 2) : ['bpmn', xmlType];
  const attributes = [`id="${escapeXmlAttribute(id)}"`, `name="${escapeXmlAttribute(name)}"`];
  const bpmnPrefix = 'bpmn';
  const refs = [...incoming.map((flowId) => `      <${bpmnPrefix}:incoming>${flowId}</${bpmnPrefix}:incoming>`), ...outgoing.map((flowId) => `      <${bpmnPrefix}:outgoing>${flowId}</${bpmnPrefix}:outgoing>`)];
  return refs.length ? `    <${prefix}:${localType} ${attributes.join(' ')}>\n${refs.join('\n')}\n    </${prefix}:${localType}>\n` : `    <${prefix}:${localType} ${attributes.join(' ')} />\n`;
}

function ensureXmlNamespace(xml, prefix, namespace) {
  const rootMatch = /<([\w]+):definitions\b([^>]*)>/.exec(xml);
  if (!rootMatch) throw new Error('BPMN definitions root not found');
  if (new RegExp(`\\bxmlns:${prefix}=`).test(rootMatch[2])) return xml;
  const replacement = `<${rootMatch[1]}:definitions${rootMatch[2]} xmlns:${prefix}="${namespace}">`;
  return xml.replace(rootMatch[0], replacement);
}

function createXmlFlow(id, sourceRef, targetRef, attributes = {}) {
  const values = [`id="${escapeXmlAttribute(id)}"`, `sourceRef="${escapeXmlAttribute(sourceRef)}"`, `targetRef="${escapeXmlAttribute(targetRef)}"`];
  if (attributes.name) values.splice(1, 0, `name="${escapeXmlAttribute(attributes.name)}"`);
  return `    <bpmn:sequenceFlow ${values.join(' ')} />\n`;
}

function escapeXmlAttribute(value) {
  return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function insertBeforeProcessClose(xml, content) {
  const match = /<\/(?:bpmn|cw):process\s*>/.exec(xml);
  if (!match) throw new Error('XML process element not found');
  return `${xml.slice(0, match.index)}${content}${xml.slice(match.index)}`;
}

function insertBeforeDiagramClose(xml, content) {
  const match = /<\/bpmndi:BPMNPlane\s*>/.exec(xml);
  if (!match) throw new Error('BPMN diagram plane not found');
  return `${xml.slice(0, match.index)}${content}${xml.slice(match.index)}`;
}

function diagramBounds(xml, bpmnElement) {
  const shape = findXmlElement(xml, (element) => element.name === 'bpmndi:BPMNShape' && element.attrs.bpmnElement === bpmnElement);
  if (!shape) return null;
  const bounds = xml.slice(shape.openEnd, shape.end).match(/<dc:Bounds\b([^>]*?)\/>/);
  if (!bounds) return null;
  const attrs = Object.fromEntries([...bounds[1].matchAll(/([:\w-]+)\s*=\s*(["'])(.*?)\2/g)].map((item) => [item[1], Number(item[3])]));
  return { x: attrs.x ?? 0, y: attrs.y ?? 0, width: attrs.width ?? 100, height: attrs.height ?? 80 };
}

function diagramPoint(bounds, side) {
  if (side === 'left') return { x: bounds.x, y: bounds.y + bounds.height / 2 };
  if (side === 'right') return { x: bounds.x + bounds.width, y: bounds.y + bounds.height / 2 };
  return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
}

function diagramEndpoints(xml, sourceId, targetId) {
  const source = diagramBounds(xml, sourceId) ?? { x: 0, y: 0, width: 100, height: 80 };
  const target = diagramBounds(xml, targetId) ?? { x: source.x + 180, y: source.y, width: 100, height: 80 };
  const sourcePoint = diagramPoint(source, source.x <= target.x ? 'right' : 'left');
  const targetPoint = diagramPoint(target, source.x <= target.x ? 'left' : 'right');
  return { sourcePoint, targetPoint };
}

function createXmlShape(xml, nodeId, xmlType, sourceId, targetId) {
  const source = diagramBounds(xml, sourceId) ?? { x: 0, y: 0, width: 100, height: 80 };
  const target = diagramBounds(xml, targetId) ?? { x: source.x + 240, y: source.y, width: 100, height: 80 };
  const width = 100;
  const height = 80;
  const x = Math.round((source.x + source.width + target.x - width) / 2);
  const y = Math.round((source.y + target.y) / 2);
  return `    <bpmndi:BPMNShape id="${escapeXmlAttribute(nodeId)}_di" bpmnElement="${escapeXmlAttribute(nodeId)}">\n      <dc:Bounds x="${x}" y="${y}" width="${width}" height="${height}" />\n    </bpmndi:BPMNShape>\n`;
}

function createXmlEdge(xml, flowId, sourceId, targetId) {
  const { sourcePoint, targetPoint } = diagramEndpoints(xml, sourceId, targetId);
  return `    <bpmndi:BPMNEdge id="${escapeXmlAttribute(flowId)}_di" bpmnElement="${escapeXmlAttribute(flowId)}">\n      <di:waypoint x="${Math.round(sourcePoint.x)}" y="${Math.round(sourcePoint.y)}" />\n      <di:waypoint x="${Math.round(targetPoint.x)}" y="${Math.round(targetPoint.y)}" />\n    </bpmndi:BPMNEdge>\n`;
}

function synchronizeDiagram(xml) {
  const topology = parseXmlTopology(xml);
  let nextXml = xml;
  const shapeContent = [];
  for (const element of topology.elements) {
    if (element.type === 'sequenceFlow' || ['definitions', 'process'].includes(element.type)) continue;
    const shape = findXmlElement(nextXml, (item) => item.name === 'bpmndi:BPMNShape' && item.attrs.bpmnElement === element.id);
    if (!shape) {
      const incoming = topology.incoming.get(element.id)?.[0];
      const outgoing = topology.outgoing.get(element.id)?.[0];
      shapeContent.push(createXmlShape(nextXml, element.id, element.type, incoming?.sourceRef ?? element.id, outgoing?.targetRef ?? element.id));
    }
  }
  if (shapeContent.length) nextXml = insertBeforeDiagramClose(nextXml, shapeContent.join(''));
  const edgeContent = [];
  for (const flow of topology.flows.values()) {
    const edge = findXmlElement(nextXml, (item) => item.name === 'bpmndi:BPMNEdge' && item.attrs.bpmnElement === flow.id);
    if (edge) continue;
    edgeContent.push(createXmlEdge(nextXml, flow.id, flow.sourceRef, flow.targetRef));
  }
  if (edgeContent.length) nextXml = insertBeforeDiagramClose(nextXml, edgeContent.join(''));
  return nextXml;
}

function uniqueId(prefix, used) {
  let id;
  do id = `${prefix}_${crypto.randomBytes(6).toString('base64url')}`; while (used.has(id));
  return id;
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function emptyHandler(handler) {
  const result = clone(handler) ?? {};
  result.assignType = null;
  if (result.assignConf) {
    for (const key of ['choosedFields', 'choosedGroups', 'choosedPersons', 'choosedDutys', 'choosedBackupDutys', 'chooseBackupDutyPerson', 'choosedFollowFields']) {
      if (Array.isArray(result.assignConf[key])) result.assignConf[key] = [];
      else if (key in result.assignConf) result.assignConf[key] = null;
    }
  }
  return result;
}

function nodeXmlType(node) {
  if (node.xmlType) return node.xmlType.includes(':') ? node.xmlType : `${node.type === 'SINGLE_APPROVE_TASK' || node.type === 'MULTI_APPROVE_TASK' ? 'cw' : 'bpmn'}:${node.xmlType}`;
  return {
    USER_TASK: 'bpmn:userTask',
    END_TASK: 'bpmn:endEvent',
    START_TASK: 'bpmn:startEvent',
    EXCLUSIVE_GATEWAY: 'bpmn:exclusiveGateway',
    PARALLEL_GATEWAY: 'bpmn:parallelGateway',
    INCLUSIVE_GATEWAY: 'bpmn:inclusiveGateway',
    SINGLE_APPROVE_TASK: 'cw:singleApprove',
    MULTI_APPROVE_TASK: 'cw:multiApprove',
  }[node.type] ?? 'bpmn:userTask';
}

function isGatewayType(type) {
  return ['EXCLUSIVE_GATEWAY', 'PARALLEL_GATEWAY', 'INCLUSIVE_GATEWAY'].includes(type);
}

function newFormConfigId(usedIds) {
  let id;
  do id = crypto.randomBytes(16).toString('hex'); while (usedIds.has(id));
  usedIds.add(id);
  return id;
}

function nearestSameTypeNode(root, topology, sourceId, type) {
  const candidates = new Map((root.nodeConf ?? []).filter((node) => node?.actNodeType === type).map((node) => [node.actNodeId, node]));
  if (!candidates.size) return null;
  const queue = [[sourceId, 0]];
  const visited = new Set([sourceId]);
  while (queue.length) {
    const [nodeId, distance] = queue.shift();
    if (distance > 0 && candidates.has(nodeId)) return candidates.get(nodeId);
    const neighbors = [
      ...(topology.incoming.get(nodeId) ?? []).map((flow) => flow.sourceRef),
      ...(topology.outgoing.get(nodeId) ?? []).map((flow) => flow.targetRef),
    ];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        visited.add(neighbor);
        queue.push([neighbor, distance + 1]);
      }
    }
  }
  return candidates.values().next().value ?? null;
}

function updateApplyConf(root, nodeId, removedFlowIds, addedFlowIds) {
  const index = (root.nodeConf ?? []).findIndex((node) => node?.actNodeId === nodeId);
  if (index < 0) return;
  const current = root.nodeConf[index].applyConf;
  if (!Array.isArray(current)) return;
  const next = current.filter((item) => !removedFlowIds.includes(item?.actLineId));
  const template = current.find((item) => removedFlowIds.includes(item?.actLineId));
  for (const flowId of addedFlowIds) {
    const item = clone(template) ?? { actLineId: flowId };
    item.actLineId = flowId;
    next.push(item);
  }
  root.nodeConf[index].applyConf = next;
}

function resolveFlow(topology, operation) {
  if (operation.flowId) {
    const flow = topology.flows.get(operation.flowId);
    if (!flow) throw new Error(`Sequence flow not found: ${operation.flowId}`);
    return flow;
  }
  let matches;
  if (operation.afterNodeId) {
    matches = topology.outgoing.get(operation.afterNodeId) ?? [];
  } else if (operation.beforeNodeId) {
    matches = topology.incoming.get(operation.beforeNodeId) ?? [];
  } else {
    matches = [...topology.flows.values()].filter((flow) => flow.sourceRef === operation.fromId && flow.targetRef === operation.toId);
  }
  if (matches.length !== 1) throw new Error(`Expected exactly one sequence flow from ${operation.fromId} to ${operation.toId}, found ${matches.length}`);
  return matches[0];
}

function topologyDiagnostic(message, topology, nodeId) {
  const incoming = (topology.incoming.get(nodeId) ?? []).map((flow) => ({ id: flow.id, from: flow.sourceRef, to: flow.targetRef }));
  const outgoing = (topology.outgoing.get(nodeId) ?? []).map((flow) => ({ id: flow.id, from: flow.sourceRef, to: flow.targetRef }));
  throw new Error(`${message}\n${JSON.stringify({ nodeId, incoming, outgoing }, null, 2)}`);
}

function appendXmlFlowReferences(xml, nodeId, direction, flowIds) {
  return flowIds.reduce((result, flowId) => addXmlReference(result, nodeId, direction, flowId), xml);
}

function insertNode(root, text, operation) {
  const xml = root.processInfo?.processXml;
  const topology = parseXmlTopology(xml);
  const edge = resolveFlow(topology, operation);
  const sourceNode = root.nodeConf?.find((node) => node?.actNodeId === edge.sourceRef);
  const nodeSpec = operation.node ?? {};
  const usedIds = new Set(topology.elements.map((item) => item.id));
  const xmlType = nodeXmlType(nodeSpec);
  const nodeId = nodeSpec.id ?? uniqueId(xmlType.split(':').at(-1) === 'userTask' ? 'UserTask' : xmlType.split(':').at(-1), usedIds);
  if (usedIds.has(nodeId)) throw new Error(`New node ID already exists: ${nodeId}`);
  const nodeName = nodeSpec.name;
  if (!nodeName) throw new Error('insertNode requires node.name');
  const firstFlowId = operation.beforeFlowId ?? uniqueId('SequenceFlow', usedIds);
  usedIds.add(firstFlowId);
  const secondFlowId = operation.afterFlowId ?? uniqueId('SequenceFlow', usedIds);
  if (firstFlowId === secondFlowId || usedIds.has(secondFlowId)) throw new Error(`New sequence flow ID already exists: ${secondFlowId}`);
  const type = nodeSpec.type ?? 'USER_TASK';
  const template = operation.templateNodeId
    ? root.nodeConf?.find((node) => node?.actNodeId === operation.templateNodeId)
    : nearestSameTypeNode(root, topology, edge.sourceRef, type) ?? sourceNode;
  if (['SINGLE_APPROVE_TASK', 'MULTI_APPROVE_TASK'].includes(type) && !operation.templateNodeId && !nearestSameTypeNode(root, topology, edge.sourceRef, type) && !nodeSpec.config && !nodeSpec.handlerConf) {
    throw new Error(`No same-type approval template found for ${type}; provide templateNodeId or explicit node.config`);
  }
  const nodeConf = clone(nodeSpec.config ?? template);
  if (!nodeConf) throw new Error('insertNode requires node.config or a template node');
  nodeConf.actNodeId = nodeId;
  nodeConf.actNodeName = nodeName;
  nodeConf.actNodeType = type;
  nodeConf.isFirst = 0;
  nodeConf.handlerConf = clone(nodeSpec.handlerConf ?? (template?.handlerConf ?? {}));
  nodeConf.handlerConf.actNodeId = null;
  nodeConf.handlerConf.actNodeName = null;
  if (nodeSpec.handlerConf == null) nodeConf.handlerConf = emptyHandler(nodeConf.handlerConf);
  nodeConf.nodeFormConf = clone(nodeSpec.formConfig ?? nodeConf.nodeFormConf ?? template?.nodeFormConf);
  if (nodeConf.nodeFormConf) {
    const formIds = new Set((root.nodeConf ?? []).map((node) => node?.nodeFormConf?.id).filter(Boolean));
    nodeConf.nodeFormConf.id = nodeConf.nodeFormConf.id && !formIds.has(nodeConf.nodeFormConf.id) ? nodeConf.nodeFormConf.id : newFormConfigId(formIds);
    nodeConf.nodeFormConf.actNodeId = nodeId;
  }
  nodeConf.applyConf = isGatewayType(type) ? [] : null;
  const newXmlNode = createXmlNode(nodeId, nodeName, xmlType, [firstFlowId], [secondFlowId]);
  let nextXml = removeXmlElement(xml, edge.id);
  if (xmlType.startsWith('cw:')) nextXml = ensureXmlNamespace(nextXml, 'cw', 'http://www.cloudwise.com/BPMN/20220520/MODEL');
  nextXml = removeXmlDiagramElement(nextXml, edge.id);
  nextXml = removeXmlReference(nextXml, edge.sourceRef, 'outgoing', edge.id);
  nextXml = removeXmlReference(nextXml, edge.targetRef, 'incoming', edge.id);
  nextXml = appendXmlFlowReferences(nextXml, edge.sourceRef, 'outgoing', [firstFlowId]);
  nextXml = appendXmlFlowReferences(nextXml, edge.targetRef, 'incoming', [secondFlowId]);
  nextXml = insertBeforeProcessClose(nextXml, `${newXmlNode}${createXmlFlow(firstFlowId, edge.sourceRef, nodeId)}${createXmlFlow(secondFlowId, nodeId, edge.targetRef, { name: edge.name })}`);
  nextXml = insertBeforeDiagramClose(nextXml, `${createXmlShape(nextXml, nodeId, xmlType, edge.sourceRef, edge.targetRef)}${createXmlEdge(nextXml, firstFlowId, edge.sourceRef, nodeId)}${createXmlEdge(nextXml, secondFlowId, nodeId, edge.targetRef)}`);
  root.processInfo.processXml = nextXml;
  const sourceIndex = root.nodeConf.findIndex((node) => node?.actNodeId === edge.sourceRef);
  updateApplyConf(root, edge.sourceRef, [edge.id], [firstFlowId]);
  root.nodeConf.push(nodeConf);
  text = replaceJsonValue(text, ['processInfo', 'processXml'], nextXml);
  if (sourceIndex >= 0) text = replaceJsonValue(text, ['nodeConf', sourceIndex, 'applyConf'], root.nodeConf[sourceIndex].applyConf);
  text = replaceJsonValue(text, ['nodeConf', root.nodeConf.length - 1], nodeConf);
  root = JSON.parse(text);
  return { root, text, change: operation };
}

function collectDiscardedBranch(topology, startId, retainedIds, parentId) {
  const removeNodes = new Set();
  const removeFlows = new Set();
  const queue = [startId];
  while (queue.length) {
    const nodeId = queue.shift();
    if (retainedIds.has(nodeId) || removeNodes.has(nodeId)) continue;
    const xmlNode = topology.byId.get(nodeId);
    if (xmlNode?.type === 'startEvent' || xmlNode?.type === 'endEvent') continue;
    const incoming = topology.incoming.get(nodeId) ?? [];
    if (incoming.some((flow) => flow.sourceRef !== parentId && !removeNodes.has(flow.sourceRef))) continue;
    removeNodes.add(nodeId);
    for (const flow of incoming) removeFlows.add(flow.id);
    for (const flow of topology.outgoing.get(nodeId) ?? []) {
      removeFlows.add(flow.id);
      queue.push(flow.targetRef);
    }
  }
  return { removeNodes, removeFlows };
}

function removeNode(root, text, operation) {
  const xml = root.processInfo?.processXml;
  const topology = parseXmlTopology(xml);
  const nodeId = operation.target?.id ?? operation.nodeId;
  const nodeIndex = (root.nodeConf ?? []).findIndex((node) => node?.actNodeId === nodeId);
  if (nodeIndex < 0) throw new Error(`Node ID not found: ${nodeId}`);
  const incoming = topology.incoming.get(nodeId) ?? [];
  const outgoing = topology.outgoing.get(nodeId) ?? [];
  if (outgoing.length > 1 && !operation.keepOutgoingFlowId) topologyDiagnostic('Removing a node with multiple outgoing flows requires keepOutgoingFlowId', topology, nodeId);
  const keepOutgoing = operation.keepOutgoingFlowId ? outgoing.find((flow) => flow.id === operation.keepOutgoingFlowId) : outgoing[0];
  if (operation.keepOutgoingFlowId && !keepOutgoing) throw new Error(`Outgoing flow not found on node ${nodeId}: ${operation.keepOutgoingFlowId}`);
  const gatewayParents = incoming.filter((flow) => (topology.outgoing.get(flow.sourceRef) ?? []).length > 1);
  if (gatewayParents.length && !operation.confirmGatewayCollapse) {
    topologyDiagnostic('Removing this node collapses a gateway branch; confirmGatewayCollapse is required', topology, nodeId);
  }
  const removeFlowIds = new Set([...incoming, ...outgoing].map((flow) => flow.id));
  const removeNodeIds = new Set([nodeId]);
  if (outgoing.length > 1) {
    const retainedIds = new Set([keepOutgoing.targetRef]);
    for (const flow of outgoing) {
      if (flow.id === keepOutgoing.id) continue;
      const branch = collectDiscardedBranch(topology, flow.targetRef, retainedIds, nodeId);
      for (const id of branch.removeNodes) removeNodeIds.add(id);
      for (const id of branch.removeFlows) removeFlowIds.add(id);
    }
  }
  let nextXml = xml;
  for (const flowId of removeFlowIds) nextXml = removeXmlElement(nextXml, flowId);
  for (const flowId of removeFlowIds) nextXml = removeXmlDiagramElement(nextXml, flowId);
  for (const id of removeNodeIds) nextXml = removeXmlElement(nextXml, id);
  for (const id of removeNodeIds) nextXml = removeXmlDiagramElement(nextXml, id);
  for (const flow of topology.flows.values()) {
    if (!removeFlowIds.has(flow.id)) continue;
    nextXml = removeXmlReference(nextXml, flow.sourceRef, 'outgoing', flow.id);
    nextXml = removeXmlReference(nextXml, flow.targetRef, 'incoming', flow.id);
  }
  const replacementFlows = [];
  const usedFlowIds = new Set(topology.elements.map((item) => item.id).concat([...removeFlowIds]));
  if (keepOutgoing) {
    const targetRef = keepOutgoing.targetRef;
    for (const flow of incoming) {
      const flowId = uniqueId('SequenceFlow', usedFlowIds);
      usedFlowIds.add(flowId);
      replacementFlows.push({ id: flowId, sourceRef: flow.sourceRef, targetRef });
      nextXml = appendXmlFlowReferences(nextXml, flow.sourceRef, 'outgoing', [flowId]);
      nextXml = appendXmlFlowReferences(nextXml, targetRef, 'incoming', [flowId]);
      updateApplyConf(root, flow.sourceRef, [flow.id], [flowId]);
    }
    nextXml = insertBeforeProcessClose(nextXml, replacementFlows.map((flow) => createXmlFlow(flow.id, flow.sourceRef, flow.targetRef)).join(''));
    nextXml = insertBeforeDiagramClose(nextXml, replacementFlows.map((flow) => createXmlEdge(nextXml, flow.id, flow.sourceRef, flow.targetRef)).join(''));
  }
  root.processInfo.processXml = nextXml;
  text = replaceJsonValue(text, ['processInfo', 'processXml'], nextXml);
  const removedIndexes = [];
  for (const [index, node] of root.nodeConf.entries()) {
    if (removeNodeIds.has(node?.actNodeId)) removedIndexes.push(index);
  }
  for (const [index, node] of root.nodeConf.entries()) {
    if (!removeNodeIds.has(node?.actNodeId) && node?.applyConf !== undefined) {
      text = replaceJsonValue(text, ['nodeConf', index, 'applyConf'], node.applyConf);
    }
  }
  for (const index of removedIndexes.sort((a, b) => b - a)) text = replaceJsonValue(text, ['nodeConf', index], undefined);
  root = JSON.parse(text);
  return { root, text, change: operation };
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

function cleanupFiles(files, source, destination) {
  const protectedPaths = new Set([path.resolve(source), path.resolve(destination)]);
  const removed = [];
  for (const file of files) {
    const target = path.resolve(file);
    if (protectedPaths.has(target)) throw new Error(`Refusing to clean source or output file: ${file}`);
    if (fs.existsSync(target) && fs.statSync(target).isFile()) {
      fs.rmSync(target);
      removed.push(target);
    }
  }
  return removed;
}

function applyPlan(filePath, plan, outPath, inPlace, cleanup = []) {
  const absolute = path.resolve(filePath);
  const original = fs.readFileSync(absolute);
  assertPlan(plan, original);
  let text = decode(original);
  let root = JSON.parse(text);
  const changes = [];
  let hasTopologyChange = false;
  for (const operation of plan.operations) {
    if (operation.op === 'insertNode') {
      const result = insertNode(root, text, operation);
      root = result.root;
      text = result.text;
      hasTopologyChange = true;
      changes.push(operation);
    } else if (operation.op === 'removeNode') {
      const result = removeNode(root, text, operation);
      root = result.root;
      text = result.text;
      hasTopologyChange = true;
      changes.push(operation);
    } else if (operation.op === 'replace') {
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
  if (hasTopologyChange) {
    const synchronizedXml = synchronizeDiagram(root.processInfo.processXml);
    text = replaceJsonValue(text, ['processInfo', 'processXml'], synchronizedXml);
  }
  const result = encode(text, original);
  const destination = inPlace ? absolute : path.resolve(outPath ?? `${absolute}.patched.json`);
  if (!inPlace && destination === absolute) throw new Error('Output path must differ from the input path');
  const temp = `${destination}.tmp-${process.pid}`;
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(temp, result);
  try {
    const check = createIndex(temp);
    if (check.references.missingXmlNodeIds.length || check.references.missingTabIds.length || check.references.missingDiagramNodeIds.length || check.references.missingDiagramFlowIds.length) {
      throw new Error(`Patched file has unresolved references: ${JSON.stringify(check.references)}`);
    }
    const validationErrors = validate(temp);
    if (validationErrors.length) throw new Error(`Patched file failed validation:\n- ${validationErrors.join('\n- ')}`);
    replaceDestination(temp, destination, inPlace);
  } catch (error) {
    fs.rmSync(temp, { force: true });
    throw error;
  }
  const removed = cleanupFiles(cleanup, absolute, destination);
  return { output: destination, sha256: hash(result, 'sha256'), md5: hash(result, 'md5'), changes: changes.length, cleaned: removed };
}

async function main(argv) {
  const args = [...argv];
  const filePath = args.shift();
  const planPath = args.shift();
  const outIndex = args.indexOf('--out');
  const outPath = outIndex >= 0 ? args[outIndex + 1] : null;
  const inPlace = args.includes('--in-place');
  const cleanupIndex = args.indexOf('--cleanup');
  const cleanup = cleanupIndex >= 0 ? args.slice(cleanupIndex + 1).filter((arg) => !arg.startsWith('--')) : [];
  if (!filePath || !planPath || (outIndex >= 0 && !outPath) || (inPlace && outPath) || (cleanupIndex >= 0 && cleanup.length === 0)) return usage();
  const plan = JSON.parse(decode(fs.readFileSync(path.resolve(planPath))));
  console.log(JSON.stringify(applyPlan(filePath, plan, outPath, inPlace, cleanup), null, 2));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await main(process.argv.slice(2)); }
  catch (error) { console.error(`proc-patch: ${error.message}`); process.exitCode = 1; }
}

export { applyPlan };

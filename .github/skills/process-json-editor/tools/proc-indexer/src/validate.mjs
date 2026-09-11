#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createIndex } from './cli.mjs';

function usage() {
  console.error('Usage: node src/validate.mjs <PROC_*.json>');
  process.exitCode = 2;
}

function asArray(value) {
  return value == null ? [] : Array.isArray(value) ? value : [value];
}

function collectFieldReferences(value, references = []) {
  if (Array.isArray(value)) {
    for (const item of value) collectFieldReferences(item, references);
  } else if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (['requireGroup', 'disabledGroup', 'hideGroup'].includes(key) && Array.isArray(child)) {
        references.push(...child.map(String));
      } else {
        collectFieldReferences(child, references);
      }
    }
  }
  return references;
}

function extractXmlNamespaceErrors(xml) {
  const errors = [];
  const root = /^\s*<([\w-]+):definitions\b([^>]*)>/m.exec(xml);
  if (!root) return ['BPMN definitions root not found.'];
  const declared = new Set([...root[2].matchAll(/xmlns:([\w-]+)\s*=/g)].map((match) => match[1]));
  for (const match of xml.matchAll(/<\/?([\w-]+):[\w-]+\b/g)) {
    if (!declared.has(match[1])) errors.push(`XML namespace prefix is not declared: ${match[1]}`);
  }
  return errors;
}

function flowXmlBlock(xml, flowId) {
  const escaped = flowId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return xml.match(new RegExp(`<bpmn:sequenceFlow\\b[^>]*\\bid=["']${escaped}["'][\\s\\S]*?(?:<\\/bpmn:sequenceFlow>|\\/>)`))?.[0] ?? null;
}

function validateGatewayConditions(node, xml, errors) {
  const applies = asArray(node.applyConf);
  if (!applies.length) return;
  const gatewayTypes = new Set(['EXCLUSIVE_GATEWAY', 'PARALLEL_GATEWAY', 'INCLUSIVE_GATEWAY']);
  if (!gatewayTypes.has(node.actNodeType)) {
    errors.push(`Non-gateway node must not contain applyConf: ${node.actNodeId}`);
    return;
  }
  for (const apply of applies) {
    const flowId = String(apply?.actLineId ?? '');
    const block = flowXmlBlock(xml, flowId);
    if (!block) continue;
    const expression = block.match(/<bpmn:conditionExpression\b[^>]*>([\s\S]*?)<\/bpmn:conditionExpression>/)?.[1] ?? '';
    if (!expression.trim()) errors.push(`Gateway flow is missing conditionExpression: ${flowId}`);
    const lineName = apply?.actLineName;
    const xmlName = block.match(/\bname=["']([^"']*)["']/)?.[1];
    if (lineName && xmlName && String(lineName) !== xmlName) errors.push(`Gateway line name mismatch for ${flowId}.`);
  }
}

function collectFormFieldCodes(value, codes = new Set()) {
  if (Array.isArray(value)) {
    for (const item of value) collectFormFieldCodes(item, codes);
  } else if (value && typeof value === 'object') {
    if (value.xProps?.fieldCode) codes.add(String(value.xProps.fieldCode));
    if (value['x-props']?.fieldCode) codes.add(String(value['x-props'].fieldCode));
    for (const child of Object.values(value)) collectFormFieldCodes(child, codes);
  }
  return codes;
}

function validate(filePath) {
  const absolutePath = path.resolve(filePath);
  const data = JSON.parse(fs.readFileSync(absolutePath, 'utf8'));
  const errors = [];
  if (!data.processInfo) errors.push('Missing processInfo.');
  if (typeof data.processInfo?.processXml !== 'string') errors.push('processInfo.processXml is missing or is not a string.');
  const processXml = data.processInfo?.processXml ?? '';
  errors.push(...extractXmlNamespaceErrors(processXml));

  let index;
  try {
    index = createIndex(absolutePath);
  } catch (error) {
    errors.push(error.message);
    return errors;
  }

  const nodeById = new Map(index.nodes.map((node) => [node.id, node]));
  const flowIds = new Set(index.flows.map((flow) => flow.id));
  const formFieldCodes = new Set(asArray(data.formDef?.fieldList).map((field) => String(field?.fieldCode ?? '')).filter(Boolean));
  for (const code of collectFormFieldCodes(data.formDef?.formInfo)) formFieldCodes.add(code);
  const formConfigIds = new Map();
  const firstNodes = [];
  for (const node of asArray(data.nodeConf)) {
    const nodeId = String(node?.actNodeId ?? '');
    if (!nodeId) {
      errors.push('nodeConf contains an entry without actNodeId.');
      continue;
    }
    const indexedNode = nodeById.get(nodeId);
    if (!indexedNode) {
      errors.push(`nodeConf actNodeId does not exist in processXml: ${nodeId}`);
      continue;
    }
    if (node.isFirst === 1) firstNodes.push(nodeId);
    const formConfigId = node.nodeFormConf?.id;
    if (formConfigId) {
      if (formConfigIds.has(formConfigId)) errors.push(`Duplicate nodeFormConf.id '${formConfigId}' on nodes '${formConfigIds.get(formConfigId)}' and '${nodeId}'.`);
      else formConfigIds.set(formConfigId, nodeId);
    }
    if (node.nodeFormConf?.actNodeId && String(node.nodeFormConf.actNodeId) !== nodeId) errors.push(`nodeFormConf.actNodeId mismatch for ${nodeId}.`);
    if (indexedNode.xml?.name && String(node.actNodeName ?? '') !== indexedNode.xml.name) {
      errors.push(`Node name mismatch for ${nodeId}: nodeConf='${node.actNodeName}', XML='${indexedNode.xml.name}'`);
    }
    for (const apply of asArray(node.applyConf)) {
      const lineId = String(apply?.actLineId ?? '');
      if (lineId && !flowIds.has(lineId)) errors.push(`Gateway line does not exist in processXml: ${lineId}`);
    }
    validateGatewayConditions(node, processXml, errors);
    const formId = data.formDef?.id;
    const nodeFormId = node.nodeFormConf?.mdlFormId;
    if (formId && nodeFormId && String(formId) !== String(nodeFormId)) errors.push(`Form ID mismatch for node ${nodeId}.`);
    for (const fieldCode of collectFieldReferences(node.nodeFormConf?.actFormInfo ?? {})) {
      const baseCode = fieldCode.split('|')[0];
      if (!formFieldCodes.has(fieldCode) && !formFieldCodes.has(baseCode)) errors.push(`Unknown form field '${fieldCode}' for node '${nodeId}'.`);
    }
    const tabIds = new Set(asArray(data.tabConfig).map((tab) => String(tab?.id ?? '')).filter(Boolean));
    for (const group of asArray(node.nodeFormConf?.actTabGroupInfo)) {
      for (const tabId of asArray(group?.tabIds)) {
        if (tabId && !tabIds.has(String(tabId))) errors.push(`Unknown Tab ID '${tabId}' for node '${nodeId}'.`);
      }
    }
  }

  if (firstNodes.length > 1) errors.push(`More than one node has isFirst=1: ${firstNodes.join(', ')}`);
  if (firstNodes.length === 1 && data.firstNodeId && String(data.firstNodeId) !== firstNodes[0]) errors.push(`firstNodeId does not match isFirst node: ${data.firstNodeId} vs ${firstNodes[0]}`);

  if (index.references.missingXmlNodeIds.length) errors.push(`Missing XML nodes: ${index.references.missingXmlNodeIds.join(', ')}`);
  if (index.references.missingTabIds.length) errors.push(`Missing Tab references: ${index.references.missingTabIds.join(', ')}`);
  if (index.references.missingDiagramNodeIds.length) errors.push(`Missing BPMN-DI shapes: ${index.references.missingDiagramNodeIds.join(', ')}`);
  if (index.references.missingDiagramFlowIds.length) errors.push(`Missing BPMN-DI edges: ${index.references.missingDiagramFlowIds.join(', ')}`);
  return errors;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const filePath = process.argv[2];
  if (!filePath || filePath.startsWith('-')) usage();
  else {
    try {
      const errors = validate(filePath);
      if (errors.length) {
        console.error('Process JSON validation failed:');
        for (const error of errors) console.error(`- ${error}`);
        process.exitCode = 1;
      } else {
        console.log(`Process JSON validation passed: ${path.resolve(filePath)}`);
      }
    } catch (error) {
      console.error(`Process JSON validation failed:\n- JSON cannot be parsed: ${error.message}`);
      process.exitCode = 1;
    }
  }
}

export { validate };

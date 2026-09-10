# PROC Indexer and Topology Patcher

This directory contains tools for reading and minimally modifying large `PROC_*.json` files without sending the complete file to an AI model or reserializing the entire JSON document.

## Requirements

- Node.js 22 or later
- Run commands from the repository root, or pass absolute paths.

## 1. Generate a semantic index

```powershell
node .\.github\skills\process-json-editor\tools\proc-indexer\src\cli.mjs <path-to-PROC.json> --out .\tmp\process-index.json
```

The source file is never rewritten. The index includes:

- file byte count, encoding, line ending style, SHA-256, and MD5;
- process metadata and embedded XML statistics;
- node cards with stable IDs, names, types, incoming/outgoing flows;
- gateway line IDs, form groups, and referenced Tab IDs;
- form-field and Tab summaries;
- unresolved XML-node, Tab-reference, BPMN-DI shape, and BPMN-DI edge diagnostics.

Query a specific node with its stable ID:

```powershell
node .\.github\skills\process-json-editor\tools\proc-indexer\src\cli.mjs <path-to-PROC.json> --node <actNodeId>
```

Name lookup is supported, but names may be duplicated. Resolve and use the ID before creating a patch.

## 2. Patch plan format

Patch plans are JSON files with `schemaVersion: 1`, an optional source `fileSha256`, and an `operations` array.

### Replace an existing process property

```json
{
  "schemaVersion": 1,
  "fileSha256": "<SHA-256 from the index>",
  "operations": [
    {
      "op": "replace",
      "target": {
        "entity": "process",
        "path": "processName"
      },
      "expectedOldValue": "Incident Management",
      "newValue": "Incident Management - Internal"
    }
  ]
}
```

### Rename an existing node

Use the stable `actNodeId`. The patcher changes both `nodeConf[].actNodeName` and the matching `name` attribute in `processInfo.processXml`.

```json
{
  "schemaVersion": 1,
  "fileSha256": "<SHA-256 from the index>",
  "operations": [
    {
      "op": "replace",
      "target": {
        "entity": "node",
        "id": "UserTask_0eepxld",
        "path": "name"
      },
      "expectedOldValue": "In Progress",
      "newValue": "In Progress (Patched)"
    }
  ]
}
```

### Replace an existing node scalar property

For an existing node property, use `path` relative to the node object, for example `actNodeType` or another scalar property already present in that node.

```json
{
  "op": "replace",
  "target": {
    "entity": "node",
    "id": "<actNodeId>",
    "path": "actNodeType"
  },
  "expectedOldValue": "USER_TASK",
  "newValue": "USER_TASK"
}
```

Changing IDs, topology, gateway conditions, forms, field permissions, or Tab references is outside this minimum scope and must not be represented as a simple scalar change.

### Append an object to an existing array

The initial add capability appends one object to an existing array, such as `tabConfig`, `nodeConf`, or another explicitly selected array.

```json
{
  "schemaVersion": 1,
  "operations": [
    {
      "op": "append",
      "target": {
        "path": "tabConfig"
      },
      "value": {
        "id": "<new-tab-id>",
        "tabName": "New Tab",
        "tabAlias": "new-tab"
      }
    }
  ]
}
```

Appending a node or Tab does not automatically create all required BPMN, form, permission, or reference relationships. Such complex process changes remain out of scope for this minimum implementation.

### Insert a node on a selected flow

Use a flow ID, use `fromId` and `toId` when exactly one flow connects the two nodes, or use `afterNodeId`/`beforeNodeId` when that node has exactly one outgoing/incoming flow. The node configuration is cloned from `templateNodeId` (normally the upstream node), its form configuration is retained, and its handler assignment is cleared unless `handlerConf` is explicitly supplied. If there are multiple candidate flows, the patcher stops and returns the candidates.

```json
{
  "op": "insertNode",
  "afterNodeId": "<upstream-node-id>",
  "templateNodeId": "<nearest-same-type-node-id>",
  "node": {
    "id": "UserTask_review",
    "name": "review",
    "type": "USER_TASK"
  },
  "beforeFlowId": "SequenceFlow_review_in",
  "afterFlowId": "SequenceFlow_review_out"
}
```

The old flow is removed. The patcher creates `source -> new node` and `new node -> old target`, updates XML incoming/outgoing references, and updates the upstream `applyConf`.

### Remove a node and reconnect topology

```json
{
  "op": "removeNode",
  "target": { "id": "<node-id>" }
}
```

For one incoming and one outgoing flow, the patcher creates a replacement flow automatically. Multiple incoming flows are connected to the selected downstream target. A node with multiple outgoing flows requires `keepOutgoingFlowId`; discarded branches are pruned until a shared merge point. If the removed node is on a multi-output gateway branch, `confirmGatewayCollapse: true` is required after the topology has been shown to and confirmed by the user.

`formDef` and `tabConfig` are metadata and are not removed by `removeNode`. Only the node-level `nodeConf` and its XML topology are changed.

## 3. Apply a plan safely

Always test with a copy first:

```powershell
Copy-Item <path-to-PROC.json> .\tmp\process-fixture.json
node .\.github\skills\process-json-editor\tools\proc-indexer\src\patch.mjs `
  .\tmp\process-fixture.json `
  .\tmp\patch-plan.json `
  --out .\tmp\process-result.json
```

The patcher:

1. checks the optional source SHA-256;
2. resolves targets by stable IDs;
3. checks `expectedOldValue` before each replacement;
4. edits only the affected JSON token using `jsonc-parser`;
5. synchronizes node names into embedded XML;
6. appends new array items without reserializing unrelated content;
7. inserts or removes topology only when the selected flow/branch is unambiguous;
8. writes a temporary output and re-indexes it before rename;
9. reports the resulting SHA-256 and MD5.

The original source remains unchanged when `--out` is used.

For a deliberate final replacement, use a separate validated output first. The current implementation also supports:

```powershell
node .\.github\skills\process-json-editor\tools\proc-indexer\src\patch.mjs `
  <path-to-PROC.json> `
  .\tmp\patch-plan.json `
  --in-place
```

In-place mode uses a temporary file and a short-lived backup during replacement. Do not use it until the separate-output result has been reviewed.

## 4. Validation and MD5

The patcher checks that the resulting index has no missing XML-node, Tab, BPMN-DI shape, or BPMN-DI edge references. Before importing the result, run the repository’s full process validator. Only after the final JSON passes validation should `README.md` and `CONSISTENCY.MD5` be regenerated with the existing scripts. Do not save the JSON again after MD5 generation.

## Current scope and stop point

Implemented minimum capability:

- read large `PROC_*.json` files through a compact local index;
- modify existing scalar values by stable target ID and expected old value;
- rename an existing node while synchronizing JSON and embedded XML;
- append an object to an existing JSON array;
- insert a configured node on a selected flow while replacing the old flow;
- remove a node while deleting its old flows and creating valid replacement flows;
- synchronize BPMN-DI shapes and edges so page rendering matches the XML topology;
- preserve the original file when writing to a separate output;
- validate temporary output before replacement and report hashes.

Not implemented:

- ambiguous gateway branch deletion without an explicit user confirmation;
- gateway-condition changes;
- automatic form-field or permission construction;
- automatic Tab/reference construction;
- automatic execution of the repository’s MD5 package scripts.

Iteration stops at this minimum capability. Complex process-topology editing can be added as a separate feature later.

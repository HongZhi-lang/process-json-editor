---
name: process-json-editor
description: "Use when modifying or reviewing BPMN process export JSON, especially PROC_*.json. Covers local indexing and patching, process names, nodes, handlers, form fields, gateway conditions, tabs, cross-reference validation, README.md, and CONSISTENCY.MD5 regeneration."
argument-hint: "Describe the process file, target object, current value, and desired value"
user-invocable: true
---

# Process JSON Editor

Use this skill for repeatable changes to a process export package. The main target is `PROC_*.json` in a `process_main_*` directory.

## Bundled tools

For large `PROC_*.json` files, use the bundled tools in `.github/skills/process-json-editor/tools/proc-indexer` instead of loading or reserializing the complete file in the model context:

Windows PowerShell:

```powershell
node .\.github\skills\process-json-editor\tools\proc-indexer\src\cli.mjs <path-to-PROC.json> --out .\tmp\process-index.json
node .\.github\skills\process-json-editor\tools\proc-indexer\src\cli.mjs <path-to-PROC.json> --node <actNodeId-or-name>
node .\.github\skills\process-json-editor\tools\proc-indexer\src\patch.mjs <path-to-PROC.json> <patch-plan.json> --out .\tmp\process-result.json
```

macOS/Linux:

```bash
mkdir -p ./tmp
node ./.github/skills/process-json-editor/tools/proc-indexer/src/cli.mjs <path-to-PROC.json> --out ./tmp/process-index.json
node ./.github/skills/process-json-editor/tools/proc-indexer/src/cli.mjs <path-to-PROC.json> --node <actNodeId-or-name>
node ./.github/skills/process-json-editor/tools/proc-indexer/src/patch.mjs <path-to-PROC.json> <patch-plan.json> --out ./tmp/process-result.json
```

The indexer reports stable node IDs, embedded XML names and flow relationships, BPMN-DI shape/edge completeness, form fields, Tab IDs, file hashes, and unresolved XML/Tab references. Resolve a name to a stable ID before creating a patch plan. The patcher supports:

- replacing existing process, node, or Tab scalar values with `expectedOldValue` protection;
- renaming a node while synchronizing `nodeConf[].actNodeName` and its embedded XML `name`;
- appending an item to an existing JSON array;
- inserting a node on an explicitly selected `sequenceFlow`, replacing the old flow with two new flows;
- removing a node, deleting its incident flows, and reconnecting its upstream nodes to the selected downstream node;
- synchronizing `bpmndi:BPMNShape` and `bpmndi:BPMNEdge` so page rendering matches the XML topology;
- temporary-output validation and SHA-256/MD5 reporting.

Use `--in-place` only after reviewing a separate `--out` result. The patcher supports selected linear topology insertion/removal, but does not construct complete BPMN topology, form permissions, gateway mappings, or Tab relationships automatically.

The `.mjs` tools run on Windows, macOS, and Linux through Node.js; PowerShell is not required on macOS/Linux. The package requires Node.js 22 or later. Run `npm install` in `.github/skills/process-json-editor/tools/proc-indexer` before first use if dependencies are not already installed.

`tmp` is a runtime workspace for indexes, patch plans, fixtures, and patched outputs. It does not belong to the skill package. Remove temporary files after review and validation; do not rely on a pre-existing `tmp` file when sharing the skill.

After reporting the final result, remove the exact temporary filenames created for the task with `src/clean.mjs`. Do not delete the whole `tmp` directory blindly, because it may contain user-owned files.

## Before editing

1. Identify the exact target file and the requested object.
2. Read the relevant JSON sections before changing anything.
3. If the request identifies a name rather than an ID, confirm the matching `actNodeId`, `fieldCode`, or Tab ID.
4. Keep unrelated JSON files unchanged unless the request requires them.

Do not change IDs just to make a value look consistent. ID changes can affect several XML and JSON references.

## Change workflow

1. Generate a local semantic index with `.github/skills/process-json-editor/tools/proc-indexer/src/cli.mjs` and identify the exact target ID or field code.
2. Read the relevant JSON sections before changing anything.
3. Create a schema-versioned patch plan with the source `fileSha256` and `expectedOldValue` whenever the change is supported by `patch.mjs`.
4. Apply the plan to a temporary copy or separate `--out` path with `.github/skills/process-json-editor/tools/proc-indexer/src/patch.mjs`.
5. Mark the temporary index, patch plan, and fixture for `--cleanup`; they are removed only after patching and validation succeed. On failure, keep them for troubleshooting.
6. For topology requests, resolve the exact flow ID and show the current upstream/downstream topology before writing. If a node has multiple candidate incoming/outgoing flows, stop and ask the user to select one; do not guess.
7. Apply the smallest requested change and update every mirrored or referenced value:
   - Node names: `processInfo.processXml` and `nodeConf[].actNodeName`.
   - Node IDs: XML node references, `nodeConf[].actNodeId`, incoming/outgoing references, and `firstNodeId` when applicable.
   - Form fields: `formDef.formInfo`, `formDef.fieldList`, and node-level field permissions.
   - Gateway conditions: XML `sequenceFlow.conditionExpression` and `nodeConf[].applyConf`.
   - Tabs: `tabConfig[]` and node-level `actTabGroupInfo[].tabIds`.
  - Inserted nodes: replace the selected old flow, create both new flows, update XML incoming/outgoing references, and update the upstream `applyConf`.
  - Removed nodes: delete the node-level `nodeConf`, XML node, and incident flows; create replacement flows according to the selected branch rule. Do not modify `formDef` or `tabConfig` metadata.
8. Run the repository validation script:

    Windows:

    ```powershell
    powershell -NoProfile -ExecutionPolicy Bypass -File .github/skills/process-json-editor/scripts/validate-process-json.ps1 `
     -Path test/process_main_test/PROC_c738b53a375d46d9b258c020d2a4720b.json
    ```

    The Windows wrapper delegates parsing and validation to the bundled Node.js validator, so duplicate JSON keys such as `attrId` and `attrID` are not rejected by PowerShell's JSON converter.

    macOS:

    ```bash
    chmod +x .github/skills/process-json-editor/scripts/validate-process-json.sh
    ./.github/skills/process-json-editor/scripts/validate-process-json.sh \
      -p test/process_main_test/PROC_c738b53a375d46d9b258c020d2a4720b.json
    ```

9. Only after all JSON changes are final, regenerate `README.md` and `CONSISTENCY.MD5` with the existing MD5 script.
10. Do not edit or re-save JSON files after MD5 generation. Encoding, BOM, and line endings are part of the checked content.

### Topology decision rules

- A new node uses the user-provided `name`, `type`, and configuration. If type is omitted, use `USER_TASK`; copy the form configuration from the previous node; select the nearest same-type node's `handlerConf` as the template and clear its assignment. An explicitly supplied `handlerConf` overrides this default.
- New node identity fields must be regenerated or corrected: `nodeFormConf.id` must be unique, `nodeFormConf.actNodeId` must equal the new node ID, handler identity fields must not point to the template, and `isFirst` must be `0` unless the user is explicitly changing the process start node.
- `SINGLE_APPROVE_TASK` and `MULTI_APPROVE_TASK` use the nearest same-type approval node as the configuration template and must be emitted as `cw:singleApprove` or `cw:multiApprove`; the XML root must declare the `cw` namespace.
- Adding a node always removes the selected old connection before creating the two replacement connections. Use an explicit `flowId`, or use `afterNodeId`/`beforeNodeId` only when the selected node has exactly one outgoing/incoming flow. A vague request such as “after In Progress” is insufficient when that node has multiple candidate flows; return the indexed candidates and wait for clarification.
- Adding a gateway does not invent branch conditions. The user must provide branch names and conditions; each gateway `applyConf` entry must be mirrored by an XML `conditionExpression`.
- BPMN-DI shapes must use type-appropriate geometry: gateways use square `50x50` bounds, start/end events use `36x36`, and tasks use `100x80`. Exclusive gateways must set `isMarkerVisible="true"`; calculate new edge waypoints only after inserting the new shape so connections terminate on the actual shape boundary.
- Removing a node with one incoming and one outgoing flow reconnects them automatically. Multiple incoming flows may connect to the selected downstream node.
- Removing a node with multiple outgoing flows requires `keepOutgoingFlowId`. Discarded branches are removed according to the topology; do not infer the retained branch.
- If a removal collapses a multi-output gateway branch, require explicit user confirmation after returning the gateway's incoming/outgoing topology. Do not modify the process while that confirmation is missing.
- `startEvent` and `endEvent` are the single fixed process boundary nodes discovered from `processXml`; they are not ordinary user-selected `nodeConf` templates.

## Validation requirements

The change is complete only when:

- The JSON parses successfully.
- `processInfo.processXml` parses as XML.
- Every `nodeConf[].actNodeId` exists in the XML.
- Node names in `nodeConf` match the XML node names when both are present.
- Every `applyConf[].actLineId` exists as an XML `sequenceFlow`.
- `nodeFormConf.mdlFormId` matches `formDef.id` when both are present.
- Field permission references point to fields in `formDef.fieldList`.
- Tab references point to entries in `tabConfig[].id`.
- Every process XML node has a matching `bpmndi:BPMNShape`.
- Every process XML `sequenceFlow` has a matching `bpmndi:BPMNEdge`.
- Every XML namespace prefix used by the process is declared on the definitions root.
- Every `nodeConf[].nodeFormConf.actNodeId` matches its node ID, and node-level `nodeFormConf.id` values are unique.
- At most one node has `isFirst: 1`, and it matches `firstNodeId` when `firstNodeId` is present.
- Non-gateway nodes do not carry gateway `applyConf`; gateway line names, conditions, field keys, and values match the XML `conditionExpression`.
- MD5 metadata is regenerated after the last JSON change.

## Reference documents

- [Process package structure](./references/基本框架说明.md)
- [PROC fields](./references/PROC/基本字段信息说明.md)
- [Form fields](./references/PROC/表单字段说明.md)
- [Nodes and process XML](./references/PROC/node节点与processXml说明.md)
- [Complete change chain](./references/PROC/修改流程的完整链路.md)
- [Tabs](./references/PROC/tab页说明.md)
- [MD5 usage](./references/MD5/MD5脚本使用说明.md)

## Important constraints

- Do not claim success without running validation.
- Ask for missing target values instead of guessing.
- Treat a validation error as a blocker to MD5 generation.
- Never modify only `README.md` or only `CONSISTENCY.MD5`.
---
name: process-json-editor
description: "Use when modifying or reviewing BPMN process export JSON, especially PROC_*.json. Covers process names, nodes, handlers, form fields, gateway conditions, tabs, cross-reference validation, README.md, and CONSISTENCY.MD5 regeneration."
argument-hint: "Describe the process file, target object, current value, and desired value"
user-invocable: true
---

# Process JSON Editor

Use this skill for repeatable changes to a process export package. The main target is `PROC_*.json` in a `process_main_*` directory.

## Before editing

1. Identify the exact target file and the requested object.
2. Read the relevant JSON sections before changing anything.
3. If the request identifies a name rather than an ID, confirm the matching `actNodeId`, `fieldCode`, or Tab ID.
4. Keep unrelated JSON files unchanged unless the request requires them.

Do not change IDs just to make a value look consistent. ID changes can affect several XML and JSON references.

## Change workflow

1. Parse the target JSON instead of performing broad text replacement.
2. Apply the smallest requested change.
3. Update every mirrored or referenced value:
   - Node names: `processInfo.processXml` and `nodeConf[].actNodeName`.
   - Node IDs: XML node references, `nodeConf[].actNodeId`, incoming/outgoing references, and `firstNodeId` when applicable.
   - Form fields: `formDef.formInfo`, `formDef.fieldList`, and node-level field permissions.
   - Gateway conditions: XML `sequenceFlow.conditionExpression` and `nodeConf[].applyConf`.
   - Tabs: `tabConfig[]` and node-level `actTabGroupInfo[].tabIds`.
4. Run the validation script:

    Windows:

    ```powershell
    powershell -NoProfile -ExecutionPolicy Bypass -File .github/skills/process-json-editor/scripts/validate-process-json.ps1 `
     -Path test/process_main_test/PROC_c738b53a375d46d9b258c020d2a4720b.json
    ```

    macOS:

    ```bash
    chmod +x .github/skills/process-json-editor/scripts/validate-process-json.sh
    ./.github/skills/process-json-editor/scripts/validate-process-json.sh \
      -p test/process_main_test/PROC_c738b53a375d46d9b258c020d2a4720b.json
    ```

5. Only after all JSON changes are final, regenerate `README.md` and `CONSISTENCY.MD5` with the existing MD5 script.
6. Do not edit or re-save JSON files after MD5 generation. Encoding, BOM, and line endings are part of the checked content.

## Large PROC JSON local edit MVP

For very large `PROC_*.json` files, use the local MVP script to avoid sending the full file to model context:

```bash
python3 .github/skills/process-json-editor/scripts/proc_json_local_edit.py index \
  --input /absolute/path/process_main_xxx/PROC_xxx.json \
  --output /tmp/proc_index.json

python3 .github/skills/process-json-editor/scripts/proc_json_local_edit.py context \
  --input /absolute/path/process_main_xxx/PROC_xxx.json \
  --target /nodeConf/0 \
  --output /tmp/proc_context.json

python3 .github/skills/process-json-editor/scripts/proc_json_local_edit.py apply-patch \
  --input /absolute/path/process_main_xxx/PROC_xxx.json \
  --patch /tmp/proc_patch.json \
  --output /tmp/PROC_xxx.updated.json
```

MVP behavior:

- Scope is **PROC-only** (`PROC_*.json`).
- Recursively indexes JSON Pointer nodes (object / array element subtree level).
- Generates per-node metadata: path, short summary, and content hash.
- Extracts common references (`id`, `ref`, `key`, `name`, `target`, `source`, `component`, `action`) plus PROC-related keys (`actNodeId`, `actLineId`, `sourceRef`, `targetRef`, `firstNodeId`, `mdlFormId`, `fieldCode`, `tabIds`, `defaultSequence`).
- Builds minimal one-hop edit context: target node + one-hop dependencies + one-hop reverse reference summaries.
- Applies local JSON patch operations (`add` / `replace` / `remove`) and validates before output.

Known limitations:

- Only RFC6902 subset (`add`, `replace`, `remove`) is supported.
- This MVP does not auto-generate patches from natural language requests.
- Reference extraction is heuristic and optimized for current PROC structure.

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
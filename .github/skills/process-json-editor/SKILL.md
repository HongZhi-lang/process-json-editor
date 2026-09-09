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

## Natural-language editing MVP (PROC only)

This skill now includes a PROC-only helper script:

```bash
python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py --help
```

Recommended flow for large PROC files:

1. **Summarize without loading the whole file into the model**

   ```bash
   python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
     summarize --target standardProcess/Problem\ Management/process_main_Problem\ Management
   ```

2. **Find candidate JSON pointers from the user's natural-language request**

   ```bash
   python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
     find --target standardProcess/Problem\ Management/process_main_Problem\ Management \
     --query '把 Approval 节点改成 Review'
   ```

3. **Inspect only the local slice that needs editing**

   ```bash
   python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
     slice --target standardProcess/Problem\ Management/process_main_Problem\ Management \
     --pointer /nodeConf/1
   ```

4. **For supported simple requests, edit directly from natural language**

   ```bash
   python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
     edit --target standardProcess/Problem\ Management/process_main_Problem\ Management \
     --request '将节点 "Approval" 的名称改为 "Review"'
   ```

5. **For more complex local edits, let the model produce structured operations and apply them**

   ```json
   [
     {
       "op": "merge",
       "path": "/nodeConf/1/handlerConf",
       "value": {
         "assignType": "CUSTOM_ASSIGN"
       }
     }
   ]
   ```

   ```bash
   python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
     apply --target standardProcess/Problem\ Management/process_main_Problem\ Management \
     --ops-file /tmp/proc-ops.json
   ```

The helper script only edits the target slice and then runs built-in consistency checks before writing the file. It blocks direct edits to known reference keys such as `actNodeId`, `fieldCode`, `tabConfig[].id`, `processXml`, and `firstNodeId`; use dedicated sync-aware operations or stop and ask for clarification instead of blind edits.

Supported direct natural-language intents in this MVP:

- Rename `processInfo.processName`
- Rename a node by `actNodeName` or `actNodeId`, with `nodeConf` + `processXml` sync
- Update a field's display name or default value, with `fieldList` + `formInfo` sync
- Rename a tab's `tabName` / `tabAlias`

Known limitations:

- Only `PROC_*.json` is supported.
- BPMN topology changes such as adding/removing nodes or rewiring flows are not automated yet.
- If `find` or a selector matches multiple candidates, stop and ask the user to confirm the exact target.
- For unsupported edits, use `find` + `slice` + `apply` so the model only sees the minimum local context.

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
- [Natural-language MVP](./references/PROC/自然语言编辑MVP说明.md)
- [MD5 usage](./references/MD5/MD5脚本使用说明.md)

## Important constraints

- Do not claim success without running validation.
- Ask for missing target values instead of guessing.
- Treat a validation error as a blocker to MD5 generation.
- Never modify only `README.md` or only `CONSISTENCY.MD5`.
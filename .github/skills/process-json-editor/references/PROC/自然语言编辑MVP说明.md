# PROC 自然语言编辑 MVP

当前仓库新增了一个仅面向 `PROC_*.json` 的局部编辑入口：

```bash
python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py --help
```

## 设计目标

- 只处理 `PROC_*.json`
- 不把超大 JSON 全量塞进模型上下文
- 先定位候选路径，再查看局部切片，再做路径级 patch 或同步型修改
- 修改后必须做基础引用校验，避免明显断链

## 推荐工作流

### 1. 文件发现与摘要

`--target` 既可以传 `PROC_*.json` 文件，也可以直接传只包含一个 `PROC_*.json` 的 `process_main_*` 目录。

```bash
python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
  summarize --target standardProcess/Problem\ Management/process_main_Problem\ Management
```

输出只包含流程名、节点数、字段数、Tab 数，以及前几个节点/字段/Tab 的摘要。

### 2. 用自然语言定位候选路径

```bash
python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
  find --target standardProcess/Problem\ Management/process_main_Problem\ Management \
  --query '把 Approval 节点改成 Review'
```

输出候选 JSON Pointer，如 `/nodeConf/1`、`/formDef/fieldList/4`、`/tabConfig/2`，并附带简短摘要与一跳相关路径。

### 3. 只读取局部切片

```bash
python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
  slice --target standardProcess/Problem\ Management/process_main_Problem\ Management \
  --pointer /nodeConf/1
```

`slice` 会返回：

- 目标片段
- 节点对应的 XML 节点摘要
- 一跳入/出线摘要
- 字段在 `formInfo` / `nodeFormConf` 中的相关引用
- Tab 被哪些节点引用

这样可以避免把整份 `PROC_*.json` 和整段 `processXml` 一次性放进上下文。

### 4. 直接执行支持的自然语言修改

```bash
python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py \
  edit --target standardProcess/Problem\ Management/process_main_Problem\ Management \
  --request '将节点 "Approval" 的名称改为 "Review"'
```

当前 MVP 直接支持：

- 修改 `processInfo.processName`
- 修改节点名称（同步 `nodeConf[].actNodeName` 与 `processInfo.processXml` 中同 ID 节点的 `name`）
- 修改字段显示名称（同步 `formDef.fieldList[].fieldName` 与 `formDef.formInfo` 中对应字段的 `title`）
- 修改字段默认值（同步 `formDef.fieldList[].defaultValue`、`formDef.formInfo[].default`、`x-props.defaultValue`）
- 修改 Tab 名称 / 别名

### 5. 用结构化 patch 执行复杂局部修改

对超出直接自然语言能力、但仍然属于“局部结构修改”的场景，先让模型读取 `find + slice` 的结果，再输出结构化操作：

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

支持的结构化操作：

- `replace`
- `merge`
- `append`
- `remove`
- `rename_node`
- `update_field`
- `update_tab`

## 基础引用保护

脚本会阻止对以下关键路径做“盲改”：

- `processInfo.processXml`
- `firstNodeId`
- `nodeConf[].actNodeId`
- `nodeConf[].applyConf[].actLineId`
- `formDef.id`
- `formDef.fieldList[].fieldCode`
- `tabConfig[].id`

如果必须改这些键，应该新增同步型专用操作，或者先停止并要求更明确的需求。

## 失败行为

- 找不到唯一目标：直接报错，不落盘
- 操作后校验失败：直接报错，不落盘
- 自然语言请求超出 MVP：提示改用 `find + slice + apply`

## 已知限制

- 只支持 `PROC_*.json`
- 还不支持自动新增/删除 BPMN 节点、自动改线、自动改网关条件 XML
- 一跳引用保护主要覆盖节点名、字段名/默认值、Tab 名称，以及关键引用键的阻断
- 更复杂的跨节点 / 跨 XML 结构修改仍需人工确认后再扩展

# Process JSON Editor

本项目用于通过 `process-json-editor` skill，以自然语言修改 BPMN 流程导出包中的大型 `PROC_*.json` 文件。

## 准备工作

### 环境要求

- Node.js 22 或更高版本。
- Windows：PowerShell 5.1 或更高版本。
- macOS：Python 3，用于运行 JSON 校验脚本。
- VS Code 和 GitHub Copilot，能够加载 `.github/skills/process-json-editor/SKILL.md`。

首次使用工具前，在仓库根目录执行：

Windows PowerShell：

```powershell
Push-Location .\.github\skills\process-json-editor\tools\proc-indexer
npm install
Pop-Location
```

macOS：

```bash
cd .github/skills/process-json-editor/tools/proc-indexer
npm install
cd ../../../..
chmod +x .github/skills/process-json-editor/scripts/*.sh
```

### 目录和目标文件

修改前确认目标是具体的 `PROC_*.json`，并且位于流程子目录中：

```text
StandardProcess/
	<流程名称>/
		processName.json
		process_main_<流程名称>/
			PROC_*.json
			ADV_*.json
			SLA_*.json
			README.md
			CONSISTENCY.MD5
```

MD5 脚本的目标目录必须是内层的 `process_main_*` 或 `process_sub_*` 目录，例如：

```text
StandardProcess/<流程名称>/process_main_<流程名称>
```

不要把外层的 `StandardProcess/<流程名称>` 作为 MD5 脚本目录。

## 推荐使用流程

1. 明确流程目录、目标 `PROC_*.json`、节点或字段名称和期望修改结果。
2. 使用 `process-json-editor` skill 生成本地语义索引，确认稳定 ID 和当前上下游关系。
3. 对已有属性或拓扑创建带 `fileSha256`、`expectedOldValue` 的 Patch Plan。
4. 始终先输出到临时文件，不要直接覆盖原始流程文件。
5. 检查 JSON、XML、节点、连线、表单、Tab 及 BPMN-DI 图形校验结果。
6. 确认所有 JSON 修改完成后，再生成 `README.md` 和 `CONSISTENCY.MD5`。
7. 生成 MD5 后不要再次编辑、格式化、转码或重新保存 JSON。
8. 按流程包目录结构打包，并确认 tar 包中的文件名与两个元数据文件一致。

`tmp` 目录只用于运行期间保存索引、补丁计划、临时副本和校验结果。完成复核后应删除其中的临时文件；分享 skill 时不需要保留 `tmp` 内容，工具会在需要时自行创建目录。

清理临时文件时使用工具提供的显式清理命令，只传入本次任务创建的文件名，不要直接清空整个 `tmp`：

```powershell
node .\.github\skills\process-json-editor\tools\proc-indexer\src\clean.mjs .\tmp process-index.json patch-plan.json process-fixture.json process-result.json
```

macOS/Linux 使用相同的 Node.js 命令和 `/` 路径，无需安装 PowerShell。

执行补丁时也可以直接使用 `--cleanup`：补丁写入、重建索引和校验全部成功后，工具自动删除列出的临时索引、补丁计划和临时副本；如果任一步骤失败，则保留这些文件供排查。最终 `--out` 结果和原始源文件不会被清理。

大型 JSON 不会完整加载到模型上下文中。工具会在本地解析完整文件，只向模型提供节点、字段、Tab、连线、图形映射和哈希等语义索引；实际修改通过局部结构化补丁完成，避免把百万字符 JSON 发送给模型，也避免重新序列化无关内容。

## 自然语言提示词示例

### 修改节点属性

```text
请使用 process-json-editor Skill，修改指定流程文件。

目标文件：
<流程名称>/process_main_<流程名称>/PROC_xxx.json

请找到名称为“原节点名称”的节点，将节点名称修改为“新节点名称”。
请先根据节点名称找到目标节点，再执行修改。
不要修改其他节点、表单、Tab 或流程连线。
请输出临时结果并完成校验，最后返回修改字段和结果文件哈希。
```

### 在节点后新增节点

```text
请使用 process-json-editor Skill，在指定流程的“前置节点名称”后添加“新节点名称”用户任务节点。

要求：
- 如果前置节点后面只有一条连接，就把新节点插入这条连接；
- 如果前置节点后面有多个去向，请先列出这些去向并等待我选择；
- 删除原有的前置节点到下游节点的连接；
- 新增“前置节点名称”->“新节点名称”和“新节点名称”->原下游节点两条连接；
- 新节点类型为 USER_TASK；
- 表单配置复制前置节点；
- 处理人配置为空；
- 新节点字段全部设置为只读；
- 同步 nodeConf、processXml、BPMNShape 和 BPMNEdge；
- 先写入临时输出，不要修改原始 PROC 文件。
```

### 删除普通节点并自动重连

```text
请使用 process-json-editor Skill，删除指定流程中的“待删除节点名称”节点。

请先根据节点名称确认目标节点，并用自然语言展示它前后连接的节点。
如果该节点只有一条入边和一条出边，则删除节点及旧连线，并将上游节点连接到下游节点。
同步修改 nodeConf、processXml、BPMNShape 和 BPMNEdge。
如果存在多个同名节点、多条候选连线或网关分支，请暂停并返回候选拓扑，不要猜测。
```

### 网关分支修改

```text
请使用 process-json-editor Skill，删除“网关节点名称”节点的“分支名称”分支后的“待删除节点名称”节点。

请先返回：
- 网关节点当前有哪些分支；
- 指定分支当前连接到哪些节点；
- 待删除节点前面和后面连接的节点；
- 删除后可能受影响的网关分支和汇聚节点。

如果删除会改变网关分支结构，请先返回完整拓扑并等待我确认保留哪个分支，再执行修改。
```

## 拓扑修改规则

- 必须优先使用 `actNodeId` 和 `sequenceFlow` ID，不要只依赖节点名称。
- 同名节点可能有多个，必须先通过上下文和拓扑确认具体节点。
- 新增节点会删除被选中的旧连线，再创建上下游两条新连线。
- 新增节点未指定类型时默认为 `USER_TASK`；表单配置复制上一个节点，处理人配置清空。
- 新增节点时，如果目标节点有多条入边或出边，必须明确指定具体连线；不清晰时返回候选拓扑并暂停。
- 删除节点时，单入边单出边自动重连；多入边单出边可将多个上游连接到下游。
- 删除节点有多条出边时，必须指定 `keepOutgoingFlowId`。
- 删除网关分支可能改变业务语义，必须先展示完整拓扑并等待确认。
- `startEvent` 和 `endEvent` 是固定流程边界，不作为普通节点模板删除或复制。
- 删除节点只修改节点配置和流程拓扑，不删除 `formDef`、`tabConfig` 等全局元数据。
- 页面能否显示取决于 BPMN 语义拓扑和 BPMN-DI 图形拓扑，两者都必须同步。

## Windows 校验和 MD5

Windows 校验命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
	-File .\.github\skills\process-json-editor\scripts\validate-process-json.ps1 `
	-Path '.\StandardProcess\<流程名称>\process_main_<流程名称>\PROC_xxx.json'
```

Windows 校验入口会调用 skill 内的 Node.js 校验器，不使用 PowerShell `ConvertFrom-Json`，因此可以处理大型 PROC 文件中 `attrId`/`attrID` 这类重复键。

Windows MD5 命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
	-File .\.github\skills\process-json-editor\scripts\md5.ps1 `
	-Dir '.\StandardProcess\<流程名称>\process_main_<流程名称>' `
	-EnvId '<环境ID>' `
	-Version '<版本号>'
```

脚本会覆盖目标目录中的 `README.md` 和 `CONSISTENCY.MD5`。`.jar` 文件不会写入这两个文件，也不会参与 MD5 清单。

## macOS 校验和 MD5

macOS 校验命令：

```bash
./.github/skills/process-json-editor/scripts/validate-process-json.sh \
	-p './StandardProcess/<流程名称>/process_main_<流程名称>/PROC_xxx.json'
```

macOS MD5 命令：

```bash
./.github/skills/process-json-editor/scripts/md5.sh \
	-d './StandardProcess/<流程名称>/process_main_<流程名称>' \
	-e '<环境ID>' \
	-v '<版本号>'
```

	## 常见使用问题

	### Windows

	ADV_文件的命名规则是：`^ADV_(?<processDefKey>\w+)_(?<version>\d+)_(?<uuid>[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\.json$`

	在Windows环境中，**`*`** 不允许出现在文件名中，默认会替换为 **`_`** 。生成 md5 脚本中已经做过特殊处理，打为tar包后，还需要在包内手动改为`*`号

	### MacOS

	MacOS 在处理压缩包时，**系统会添加一些附加信息文件**，导致最终生成的tar包不符合规则。

	目前确认使用`keka`，勾选 **`排除Mac资源文件 / Exclude Mac resource forks`** ，生成的tar包覆合规则

macOS 打包时，系统可能添加资源分叉等附加文件。使用 Keka 时勾选 `排除 Mac 资源文件 / Exclude Mac resource forks`，避免 tar 包中出现额外文件。

Windows 文件名不允许使用 `*`。本地 `ADV_*.json` 通常使用下划线保存，Windows MD5 脚本会在 `README.md` 和 `CONSISTENCY.MD5` 中进行协议名称转换；打 tar 包后仍需确认包内名称符合导入协议。

## 注意事项

- 不要直接编辑或重新保存百万字符级别的 PROC JSON。
- 不要使用固定文本替换修改 JSON。
- 不要在没有稳定 ID、旧值或明确连线的情况下猜测目标。
- `README.md` 和 `CONSISTENCY.MD5` 必须由同一次脚本执行生成，不能只更新其中一个。
- `.jar` 文件不会加入 README 和 MD5 清单；其他不属于流程包的直接文件不要放在目标目录中。
- MD5 生成前必须完成所有 JSON 修改和校验。
- MD5 生成后不能修改 JSON 的 BOM、编码、换行或内容。
- 网关分支、表单权限、字段只读配置和 Tab 关系属于高风险修改，提示词中应明确目标和期望结果。
- 原始标准流程文件建议保留不动，先使用临时副本验证，再决定是否使用 `--in-place`。
- 用户不需要了解 `actNodeId`、`sequenceFlow`、`nodeConf` 等内部字段；通常只需要提供流程文件、节点名称、分支名称和想要的自然语言结果。skill 会在本地索引中解析名称并确认内部 ID。
- 如果同名节点不止一个，或一句话无法唯一确定要修改的连线，skill 会先列出候选节点和自然语言拓扑，等待用户补充，不会自行猜测。

## 参考资料

- [Process JSON Editor Skill](.github/skills/process-json-editor/SKILL.md)
- [流程包结构说明](.github/skills/process-json-editor/references/基本框架说明.md)
- [MD5 脚本使用说明](.github/skills/process-json-editor/references/MD5/MD5脚本使用说明.md)
- [Windows JSON 校验入口](.github/skills/process-json-editor/scripts/validate-process-json.ps1)
- [Windows MD5 生成脚本](.github/skills/process-json-editor/scripts/md5.ps1)
- [macOS JSON 校验脚本](.github/skills/process-json-editor/scripts/validate-process-json.sh)
- [macOS MD5 生成脚本](.github/skills/process-json-editor/scripts/md5.sh)

## 导入后仍需手动设置的内容

- 工单编号前缀 `Prefix`
- 所有涉及人员或组织的内容
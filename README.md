## 准备工作

## 导入后仍需手动设置的内容

- 工单编号前缀 Prefix 

- 所有涉及到人员或组织的内容


## 常见使用问题

### Windows

ADV_文件的命名规则是：`^ADV_(?<processDefKey>\w+)_(?<version>\d+)_(?<uuid>[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\.json$`

在Windows环境中，**`*`** 不允许出现在文件名中，默认会替换为 **`_`** 。生成 md5 脚本中已经做过特殊处理，打为tar包后，还需要在包内手动改为`*`号

### MacOS

MacOS 在处理压缩包时，**系统会添加一些附加信息文件**，导致最终生成的tar包不符合规则。

目前确认使用`keka`，勾选 **`排除Mac资源文件 / Exclude Mac resource forks`** ，生成的tar包覆合规则

## 大型 PROC JSON 局部修改 MVP

已提供 `PROC_*.json` 的本地局部编辑脚本（MVP）：

`/home/runner/work/process-json-editor/process-json-editor/.github/skills/process-json-editor/scripts/proc_json_local_edit.py`

能力范围：

- 仅支持 `PROC_*.json`
- 递归建立 JSON Pointer 节点索引（路径、摘要、hash）
- 提取常见引用并构建一跳依赖/反向引用上下文
- 支持 JSON Patch（`add` / `replace` / `remove`）本地合并
- 合并后执行基础一致性校验（JSON/XML、常见引用、唯一性）
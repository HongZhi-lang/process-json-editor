## 准备工作

## 导入后仍需手动设置的内容

- 工单编号前缀 Prefix 

- 所有涉及到人员或组织的内容


## 常见使用问题

## PROC 自然语言编辑 MVP

仓库现在提供了一个仅面向 `PROC_*.json` 的局部编辑脚本，可配合 skill 在不展开整份超大 JSON 的情况下完成自然语言修改：

```bash
python3 .github/skills/process-json-editor/scripts/proc-json-nl-editor.py --help
```

推荐流程：

1. `summarize`：先看流程摘要
2. `find`：把自然语言请求映射到候选 JSON Pointer
3. `slice`：只读取目标片段和一跳关联引用
4. `edit`：直接处理 MVP 支持的自然语言请求
5. `apply`：对复杂局部结构使用结构化 patch
6. `validate-process-json.sh`：校验
7. `md5.sh` / `md5.ps1`：更新 `README.md` 与 `CONSISTENCY.MD5`

详细说明见：

- `.github/skills/process-json-editor/SKILL.md`
- `.github/skills/process-json-editor/references/PROC/自然语言编辑MVP说明.md`

### Windows

ADV_文件的命名规则是：`^ADV_(?<processDefKey>\w+)_(?<version>\d+)_(?<uuid>[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\.json$`

在Windows环境中，**`*`** 不允许出现在文件名中，默认会替换为 **`_`** 。生成 md5 脚本中已经做过特殊处理，打为tar包后，还需要在包内手动改为`*`号

### MacOS

MacOS 在处理压缩包时，**系统会添加一些附加信息文件**，导致最终生成的tar包不符合规则。

目前确认使用`keka`，勾选 **`排除Mac资源文件 / Exclude Mac resource forks`** ，生成的tar包覆合规则
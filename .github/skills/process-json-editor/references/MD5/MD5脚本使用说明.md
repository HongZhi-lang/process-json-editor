# 流程导入 MD5 生成脚本使用说明

## 用途

`md5.ps1`（Windows）和 `md5.sh`（macOS）用于为一个 `process_main_*` 或 `process_sub_*` 流程目录生成导入所需的两个文件：

- `CONSISTENCY.MD5`：记录环境、版本和每个流程定义文件的 MD5。
- `README.md`：记录导出协议中的文件名清单。

脚本会覆盖目标目录中已有的 `CONSISTENCY.MD5` 和 `README.md`。不会修改任何 JSON 文件，也不会创建 tar 包。

## 前提条件

- Windows 使用 Windows PowerShell 5.1 或更高版本运行 `md5.ps1`。
- macOS 使用 Terminal 运行 `md5.sh`。首次使用前执行 `chmod +x md5.sh`。
- 目标目录中只放本流程需要校验的 JSON 文件，例如 `PROC_*.json`、`ADV_*.json`、`SLA_*.json`。
- 在运行脚本前确认 JSON 内容、编码和换行已经最终确定。生成 MD5 后不得再修改文件内容。

目录示例：

```text
流程名\
  processName.json
  process_main_流程名\
    PROC_xxx.json
    ADV_xxx_x_xxx.json
    SLA_xxx.json
```

脚本所在目录为 `.github/skills/process-json-editor/scripts`。执行命令前进入该目录；`Dir`（macOS 为 `-d`）参数应传入 `process_main_流程名`，而不是最外层的流程名目录。

## Windows 命令格式

```powershell
.\md5.ps1 -Dir <流程目录> -EnvId <环境ID> -Version <版本号>
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `Dir` | 是 | 一个 `process_main_*` 或 `process_sub_*` 目录的完整路径。 |
| `EnvId` | 是 | 目标环境 ID，写入 `CONSISTENCY.MD5` 的第一行。 |
| `Version` | 是 | 目标系统版本，写入 `CONSISTENCY.MD5` 的第二行。 |

## macOS 命令格式

```bash
./md5.sh -d <流程目录> -e <环境ID> -v <版本号>
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `-d` | 是 | 一个 `process_main_*` 或 `process_sub_*` 目录的完整路径。 |
| `-e` | 是 | 目标环境 ID，写入 `CONSISTENCY.MD5` 的第一行。 |
| `-v` | 是 | 目标系统版本，写入 `CONSISTENCY.MD5` 的第二行。 |

## macOS 校验命令格式

在 macOS 上，流程 JSON 校验也可直接用对应的 bash 脚本：

```bash
chmod +x .github/skills/process-json-editor/scripts/validate-process-json.sh
./.github/skills/process-json-editor/scripts/validate-process-json.sh \
  -p test/process_main_test/PROC_c738b53a375d46d9b258c020d2a4720b.json
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `-p` | 是 | 需要校验的单个 `PROC_*.json` 文件路径。 |

其校验逻辑与 Windows 版 PowerShell 校验脚本一致，均会检查 JSON 可解析性、XML 可解析性、节点 ID 与 XML 映射、Gateway 条件引用、表单字段引用和 Tab 引用等。 |

## 使用示例

在 Windows 的 `generateJSON\.github\skills\process-json-editor\scripts` 目录中执行：

```powershell
.\md5.ps1 `
  -Dir 'E:\work\generateJSON\test\process_main_test' `
  -EnvId '583ad12aefd445ac9df76079939666cf' `
  -Version '7.1.0'
```
```powershell
& 'E:\work\generateJSON\.github\skills\process-json-editor\scripts\md5.ps1' -Dir 'E:\work\generateJSON\test\process_main_test' -EnvId '583ad12aefd445ac9df76079939666cf' -Version '7.1.0'
```
执行成功后，目标目录会生成或更新：

```text
process_main_test\CONSISTENCY.MD5
process_main_test\README.md
```

在 macOS 的 `generateJSON/.github/skills/process-json-editor/scripts` 目录中执行：

```bash
chmod +x md5.sh
./md5.sh \
  -d '/Users/用户名/work/generateJSON/test/process_main_test' \
  -e '583ad12aefd445ac9df76079939666cf' \
  -v '7.1.0'
```

执行成功后，同样会在目标目录生成或更新 `CONSISTENCY.MD5` 和 `README.md`。

## 生成规则

### 文件顺序

脚本按以下顺序写入 `README.md` 和 `CONSISTENCY.MD5`：

1. `PROC_*.json`
2. `ADV_*.json`
3. 其他文件

同一类文件再按文件名排序。`CONSISTENCY.MD5` 与 `README.md` 自身不会参与 MD5 计算。

### ADV 文件名映射

Windows 文件名不能包含 `*`，所以 Windows 本地磁盘上的 ADV 文件使用下划线，例如：

```text
ADV_qurowots_4_4704b07c-a69a-11f1-a532-00163e67538e.json
```

Windows 版 `md5.ps1` 会自动把协议文件中的下划线转换为星号，但不会重命名 Windows 磁盘上的实体文件。现有导入导出协议要求在 `README.md`、`CONSISTENCY.MD5` 以及最终 tar 包的条目名中使用星号：

```text
ADV_qurowots*4*4704b07c-a69a-11f1-a532-00163e67538e.json
```

macOS 文件名允许包含 `*`，因此 macOS 磁盘上的 ADV 文件本身就应直接使用星号，例如：

```text
ADV_qurowots*4*4704b07c-a69a-11f1-a532-00163e67538e.json
```

macOS 版 `md5.sh` 不会进行下划线到星号的转换，直接使用实体文件名写入 `README.md` 和 `CONSISTENCY.MD5`。

### MD5 计算口径

脚本按现有服务端导入逻辑计算：先按 UTF-8 把文件读成字符串，再将该字符串编码为 UTF-8 后计算 MD5。

这点对带 UTF-8 BOM 的 `PROC_*.json` 很重要。不要在生成 MD5 后用编辑器重新保存 JSON，否则 BOM、编码或换行发生变化都会导致导入报错：

```text
The file is modified.
```

## 打包前检查

运行脚本后，检查 `README.md` 与 `CONSISTENCY.MD5` 中的文件名是否一致。例如：

```text
PROC_c738b53a375d46d9b258c020d2a4720b.json
ADV_qurowots*4*4704b07c-a69a-11f1-a532-00163e67538e.json
SLA_qurowots.json
```

打包时保持导出包的目录层级：

```text
流程名/
  processName.json
  process_main_流程名/
    PROC_*.json
    ADV_*.json
    SLA_*.json
    CONSISTENCY.MD5
    README.md
```

Windows 最终 tar 包内的 `ADV` 条目名必须从下划线改为星号；macOS 无需改名。两种平台的 tar 条目名都必须与 `README.md` 和 `CONSISTENCY.MD5` 中的名称完全一致。仅修改 `README.md` 或仅修改 `CONSISTENCY.MD5` 都会导致导入失败。

JSON 文件内容必须与生成 MD5 时完全相同。打包或修改 tar 内条目名时不能重新保存、转码、格式化或改变换行。

## 常见导入错误

| 错误信息 | 常见原因 | 处理方式 |
| --- | --- | --- |
| `The file does not exist.` | `CONSISTENCY.MD5` 声明的名称与 tar 内实际条目名不一致，常见于 ADV 文件仍是下划线。 | 让 tar 内 ADV 条目名、`README.md`、`CONSISTENCY.MD5` 全部使用相同的星号名称。 |
| `The file is modified.` | JSON 在生成 MD5 后被编辑、重新保存或转码；尤其是 `PROC` 的 BOM 被改变。 | 恢复生成 MD5 时的 JSON 内容，重新运行脚本，再重新打包。 |

## 推荐操作顺序

1. 准备 `PROC`、`ADV`、`SLA` 等 JSON 文件。
2. 确认所有 JSON 内容已最终定稿，尤其不要改变 `PROC` 的编码和 BOM。
3. Windows 运行 `md5.ps1`；macOS 运行 `md5.sh`，生成 `CONSISTENCY.MD5` 和 `README.md`。
4. 将最外层流程目录打成 tar，保持上述目录层级。
5. Windows 在 tar 包内将 ADV 条目名从下划线形式改为与协议文件一致的星号形式；macOS 保持原文件名即可。
6. 确认 tar 内实际 ADV 条目名、`README.md` 和 `CONSISTENCY.MD5` 三者完全一致后导入。

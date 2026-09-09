## processXml 结构
processXml 是标准的 BPMN 2.0 XML，存储在 processInfo.processXml 字段中（JSON 转义）。

### 命名空间
| 前缀 | URI | 说明 |
| --- | --- | --- |
| `bpmn` | http://www.omg.org/spec/BPMN/20100524/MODEL | BPMN 标准元素 |
| `bpmndi` | http://www.omg.org/spec/BPMN/20100524/DI | BPMN 图形信息 |
| `dc` | http://www.omg.org/spec/DD/20100524/DC | 坐标定义 |
| `di` | http://www.omg.org/spec/DD/20100524/DI | 图形信息 |
| `cw` | http://www.cloudwise.com/BPMN/20220520/MODEL | 自定义扩展（如 cw:singleApprove） |

### 节点类型
| 元素 | actNodeType | 说明 |
| --- | --- | --- |
| `bpmn:startEvent` | START_EVENT | 开始事件 |
| `bpmn:endEvent` | END_TASK | 结束事件 |
| `bpmn:userTask` | USER_TASK | 用户任务节点 |
| `bpmn:exclusiveGateway` | EXCLUSIVE_GATEWAY | 排他网关（条件分支） |
| `bpmn:parallelGateway` | PARALLEL_GATEWAY | 并行网关 |
| `bpmn:inclusiveGateway` | INCLUSIVE_GATEWAY | 包含网关 |
| `cw:singleApprove` | SINGLE_APPROVE_TASK | 自定义审批节点（单审批） |
| `cw:multiApprove` | MULTI_APPROVE_TASK | 自定义审批节点（多审批） |

### 连线与条件
```xml
<bpmn:sequenceFlow id="SequenceFlow_RadioTrue_Manage" 
                   name="Radio = True" 
                   sourceRef="ExclusiveGateway_0fqp5zz" 
                   targetRef="SingleApprove_0w5ml4y">
  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">
    ${radioTrue}
  </bpmn:conditionExpression>
</bpmn:sequenceFlow>
```

## nodeConf 结构
nodeConf 数组中每个元素对应 processXml 中的一个非连线节点。

### 顶层字段
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `actNodeId` | String | 关联键，对应 processXml 中节点的 id 属性 |
| `actNodeName` | String | 节点名称，对应 processXml 中节点的 name 属性 |
| `actNodeType` | String | 节点类型（见 节点类型 表格） |
| `processId` | String | 所属流程 ID |
| `version` | Number | 节点配置版本 |
| `isFirst` | Number | 是否首节点（1=是，0=否） |
| `handlerConf` | Object | 处理人配置（用户任务/审批节点有值） |
| `nodeFormConf` | Object | 节点级表单配置 |
| `applyConf` | Array | 网关条件配置（网关节点有值） |
| `defaultSequence` | String | 默认连线 ID（网关节点） |
| `subProcessConf` | Object | 子流程配置 |
| `acceptanceTaskConf` | Object | 验收任务配置 |
| `automationTaskConf` | Object | 自动化任务配置 |

### handlerConf（处理人配置）
| 字段 | 说明 |
| --- | --- |
| `handlerType` | 处理类型（SINGLE_PROCESSING 等） |
| `assignType` | 分配类型（CHOOSE_GROUP、CUSTOM_ASSIGN 等） |
| `assignConf` | 分配配置（包含选中的组、人、职责等） |
| `button` | 节点可用按钮列表 |
| `redeployType / redeployConf` | 转派配置 |
| `approveConf` | 审批配置（审批节点） |
| `assistedConf` | 协助配置 |

### applyConf（网关条件）
```json
{
  "actLineId": "SequenceFlow_RadioTrue_Manage",  // 对应 processXml 中的 sequenceFlow ID
  "actLineName": "Radio = True",
  "matchType": "ALL",                             // ALL=满足所有条件, ANY=满足任一条件
  "condition": [
    {
      "fieldKey": "Radio",                        // 表单字段 code
      "fieldType": "RADIO",                       // 字段组件类型
      "type": "EQ",                               // 比较运算符
      "valueList": ["JwaDYC"]                     // 比较值
    }
  ]
}
```
## 两者的联动关系
```text
processXml                              nodeConf
┌──────────────────────────┐           ┌──────────────────────────┐
│ <bpmn:userTask           │           │ {                        │
│   id="UserTask_0jbdio2"  │◄─────────►│   actNodeId:             │
│   name="New"             │  ID 匹配   │     "UserTask_0jbdio2", │
│ />                       │           │   actNodeName: "New",    │
│                          │           │   actNodeType:           │
│                          │           │     "USER_TASK",         │
│                          │           │   handlerConf: {...},    │
│                          │           │   nodeFormConf: {...}    │
│                          │           │ }                        │
├──────────────────────────┤           ├──────────────────────────┤
│ <bpmn:exclusiveGateway   │           │ {                        │
│   id="ExclusiveGateway_  │◄─────────►│   actNodeId:             │
│     0fqp5zz"             │  ID 匹配   │     "ExclusiveGateway_  │
│   name="Radio Gateway"   │           │      0fqp5zz",           │
│ />                       │           │   applyConf: [           │
│                          │           │     {                    │
│ <bpmn:sequenceFlow       │           │       actLineId:         │
│   id="SequenceFlow_      │◄─────────►│         "SequenceFlow_   │
│     RadioTrue_Manage"    │  ID 匹配   │           RadioTrue_    │
│   sourceRef="..."        │           │           Manage",       │
│   targetRef="..."        │           │       condition: [...]   │
│ />                       │           │     }                    │
│                          │           │   ]                      │
│                          │           │ }                        │
└──────────────────────────┘           └──────────────────────────┘
```

**核心规则：**

1. **节点对应：**`nodeConf[].actNodeId` 与 `processXml` 中节点元素的 `id` 属性一一对应

2. **连线条件对应：**网关节点的 `applyConf[].actLineId` 与 `processXml` 中 `sequenceFlow` 的 `id` 对应

3. **名称同步：**`actNodeName` 与 `processXml` 中节点的 `name` 属性保持一致

4. **修改同步：**修改 `processXml` 中节点 `ID` 时，必须同步修改 `nodeConf` 中对应的 actNodeId
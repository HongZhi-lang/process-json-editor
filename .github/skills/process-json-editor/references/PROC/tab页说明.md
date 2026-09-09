## tabConfig 全局定义

```json
{
  "id": "c9b8d98f...",              // Tab 唯一 ID
  "tabName": "Business status flow", // 显示名称
  "tabAlias": "Business status flow", // 别名
  "type": 0,                         // Tab 类型
  "dynamicParameter": "['workOrderId']", // 动态参数
  "useRange": 0,                     // 使用范围
  "h5Uri": null,                     // H5 链接（自定义 Tab）
  "uri": null,                       // URI
  "language": "en",                  // 语言
  "isDel": 0                         // 软删除标记
}
```

## 节点级 Tab 配置（actTabGroupInfo）

```json
{
  "tabGroupId": "30ec7308...",      // Tab 组 ID
  "tabDisplayType": "vertical",      // 显示方式（vertical / horizontal）
  "tabIds": [                        // 引用的 Tab ID 列表
    "d1fe9e2c...",
    "11a11a88...",
    "5a158258..."
  ]
}
```

## 两者的关系

```text
tabConfig[] (全局 Tab 池)              nodeFormConf.actTabGroupInfo (节点引用)
┌──────────────────────┐              ┌──────────────────────┐
│ id: "tab_1"          │              │ tabIds: [            │
│ tabName: "SLA"       │◄────────────►│   "tab_1",           │
│                      │   ID 引用     │   "tab_2"            │
│ id: "tab_2"          │              │ ]                    │
│ tabName: "Flow chart"│              │ tabDisplayType:      │
│                      │              │   "vertical"         │
└──────────────────────┘              └──────────────────────┘
```

**规则：**

- `tabConfig` 定义所有可用 `Tab`

- 每个节点通过 `actTabGroupInfo[].tabIds` 选择显示哪些 `Tab`

- 不同节点可以配置不同的 `Tab` 组合

- `tabGroupId` 在不同节点中可能相同（表示使用同一组配置）或不同
请使用 process-json-editor Skill，修改Incident Management流程文件：

目标文件：
Incident Management/process_main_Incident Management/PROC_cfc4be9658854fbb9fc460817eb06ee0.json

修改要求：
1. 在New节点后添加网关节点，分出两天路径，判断Major Incident的值，
   - 如果为true，则再添加一个approval节点并将出边连到In Progress
   - 如果为false，则走原来的流程，连接In Progress
2. 修改完成后，重新生成 README.md 和 CONSISTENCY.MD5。
3. 当前环境处于Windows
4.  最后告诉我：
   - 修改了哪些字段
   - 校验是否通过
   - 生成的 PROC 文件 MD5
   - README.md 和 CONSISTENCY.MD5 是否已更新
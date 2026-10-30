# 核电质量数据获取与局域网看板

项目按网络边界拆成两个服务。公网 Windows 电脑运行短信取码、aTrust/AE 自动化、Excel 下载和 SQLite 汇总；内网 Ubuntu 服务器接收 Windows 主动推送的 SQLite 快照，并运行查询 API 和 Vue 看板；用户清单及编号备注保存在 Ubuntu 的独立数据库。Ubuntu 不需要也不会主动访问公网。

```text
短信服务 / AE 平台（公网）
            ↓
Windows 采集端：取码、登录、下载 Excel、更新 SQLite
            └── HTTP PUT /api/sync/database（Bearer 同步令牌）──→
Ubuntu 内网服务器：校验快照、原子更新 SQLite、查询 API + Vue 看板
            ↓
局域网同事通过浏览器查看
```

Windows 每轮成功入库后通过 SQLite backup API 生成一致性快照并推送。推送失败会保留 Windows 本地数据库并记录警告；下一轮成功入库后重新推送最新完整快照。Ubuntu 校验同步令牌、SQLite integrity_check 和看板必需表后才替换正在服务的数据库。看板状态区显示最近推送时间及记录数，不显示验证码或凭据。

## 多平台接入

系统支持 AE 协调平台和中广核 IMSQS 平台，分别保存原始信息并在列表、详情、变化记录和导出中标明来源。Windows 广核配置、定时采集和 Ubuntu 更新方法见 [多平台接入说明](MULTI_SOURCE.md)。

## 部署

完整的 Windows 与 Ubuntu 部署步骤、网络端口、密钥配置和服务维护命令见 [DEPLOYMENT_SPLIT.md](DEPLOYMENT_SPLIT.md)。Ubuntu 文件模板位于 `deploy/`。Pusher 中已有的内网地址是 `10.42.60.230`；示例使用 `http://10.42.60.230:8787`，若质量看板 Ubuntu 服务器 IP 不同，改 Windows 的 `lan_sync_config.json`。

## Windows 公网采集端

保留现有 Windows 自动化配置和运行方式。完成 `setup.bat`、短信服务配置、`atrust_config.json` 与 `ecs_login_config.json` 后，创建 `lan_sync_config.json`：

```json
{
  "url": "http://10.42.60.230:8787",
  "token": "与 Ubuntu 配置相同的随机同步密钥"
}
```

之后运行 `start_scheduler.bat`（使用 `setup.bat` 创建的 `.venv`），默认启动立即执行，之后每 60 分钟自动跑一轮；周期可在 `scheduler_config.json` 里调整。每轮都会关闭旧 aTrust 客户端、重开并重新登录，完成下载和推送后再次关闭。需要开机常驻时，在 Windows 任务计划程序中配置登录时启动 `start_scheduler.bat`。同步也会在手动执行 `main.py` 或 `ecs_sync.py` 入库后触发。看板服务器暂时不可达时，自动化采集和本地入库仍会完成，日志会提示推送失败。

## Ubuntu 内网看板

Linux 端仅部署 `dashboard_api/` 和构建后的 `nuclear-quality-dashboard/dist/`，不部署 Windows 登录自动化、短信凭据或账号配置。FastAPI API 默认使用 `ECS_DB_PATH` 指向 Ubuntu 数据目录，前端由 Nginx 在 `8090` 端口托管。浏览器访问 `http://10.42.60.230:8090/`；Nginx 将 `/api/*` 转发到本机 API 的 `8787` 端口。

## 主要接口

- `PUT /api/sync/database`：公网采集端推送 SQLite 文件（二进制请求体），必须带 `Authorization: Bearer <LAN_SYNC_TOKEN>`。
- `GET /api/sync/status`：返回最近一次快照到达时间和文档数。
- `/api/health`、`/api/filters`、`/api/overview`、`/api/documents`、`/api/trace`、`/api/suppliers`、`/api/governance`、`/api/export`：看板接口。


## 清单与台账维护

- 总览的完成/处理中指标、流程状态和核安全报送级别可点击进入对应台账明细；项目与机组联动筛选。
- “质量计划清单”支持 Excel（`.xlsx` / `.xls`）和 CSV：上传 → 预览 → 确认字段映射 → 导入。可下载表头模板。文件最多 10 MB、10000 条、100 列，CSV 支持 UTF-8 和 GB18030。
- 计划名称必填，并提供文件编号、内部编号或完整项目＋机组中的一种。优先精确匹配文件编号，其次内部编号，再次名称＋项目＋机组；显式文件编号不匹配时不按同名强行关联。多个候选或多项清单对应同一实际记录显示“待核对”。
- 清单完成率 = 唯一匹配且流程为“完成”的计划项 ÷ 筛选范围内清单总项数。未接入、待核对均在分母中；清单外实际记录不计入分母，可单独查看/导出。清单以项目、机组、供方筛选，不受实际记录创建时间筛选影响。
- 导入为合并更新：同一项目、机组和标识的条目更新，其余保留。更改标识会视为新条目；导入前请核对编号，不会自动删除旧清单。
- 台账“内部编号”由用户点击“添加备注”或已有编号编辑。用户备注优先于源平台和导入清单，支持检索与导出。清空备注后若平台或清单有该编号，恢复显示来源值。
- “最新审批流程时间”仅显示源数据中同名字段（或“最新审批时间”）及唯一匹配清单中的值，标明来源；当前 Windows 采集字段未提供该时间，缺失时显示“未提供”。不会使用创建时间、抓取时间或普通字段变更时间代替审批时间。
- 流程追踪支持搜索、翻页和选择计划；右侧只显示被选中计划的字段变更，并独立分页。供方分析可进入该供方的清单执行对比。

导入和编号修改需要管理员配置 `DASHBOARD_ADMIN_TOKEN`，页面输入的维护口令只留在当前页面内存中，不存浏览器持久存储。不要复用 Windows 的 `LAN_SYNC_TOKEN`。清单及备注写入独立的 `PLAN_CATALOG_PATH`（默认在接收数据库旁边的 `quality_plan_catalog.db`），Windows 新快照不会覆盖它。更新步骤与备份方法见 [部署说明](DEPLOYMENT_SPLIT.md#前后端一起更新本次清单与备注功能)。

### 回归验证

在测试 Python 环境安装 `dashboard_api/requirements.txt` 和 `httpx` 后，运行 `python -m unittest discover -s tests -v`。覆盖清单匹配歧义、重复导入、字段映射、备注跨快照保留、筛选钻取及流程变更隔离。前端在 `nuclear-quality-dashboard` 目录运行 `npm run build`。

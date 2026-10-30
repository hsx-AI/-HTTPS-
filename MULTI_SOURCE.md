# AE 与中广核两个平台的数据接入

看板现在支持 **AE 协调平台** 和 **中广核 IMSQS 平台**。Windows 负责下载、整理及推送；Ubuntu 分别保存两平台的数据，在同一看板中查询。页面顶部可选“全部平台”或单独的平台，每条计划、变化记录和导出结果都标明来源。

## Windows：配置广核采集

需要 Node.js 20 或更高版本，以及本项目 `.venv` 的 Python。先更新 Python 依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .\collectors\cgn\config.example.json .\collectors\cgn\config.json
```

在 `collectors/cgn/config.json` 填写广核账号、密码，按原“广核自动化”的设置填写短信发送方等信息。也可把原文件夹的 `config.json` 复制到此位置。不要提交此文件；Git 已忽略配置、Cookie 会话和下载文件。迁移的是纯 HTTP 采集程序，未复制账号、密码、旧会话或抓包凭据。

广核使用当前项目根目录的 `sms_relay_config.json` 获取短信。若广核短信需要另一个取码项目，可在广核配置中设置 `smsRelayConfigPath`，或给该进程设置 `CODE_RELAY_CONFIG`；不要因为接入广核而更改 AE 正在使用的取码凭据。`CODE_RELAY_URL`、`CODE_RELAY_TOKEN` 的覆盖方式沿用原程序。

`collectors/cgn/query.json`、`export.json` 保留原下载程序的项目范围；`total`、导出结束行由本轮查询总数计算。此范围需要随广核账号实际可见项目更新，不代表平台上所有人的全部计划。

单独执行广核采集：

```powershell
.\start_cgn_sync.bat
```

它会先验证保存的广核会话，失效时只执行一次完整短信登录，然后下载、检查 Excel、入库并推送。导出失败不会再次自动请求短信。保存位置：

- 会话：`collectors/cgn/.local/session.json`
- 下载文件：`collectors/cgn/downloads/`
- 本地数据：`data/cgn_documents.db`

也可以只处理已下载文件，不登录平台：

```powershell
.\start_cgn_sync.bat --excel "C:\下载目录\质量计划信息.xlsx"
```

推送继续使用原有 `lan_sync_config.json`（URL 和同步密钥相同），广核会自动推送到 `/api/sync/database?source=cgn`；AE 仍使用原接口。Ubuntu 需先更新本次后端，之后再开启广核推送。

## Windows：加入原定时任务

在现有 `scheduler_config.json` 保留原配置，增加以下内容；不要用示例文件覆盖已经填写的配置：

```json
{
  "sources": {"ae": true, "cgn": true},
  "cgnDbPath": "data/cgn_documents.db",
  "nodeExecutable": "node"
}
```

以上是新增项示意，需合并到原 JSON。`sources` 未配置时继续只采集 AE；只启用广核可设 `ae:false`。`nodeExecutable` 可填写 Windows Node.exe 的完整路径。两平台使用原来的 `intervalMinutes` 周期，按 AE、广核顺序执行，避免同时读取短信；一个平台失败后仍会继续尝试另一个平台。各自保存上次成功的数据。重启原 `start_scheduler.bat` 后生效；`--once` 可运行一轮。

## Ubuntu：更新处理服务和网页

按 [原部署说明](DEPLOYMENT_SPLIT.md#前后端一起更新本次清单与备注功能) 更新 **整个 `dashboard_api/`**、安装该目录的 `requirements.txt`、重启 API，并更新前端 `dist/`。Ubuntu 不需要安装 Node 或广核登录脚本。新增字段适配在后端完成。

在 `/etc/nuclear-quality-dashboard.env` 保留原配置，增加：

```ini
CGN_DB_PATH=/srv/nuclear-quality-dashboard/data/cgn_documents.db
```

不填写时，广核数据默认保存在 `ECS_DB_PATH` 同目录的 `cgn_documents.db`。两个路径必须不同，所在目录需要允许服务用户写入。清单与手动备注仍保存在独立的 `quality_plan_catalog.db`。

```bash
sudo systemctl restart nuclear-quality-dashboard-api
curl --fail 'http://127.0.0.1:8787/api/health'
curl --fail 'http://127.0.0.1:8787/api/sync/status'
curl --fail 'http://127.0.0.1:8787/api/documents?source=cgn'
```

首次广核同步前网页显示“尚未收到数据”，已有 AE 数据正常显示。每个平台分别校验快照、原子更新，并分别记录接收时间。可单独查询 `?source=ae`、`?source=cgn`，默认显示两平台。备份时保留两平台数据文件、对应同步状态 JSON 及 `quality_plan_catalog.db`；仅替换网页或代码时不要覆盖 `data/`。

## 字段不同、版本不同的处理

- 广核的“质量计划名称/编码、版本、项目、机组、供应商、创建人/日期、合同订单编号”等用于通用列表。原有 AE 表格和同步接口继续可用。
- 广核计划按“质量计划编码＋版本”区分。当前样本同一编码有多个版本，不能仅按编码覆盖。不同平台的同名、同编号记录也分别保存，备注和变化记录互不串用。
- 点台账的计划名称可以查看“计划完整信息”，并导出原平台全部内容。广核 34 列完整保留，两个同名“状态”分别展示为“流程状态”“版本状态”，将来新增列也保留。未知列不会被强行当作 AE 的列。
- **广核“已审查”不计为执行完成**。当前样本只有“已审查”和“审查中”；审查中列为正在办理，已审查的执行完成情况显示待确认。只有明确的“完成/已完成”才计为完成。版本状态 CFC、历史数据以及“完成比列”原值仍在完整信息中展示，不据此猜测执行已完成。
- 广核未提供 AE 的“核安全报送级别、供方工作模式”，显示“平台未提供”，不冒充已填或未填；“核级”保留原名，不映射到报告类别。文档审核日期、审查意见发出日期也保留原意，不冒充最近审批时间。
- 导出结果标明数据平台；通用列表导出还含“原平台完整信息”，原始表格内容可在详情中另行导出为易读的两列表格。

## 导入计划清单时选择平台

清单增加可选“数据平台”列，支持 `ae` / `AE` / `AE 协调平台`，以及 `cgn` / `广核` / `中广核` / `中广核 IMSQS 平台`。没有该列时使用页面选定的平台；“全部平台”下默认为 AE，保证历史清单兼容。平台之间不自动对应。

广核同编码多版本无法确定对应哪版时，清单显示“需要核对”，不会随便选一版计入完成率。需要唯一对应时可填写只属于该版本的内部编号，并不填外部编码，或在真实清单中明确项目和机组后核对。

## 验证范围

自动化验证使用临时数据库和本地表格，覆盖双平台同编号隔离、广核多版本、重复表头和新增列保留、来源筛选、备注和变化记录、快照隔离、旧 AE 推送兼容、清单对应隔离。没有触发真实短信或真实平台登录；Windows 端真实登录、内网推送及 Ubuntu 正式服务需按实际账号与网络完成首次运行。

本地回归命令：`python -m unittest discover -s tests -v`（安装后端依赖和 `httpx`）以及 `node --test tests/test_cgn_collector.js`；前端在 `nuclear-quality-dashboard` 中运行 `npm run build`。

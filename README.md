# 核电质量数据获取与局域网看板

项目按网络边界拆成两个服务。公网 Windows 电脑运行短信取码、aTrust/AE 自动化、Excel 下载和 SQLite 汇总；内网 Ubuntu 服务器接收 Windows 主动推送的 SQLite 快照，并运行只读查询 API 和 Vue 看板。Ubuntu 不需要也不会主动访问公网。

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

之后运行 `python scheduler.py`，默认启动立即执行，之后每 60 分钟自动跑一轮；周期可在 `scheduler_config.json` 里调整。每轮都会关闭旧 aTrust 客户端、重开并重新登录，完成下载和推送后再次关闭。需要开机常驻时，在 Windows 任务计划程序中配置登录时启动 `start_scheduler.bat`。同步也会在手动执行 `main.py` 或 `ecs_sync.py` 入库后触发。看板服务器暂时不可达时，自动化采集和本地入库仍会完成，日志会提示推送失败。

## Ubuntu 内网看板

Linux 端仅部署 `dashboard_api/` 和构建后的 `nuclear-quality-dashboard/dist/`，不部署 Windows 登录自动化、短信凭据或账号配置。FastAPI API 默认使用 `ECS_DB_PATH` 指向 Ubuntu 数据目录，前端由 Nginx 托管。Nginx 对同事提供网页，并将 `/api/*` 转发到本机 API。

## 主要接口

- `PUT /api/sync/database`：公网采集端推送 SQLite 文件（二进制请求体），必须带 `Authorization: Bearer <LAN_SYNC_TOKEN>`。
- `GET /api/sync/status`：返回最近一次快照到达时间和文档数。
- `/api/health`、`/api/filters`、`/api/overview`、`/api/documents`、`/api/trace`、`/api/suppliers`、`/api/governance`、`/api/export`：看板接口。

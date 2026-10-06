# 双机部署架构

```text
短信服务器（HTTPS）                    AE / aTrust 公网平台
      ↑                                      ↑
      └──────────────┐       ┌───────────────┘
                     │       │
          Windows 公网采集端（本项目）
          - aTrust / AE 自动化取码
          - 下载 Excel，写入本机 SQLite
          - 通过 SQLite backup 生成一致性快照
                     │
          HTTP PUT + LAN_SYNC_TOKEN
                     ↓
          Ubuntu 局域网看板端
          - 认证并校验 SQLite 快照
          - 原子替换只读数据库
          - FastAPI 查询接口 + Nginx / Vue 看板
                     ↓
               局域网同事浏览器
```

## Windows 公网采集端

- `sms_relay_client.py`：短信服务 HTTPS 客户端、新码游标与轮询。
- `atrust_auto_login.py`、`ecs_auto_login.py`：登录与 Excel 下载自动化。
- `ecs_sync.py`、`excel_db.py`：Excel 解析、SQLite upsert、字段变化记录；入库完成后调用 `lan_sync_client.py` 推送快照。
- `scheduler.py`：定时同步；每轮开始时关闭旧 aTrust 进程并重新启动、短信登录，结束时关闭客户端。AE 自身会话可复用，失效后重新登录。
- `lan_sync_config.json`：内网看板地址和同步令牌；只保存在 Windows 采集端。

## Ubuntu 内网看板端

- `dashboard_api/`：FastAPI 查询接口和受令牌保护的 SQLite 快照接收接口。
- `nuclear-quality-dashboard/`：Vue 看板，构建为静态文件由 Nginx 发布。
- `data/ecs_documents.db`：Ubuntu 收到的只读看板数据库；每次成功推送会原子替换。
- `/etc/nuclear-quality-dashboard.env`：Ubuntu 保存同步令牌和数据库路径。

验证码、项目取码密钥、登录凭据和浏览器会话均不推送到 Ubuntu。Ubuntu 不连接公网短信服务，也不执行登录和 Excel 下载流程。

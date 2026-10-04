# HTTPS 短信接码版架构

## 数据获取路径

```text
短信运营商
   ↓
Android App（仅提取允许来源短信中的验证码）
   └─ HTTPS + device_token → https://www.hec-hsx.top
                                 ├─ 加密短期存储
                                 └─ HTTPS + 项目取码密钥 ← 本项目自动化程序
                                                             ↓
                                          aTrust / AE 登录与 Excel 下载
                                                             ↓
                                                   SQLite 汇聚数据库
                                                             ↓
                                           FastAPI + Vue 数据看板
```

## 认证与消息新旧判断

- Android 上传凭据为 `device_token`；本项目只使用独立的 `clients.default` 项目密钥读取，角色不可混用。
- 自动化在点击“获取验证码”前读取最近消息游标，之后只接受更大的消息 ID，防止使用旧码。
- `smsSenderContains` 用于在取回的新消息中按来源进行额外匹配；服务器项目密钥自身也须有权读取该来源。
- 短信服务器默认保留验证码 5 分钟并加密数据库内容；本地脚本不落盘保存读取到的验证码。
- 网页看板后端只向前端提供接码服务状态、来源与时间，不返回验证码或项目密钥。

## 本项目的组件

- `sms_relay_client.py`：HTTPS 健康检查、凭据读取、新码游标与轮询。
- `atrust_auto_login.py`：aTrust 界面自动操作并从云端等待短信。
- `ecs_auto_login.py`：AE/CAS 登录并从云端等待短信，再下载 Excel。
- `ecs_sync.py`、`excel_db.py`：数据同步、文件编号 upsert 与变更记录。
- `scheduler.py`：定时同步与会话恢复。
- `dashboard_api/`、`nuclear-quality-dashboard/`：本机 API 与数据可视化前端。

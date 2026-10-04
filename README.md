# 核电质量数据获取平台（HTTPS 接码版）

这是从旧 USB 短信接收项目复制出的独立版本。旧项目未改动。本版本由 Android App 将短信验证码经 HTTPS 转发至 `https://www.hec-hsx.top`，Windows 自动化程序使用项目取码密钥从服务器读取新验证码，再完成 aTrust / AE 登录、下载 Excel、写入 SQLite，并在网页看板中显示数据。

## 短信链路

```text
Android App ──HTTPS 上传──> www.hec-hsx.top ──HTTPS 长期存取接口──> 本项目自动化
                                                               │
                                                               └─> 登录、下载 Excel、更新 SQLite
                                                                          │
                                                                  Vue + FastAPI 看板
```

- 项目脚本只使用**项目取码密钥**，不使用手机的 `device_token`。
- 验证码在服务端加密保存，默认 5 分钟过期；脚本以轮询 `GET /v1/codes/recent` 的方式等待触发后的新验证码。
- aTrust 与 AE 的 `smsSenderContains` 配置仍可选填；建议配置短信来源号码/名称的一部分，避免收到其他验证码时匹配错码。
- 项目密钥优先从环境变量 `CODE_RELAY_TOKEN` 读取，也可保存在本地 `sms_relay_config.json`。该文件已加入 `.gitignore`。

## Windows 首次设置

在项目根目录运行：

```bat
setup.bat
```

脚本会创建 Python 虚拟环境、安装依赖、交互配置短信服务器与项目取码密钥，并在 Node.js 可用时构建看板。配置向导不会在终端显示密钥。可直接粘贴本机保存的 `credentials.json` 中 `clients.default` 对应值；不要使用 `device_token`。

也可将 `CODE_RELAY_URL` 和 `CODE_RELAY_TOKEN` 配置在操作系统的用户环境变量或密钥管理器中，脚本会优先读取环境变量；避免把密钥直接写入命令历史。

## 登录与数据更新

复制示例配置并填写账号：

```powershell
Copy-Item .\atrust_config.example.json .\atrust_config.json
Copy-Item .\ecs_login_config.example.json .\ecs_login_config.json
```

在 `atrust_config.json` 中填写手机号和可选短信来源筛选，在 `ecs_login_config.json` 中填写 AE 平台用户名和密码。然后：

```powershell
python .\main.py
```

单独运行定时更新：

```powershell
python .\scheduler.py --once
python .\scheduler.py
```

系统会尝试复用 AE 会话；会话失效时执行完整登录。自动化运行期间手机需开机、联网并能收到短信，但不需要 USB 连接，也不需要本机启动短信接收器。

## 网页看板

1. 先完成一次数据同步，生成 `data/ecs_documents.db`。
2. 运行 `run_dashboard_api.bat` 启动仅监听本机回环地址的 API（`127.0.0.1:8787`）。
3. 在 `nuclear-quality-dashboard` 运行 `npm run dev`，打开 Vite 显示的页面。

看板保留原有质量计划总览、台账、流程追踪、供方分析、数据治理和导出功能。左下角增加短信服务器连接状态与最近短信时间（只显示来源与时间，不在业务看板显示验证码），数据页面每分钟自动刷新。

## 文件与凭据

- `sms_relay_client.py`：短信服务 HTTPS 客户端与新码游标处理。
- `configure_sms_relay.py`：安全输入项目密钥并验证连接。
- `main.py` / `scheduler.py`：登录、定时调度和 Excel 入库流程。
- `dashboard_api/`、`nuclear-quality-dashboard/`：看板后端与前端。
- `sms_relay_config.json`、`atrust_config.json`、`ecs_login_config.json`：本地密钥/账号配置，不要提交或分享。

完整接入步骤见 [ATRUST_LOGIN_README.md](ATRUST_LOGIN_README.md)。

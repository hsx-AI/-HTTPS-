# Windows 公网采集端与 Ubuntu 内网看板部署

## 网络和数据流

| 主机 | 系统 | 工作 | 网络方向 |
|---|---|---|---|
| 公网采集电脑 | Windows | 短信取码、aTrust/AE 自动化、下载 Excel、维护本地 SQLite | 主动访问公网平台，并主动推送到内网 Ubuntu |
| 看板服务器 | Ubuntu | 接收已校验的 SQLite 快照、运行 FastAPI、托管 Vue 页面 | 不向公网请求数据；接受 Windows 推送及局域网浏览器请求 |

Pusher 配置中的现有内网服务器地址为 `10.42.60.230:8000`。本项目 API 使用独立的 `8787` 端口，默认示例地址为 `http://10.42.60.230:8787`。若看板 Ubuntu 主机不是该 IP，在 Windows 配置中替换 IP。

推送传输整个 SQLite 一致性快照，不复制正在写入的数据库文件，也不传送登录凭据或短信密钥。Windows 在每次成功入库后创建快照，以 HTTP PUT 主动发送。Ubuntu 先验证同步令牌、SQLite 完整性、表和列，再原子替换数据库；未通过校验时旧看板数据继续服务。

## 1. Ubuntu：安装内网接收端和看板

以下命令以 Ubuntu 22.04/24.04、管理员 sudo 权限为例。只把本项目的 `dashboard_api/`、构建好的前端 `dist/` 和 `deploy/` 模板传到 Ubuntu；不要传 `atrust_config.json`、`ecs_login_config.json`、`sms_relay_config.json`、账号、项目取码密钥或 Windows 会话文件。

安装运行环境：

```bash
sudo apt update
sudo apt install -y python3 python3-venv nginx
sudo useradd --system --home /srv/nuclear-quality-dashboard --create-home --shell /usr/sbin/nologin nuclear-dashboard
sudo mkdir -p /srv/nuclear-quality-dashboard/app/dashboard_api /srv/nuclear-quality-dashboard/data /srv/nuclear-quality-dashboard/web
sudo chown -R nuclear-dashboard:nuclear-dashboard /srv/nuclear-quality-dashboard
```

从 Windows 项目目录传输后端、前端构建产物和部署模板（先安装 Node.js 20 或更新版本；把 `UBUNTU_IP` 换成实际地址）：

```powershell
scp -r .\dashboard_api user@UBUNTU_IP:/tmp/nqd-dashboard-api
cd .\nuclear-quality-dashboard
npm ci
npm run build
cd ..
scp -r .\nuclear-quality-dashboard\dist user@UBUNTU_IP:/tmp/nqd-web-dist
scp -r .\deploy user@UBUNTU_IP:/tmp/nqd-deploy
```

在 Ubuntu 安装后端和前端静态文件：

```bash
sudo cp -a /tmp/nqd-dashboard-api/. /srv/nuclear-quality-dashboard/app/dashboard_api/
sudo chown -R nuclear-dashboard:nuclear-dashboard /srv/nuclear-quality-dashboard
sudo -u nuclear-dashboard python3 -m venv /srv/nuclear-quality-dashboard/venv
sudo -u nuclear-dashboard /srv/nuclear-quality-dashboard/venv/bin/pip install -r /srv/nuclear-quality-dashboard/app/dashboard_api/requirements.txt
sudo cp -a /tmp/nqd-web-dist/. /srv/nuclear-quality-dashboard/web/
sudo chown -R nuclear-dashboard:nuclear-dashboard /srv/nuclear-quality-dashboard
```

生成一个同步密钥并记下来，Windows 配置时需要使用同一个值：

```bash
openssl rand -hex 32
```

创建 `/etc/nuclear-quality-dashboard.env`，把下方同步密钥替换为刚生成的值：

```bash
sudo tee /etc/nuclear-quality-dashboard.env >/dev/null <<'EOF'
LAN_SYNC_TOKEN=替换为随机同步密钥
ECS_DB_PATH=/srv/nuclear-quality-dashboard/data/ecs_documents.db
DASHBOARD_API_HOST=0.0.0.0
DASHBOARD_API_PORT=8787
EOF
sudo chmod 600 /etc/nuclear-quality-dashboard.env
sudo chown root:root /etc/nuclear-quality-dashboard.env
```

启用 API 服务和 Nginx：

```bash
sudo cp /tmp/nqd-deploy/nuclear-quality-dashboard-api.service /etc/systemd/system/
sudo cp /tmp/nqd-deploy/nuclear-quality-dashboard.nginx.conf /etc/nginx/sites-available/nuclear-quality-dashboard
sudo ln -sfn /etc/nginx/sites-available/nuclear-quality-dashboard /etc/nginx/sites-enabled/nuclear-quality-dashboard
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now nuclear-quality-dashboard-api
sudo systemctl enable --now nginx
```

安全组或 Ubuntu 防火墙只对可信内网开放网页 `80/tcp` 及接收端口 `8787/tcp`。例如 UFW 已启用且公司网段为 `10.42.60.0/24` 时：

```bash
sudo ufw allow from 10.42.60.0/24 to any port 80 proto tcp
sudo ufw allow from 10.42.60.0/24 to any port 8787 proto tcp
```

若 Windows 公网电脑到 Ubuntu 的网络路径来源不属于该网段，应按实际受信来源调整 8787 规则；不要将 8787 映射到公网。内网同事浏览器访问 `http://Ubuntu内网IP/`。

## 2. Windows：配置公网采集与推送

继续在公网 Windows 电脑上使用本项目现有 `setup.bat` 流程，填写短信服务器、aTrust 和 AE 登录配置。该机器需要能访问公网平台，也需要能主动连接 Ubuntu 的内网地址和 TCP 8787。

在项目根目录创建 `lan_sync_config.json`，同步密钥必须与 Ubuntu 的 `LAN_SYNC_TOKEN` 完全相同：

```json
{
  "url": "http://10.42.60.230:8787",
  "token": "填入 Ubuntu 上生成的随机同步密钥"
}
```

`10.42.60.230` 是从 Pusher 读到的现有内网地址示例；如果看板实际部署 IP 不同，请改为实际 Ubuntu 内网 IP。也可以设置用户环境变量 `LAN_SYNC_URL` 和 `LAN_SYNC_TOKEN` 覆盖 JSON 文件。配置文件已加入 `.gitignore`。

正常启动定时自动化：

```powershell
Copy-Item .\scheduler_config.example.json .\scheduler_config.json
# 默认 intervalMinutes=60（每小时一轮），runImmediately=true（启动后立即执行）
python .\scheduler.py
```

在 `scheduler_config.json` 中调整 `intervalMinutes` 可更改周期，例如 `30` 表示每 30 分钟；`runImmediately` 控制启动后是否先立即执行。**每轮都会先结束旧的 aTrust 进程，再重新打开客户端、请求新的短信验证码并登录；本轮下载、入库和推送结束后关闭客户端。** AE 平台自己的已保存会话可以复用；如果失效，程序会重新登录 AE 后再下载。

### Windows 开机后自动常驻

用 Windows“任务计划程序”创建任务，让调度器在公网采集电脑登录后启动一次并自行循环：

1. “常规”选择运行任务的 Windows 用户，并选“只在用户登录时运行”。aTrust 自动化需要交互桌面会话；保持该用户登录且电脑不进入睡眠。
2. “触发器”选择“登录时”，可指定这个用户。
3. “操作”选择“启动程序”：程序填项目目录下的 `start_scheduler.bat`；“起始于”填项目根目录，例如 `C:\nuclear-quality-dashboard`。
4. 在“设置”中启用任务失败后重新启动，并设置重试间隔；不要配置每小时重复启动任务，`scheduler.py` 自身已按 `intervalMinutes` 循环，重复启动会造成并行采集。

也可手动运行 `start_scheduler.bat` 前台启动；按 `Ctrl+C` 停止。`python .\scheduler.py --once` 只执行一轮，适合部署时手动确认。手动运行 `main.py` 或 `ecs_sync.py` 入库后同样会推送。首次成功同步后，Ubuntu 会生成 `data/ecs_documents.db` 和 `data/sync_status.json`，看板侧栏显示推送时间和记录条数。Windows 端日志出现 `[LAN同步]` 即表示收到 Ubuntu 确认。

## 3. 检查与维护

Ubuntu 查看状态和日志：

```bash
sudo systemctl status nuclear-quality-dashboard-api nginx
sudo journalctl -u nuclear-quality-dashboard-api -n 100 --no-pager
curl http://127.0.0.1:8787/api/health
curl http://127.0.0.1:8787/api/sync/status
```

Windows 推送失败时先检查 `lan_sync_config.json` 中 IP/端口/令牌，再检查 Windows 到 Ubuntu 的路由和 8787 防火墙规则。推送失败不会丢失 Windows 本地 SQLite 数据；后续入库成功时会重新推送完整快照。密钥泄漏后，在 Ubuntu 和 Windows 同时换成新的随机同步密钥。

Ubuntu 只读取发布后的数据库快照，不连接短信服务、不请求公网、不执行 Windows 登录或 Excel 下载自动化。自动化凭据与取码凭据留在 Windows 公网采集端。

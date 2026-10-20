# Windows 公网采集端与 Ubuntu 内网看板部署

## 网络和数据流

| 主机 | 系统 | 工作 | 网络方向 |
|---|---|---|---|
| 公网采集电脑 | Windows | 短信取码、aTrust/AE 自动化、下载 Excel、维护本地 SQLite | 主动访问公网平台，并主动推送到内网 Ubuntu |
| 看板服务器 | Ubuntu | 接收已校验的 SQLite 快照、运行 FastAPI、托管 Vue 页面 | 不向公网请求数据；接受 Windows 推送及局域网浏览器请求 |

Pusher 配置中的现有内网服务器地址为 `10.42.60.230:8000`。本项目网页使用 `8090` 端口，API 使用独立的 `8787` 端口。看板地址为 `http://10.42.60.230:8090/`，Windows 推送地址为 `http://10.42.60.230:8787`。若看板 Ubuntu 主机不是该 IP，在 Windows 配置中替换 IP。

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

生成同步密钥并记下来，Windows 配置时需要使用同一个值。再运行一次该命令，生成独立的维护口令，仅用于网页导入清单和编辑内部编号：

```bash
openssl rand -hex 32
```

创建 `/etc/nuclear-quality-dashboard.env`，把下方同步密钥替换为刚生成的值：

```bash
sudo tee /etc/nuclear-quality-dashboard.env >/dev/null <<'EOF'
LAN_SYNC_TOKEN=替换为随机同步密钥
DASHBOARD_ADMIN_TOKEN=替换为另一个随机维护口令
PLAN_CATALOG_PATH=/srv/nuclear-quality-dashboard/data/quality_plan_catalog.db
ECS_DB_PATH=/srv/nuclear-quality-dashboard/data/ecs_documents.db
DASHBOARD_API_HOST=0.0.0.0
DASHBOARD_API_PORT=8787
EOF
sudo chmod 600 /etc/nuclear-quality-dashboard.env
sudo chown root:root /etc/nuclear-quality-dashboard.env
```

启用 API 服务和 Nginx：

```bash
sudo ss -ltnp '( sport = :8090 )'  # 应无输出；如已占用，先在 Nginx 模板中选一个空闲端口
sudo cp /tmp/nqd-deploy/nuclear-quality-dashboard-api.service /etc/systemd/system/
sudo cp /tmp/nqd-deploy/nuclear-quality-dashboard.nginx.conf /etc/nginx/sites-available/nuclear-quality-dashboard
sudo ln -sfn /etc/nginx/sites-available/nuclear-quality-dashboard /etc/nginx/sites-enabled/nuclear-quality-dashboard
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now nuclear-quality-dashboard-api
sudo systemctl enable --now nginx
```

已有部署从 80 迁移时，在 Ubuntu 上确认 8090 未被占用，再只修改本项目站点配置并重载 Nginx。若此前已照旧版说明改到 8088，同一命令也可迁移：

```bash
sudo ss -ltnp '( sport = :8090 )'
sudo cp /etc/nginx/sites-available/nuclear-quality-dashboard /etc/nginx/sites-available/nuclear-quality-dashboard.bak
sudo sed -i -E 's/listen (80|8088);/listen 8090;/' /etc/nginx/sites-available/nuclear-quality-dashboard
sudo nginx -t && sudo systemctl reload nginx
curl -I http://127.0.0.1:8090/
```

保留服务器原有的 80 端口站点配置。安全组或 Ubuntu 防火墙只对可信内网开放网页 `8090/tcp` 及接收端口 `8787/tcp`。例如 UFW 已启用且公司网段为 `10.42.60.0/24` 时：

```bash
sudo ufw allow from 10.42.60.0/24 to any port 8090 proto tcp
sudo ufw allow from 10.42.60.0/24 to any port 8787 proto tcp
```

若 Windows 公网电脑到 Ubuntu 的网络路径来源不属于该网段，应按实际受信来源调整 8787 规则；不要将 8787 映射到公网。内网同事浏览器访问 `http://Ubuntu内网IP:8090/`。

### 以后只更新前端页面

在 Windows 项目目录执行，重新构建 Vue 页面并传输构建产物：

```powershell
cd .\nuclear-quality-dashboard
npm ci
npm run build
$bundle = Join-Path $env:TEMP 'nqd-web.tgz'
tar -czf $bundle -C dist .
scp $bundle zns@10.42.60.230:/tmp/nqd-web.tgz
```

在 Ubuntu 上执行，把压缩包内容解压到 Nginx 已使用的网页目录：

```bash
sudo tar -xzf /tmp/nqd-web.tgz -C /srv/nuclear-quality-dashboard/web
sudo chown -R nuclear-dashboard:nuclear-dashboard /srv/nuclear-quality-dashboard/web
curl -I http://127.0.0.1:8090/
```

浏览器重新打开 `http://10.42.60.230:8090/`，必要时强制刷新。静态文件更新不需要重启 Nginx 或 API，也不需要重传数据库和 Windows 采集程序。

### 前后端一起更新（本次清单与备注功能）

本次增加了清单导入接口、Excel 解析依赖和独立存储，需同时更新 `dashboard_api/` 与前端构建产物。Windows 采集程序和同步配置无需修改。以下命令以此前部署目录和用户为准。

1. 在 Windows 拉取已推送的最新代码，进入项目根目录，打包前后端：

```powershell
git pull
$apiBundle = Join-Path $env:TEMP 'nqd-api.tgz'
tar --exclude=__pycache__ -czf $apiBundle dashboard_api
scp $apiBundle zns@10.42.60.230:/tmp/nqd-api.tgz
cd .\nuclear-quality-dashboard
npm ci
npm run build
$webBundle = Join-Path $env:TEMP 'nqd-web.tgz'
tar -czf $webBundle -C dist .
scp $webBundle zns@10.42.60.230:/tmp/nqd-web.tgz
```

2. 在 Ubuntu 备份当前程序和网页，然后更新后端代码、安装依赖：

```bash
sudo tar -czf "/srv/nuclear-quality-dashboard/release-backup-$(date +%Y%m%d-%H%M%S).tgz" -C /srv/nuclear-quality-dashboard app web
sudo tar -xzf /tmp/nqd-api.tgz -C /srv/nuclear-quality-dashboard/app
sudo chown -R nuclear-dashboard:nuclear-dashboard /srv/nuclear-quality-dashboard/app/dashboard_api
sudo -u nuclear-dashboard /srv/nuclear-quality-dashboard/venv/bin/pip install -r /srv/nuclear-quality-dashboard/app/dashboard_api/requirements.txt
```

本次新增 `openpyxl`、`xlrd`。若 Ubuntu 无法访问包源，需准备适配该 Ubuntu Python 版本的离线依赖包，再用 `pip install --no-index --find-links=离线目录 -r .../requirements.txt` 安装；确认安装成功后再重启服务。

3. 生成独立维护口令：`openssl rand -hex 32`。使用 `sudoedit /etc/nuclear-quality-dashboard.env`，保留原有 `LAN_SYNC_TOKEN` 和 `ECS_DB_PATH`，新增以下两行（替换口令占位符；已有同名项时修改原行）：

```ini
DASHBOARD_ADMIN_TOKEN=替换为刚生成的独立维护口令
PLAN_CATALOG_PATH=/srv/nuclear-quality-dashboard/data/quality_plan_catalog.db
```

`PLAN_CATALOG_PATH` 必须与 `ECS_DB_PATH` 使用不同文件，所在目录需允许 `nuclear-dashboard` 写入。维护口令交给需要导入清单、修改编号的内网用户；未配置时可查看看板，写入操作会提示管理员配置。

4. 重启 API 并检查，再发布前端：

```bash
sudo chmod 600 /etc/nuclear-quality-dashboard.env
sudo systemctl restart nuclear-quality-dashboard-api
sudo systemctl status nuclear-quality-dashboard-api --no-pager
curl --fail http://127.0.0.1:8787/api/health
curl --fail http://127.0.0.1:8787/api/catalog
sudo tar -xzf /tmp/nqd-web.tgz -C /srv/nuclear-quality-dashboard/web
sudo chown -R nuclear-dashboard:nuclear-dashboard /srv/nuclear-quality-dashboard/web
curl -I http://127.0.0.1:8090/
```

只有 API 正常返回后才发布网页。Nginx 配置未变，无需重新加载。访问 `http://10.42.60.230:8090/` 并强制刷新，检查“质量计划清单”页面、用真实清单预览字段映射，并在台账保存一条内部编号备注。

### 清单与备注备份

接收的 `ecs_documents.db` 来自 Windows；`quality_plan_catalog.db` 保存用户导入清单和内部编号备注，首次写入自动创建，后续 Windows 快照不会覆盖。部署更新不要覆盖或删除整个 `data/` 目录。

首次清单导入/备注保存后，可在 Ubuntu 用 SQLite backup API 备份维护库（如修改了路径，请替换）：

```bash
sudo -u nuclear-dashboard /srv/nuclear-quality-dashboard/venv/bin/python - <<'PYBACKUP'
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
source = Path('/srv/nuclear-quality-dashboard/data/quality_plan_catalog.db')
backup = source.with_name('quality_plan_catalog-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.db')
with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
    with closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
print(backup)
PYBACKUP
```

恢复维护库时先停止 API，复制选定备份到 `PLAN_CATALOG_PATH` 并确保归属 `nuclear-dashboard`，再启动 API。不会影响 Windows 的采集数据库。

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
.\start_scheduler.bat
```

在 `scheduler_config.json` 中调整 `intervalMinutes` 可更改周期，例如 `30` 表示每 30 分钟；`runImmediately` 控制启动后是否先立即执行。**每轮都会先结束旧的 aTrust 进程，再重新打开客户端、请求新的短信验证码并登录；本轮下载、入库和推送结束后关闭客户端。** AE 平台自己的已保存会话可以复用；如果失效，程序会重新登录 AE 后再下载。

### Windows 开机后自动常驻

用 Windows“任务计划程序”创建任务，让调度器在公网采集电脑登录后启动一次并自行循环：

1. “常规”选择运行任务的 Windows 用户，并选“只在用户登录时运行”。aTrust 自动化需要交互桌面会话；保持该用户登录且电脑不进入睡眠。
2. “触发器”选择“登录时”，可指定这个用户。
3. “操作”选择“启动程序”：程序填项目目录下的 `start_scheduler.bat`；“起始于”填项目根目录，例如 `C:\nuclear-quality-dashboard`。
4. 在“设置”中启用任务失败后重新启动，并设置重试间隔；不要配置每小时重复启动任务，`scheduler.py` 自身已按 `intervalMinutes` 循环，重复启动会造成并行采集。

也可手动运行 `start_scheduler.bat` 前台启动；按 `Ctrl+C` 停止。`.\start_scheduler.bat --once` 只执行一轮，适合部署时手动确认。手动运行 `main.py` 或 `ecs_sync.py` 时也应使用 `.\.venv` 中的 Python；入库后同样会推送。首次成功同步后，Ubuntu 会生成 `data/ecs_documents.db` 和 `data/sync_status.json`，看板侧栏显示推送时间和记录条数。Windows 端日志出现 `[LAN同步]` 即表示收到 Ubuntu 确认。

若 Windows 报 `ModuleNotFoundError: No module named 'Crypto'`，在项目根目录执行 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`，再运行 `.\start_scheduler.bat`。`pycryptodome` 提供代码使用的 `Crypto` 包；安装到其他 Python 环境不会修复项目 `.venv` 中缺包的问题。

## 3. 检查与维护

Ubuntu 查看状态和日志：

```bash
sudo systemctl status nuclear-quality-dashboard-api nginx
sudo journalctl -u nuclear-quality-dashboard-api -n 100 --no-pager
curl http://127.0.0.1:8787/api/health
curl http://127.0.0.1:8787/api/sync/status
curl -I http://127.0.0.1:8090/
```

Windows 推送失败时先检查 `lan_sync_config.json` 中 IP/端口/令牌，再检查 Windows 到 Ubuntu 的路由和 8787 防火墙规则。推送失败不会丢失 Windows 本地 SQLite 数据；后续入库成功时会重新推送完整快照。密钥泄漏后，在 Ubuntu 和 Windows 同时换成新的随机同步密钥。

Ubuntu 只读取发布后的数据库快照，不连接短信服务、不请求公网、不执行 Windows 登录或 Excel 下载自动化。自动化凭据与取码凭据留在 Windows 公网采集端。

# 核电质量计划看板

Vue 看板 + FastAPI 后端。开发模式读取项目目录的 SQLite；正式部署时，Vue 静态文件由 Ubuntu 上的 Nginx 发布，FastAPI 读取 Ubuntu 收到的 SQLite 快照。公网 Windows 采集端在每次入库后主动推送，不要求 Ubuntu 访问公网。

双机安装步骤见项目根目录的 [DEPLOYMENT_SPLIT.md](../DEPLOYMENT_SPLIT.md)。

## 启动

先开后端（默认 `127.0.0.1:8787`）：

```powershell
.\run_dashboard_api.bat
# 或
.venv\Scripts\python.exe -m dashboard_api.main
```

再开前端：

```powershell
cd nuclear-quality-dashboard
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（通常是 `http://127.0.0.1:5173`）。前端通过代理访问 `/api/*`。

## 页面

- 质量计划总览：指标卡、状态分布、制造单位、清单、报送级别
- 计划台账：搜索 / 状态筛选 / 分页
- 流程追踪：节点停留、处理中计划、近期字段变更
- 供方分析：供方排行、工作模式分布
- 数据治理：字段完整率、同步批次、变更明细
- 侧栏显示云端短信服务连接状态与最近收码时间；不向浏览器返回验证码或取码密钥
- 页面每分钟自动刷新，显示最新入库数据

## 主要接口

- `GET /api/health`
- `GET /api/filters`
- `GET /api/overview`
- `GET /api/documents`
- `GET /api/trace`
- `GET /api/suppliers`
- `GET /api/governance`
- `GET /api/export`

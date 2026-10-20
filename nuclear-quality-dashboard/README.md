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

- 质量计划总览：指标和分布点击查看明细，项目与机组联动
- 质量计划清单：Excel/CSV 导入、字段映射、计划与实际对比、供方筛选和导出
- 计划台账：搜索 / 状态与报送级别筛选 / 分页 / 内部编号备注 / 审批时间
- 流程追踪：处理中计划检索和分页、选中计划对应的字段变更
- 供方分析：供方排行、工作模式分布
- 数据治理：字段完整率、同步批次、变更明细
- 侧栏显示内网 API 状态与最近收到的数据库快照信息
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

清单导入和编号备注需要配置 `DASHBOARD_ADMIN_TOKEN`，完整规则见根目录 [README](../README.md#清单与台账维护)。本次更新需同时部署后端与前端。

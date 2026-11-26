# 项目交付要求

- 固定发布流程：Mac 上开发和本地验收，由负责人使用 GitHub Desktop 提交并推送；Ubuntu 上从已配置的 Git 检出目录执行同一个入口 `sudo ./deploy/update-linux.sh`。不要把手动 pip、npm、SQL 或复制数据库作为例行发布步骤。
- 每次开发必须保证服务器能从上一版经该入口直接升级。新增后端运行依赖时，在同一提交更新 `dashboard_api/requirements.txt`；测试专用依赖与运行依赖区分。新增前端依赖时更新 `package.json` 和锁文件。
- 修改已有 SQLite 表结构时，在同一提交向 `dashboard_api/migrations.py` 追加可重复识别的版本化迁移，不改写已发布迁移。升级前备份受影响的库，迁移不得清空现有业务数据。
- 涉及构建、启动、systemd、Nginx 或环境变量变化时，同步更新 `deploy/update-linux.sh`、模板和部署文档。保留服务器的 `data/`、服务环境文件及口令；不把本机 `.venv`、`node_modules`、真实 PDF、数据库、备份或演示数据纳入发布。
- 交付前验证前端构建、后端依赖和测试、旧库升级、重复部署或重复迁移，以及失败提示；不能在 Mac 模拟的 Ubuntu 服务步骤明确列为上线首次核对项。

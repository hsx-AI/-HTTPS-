#!/usr/bin/env bash
# Run from the Ubuntu Git checkout: sudo ./deploy/update-linux.sh
set -Eeuo pipefail

step='预检'
cutover=0
stage=''
rollback_dir=''

fail() {
  printf '部署失败 [%s]：%s\n' "$step" "$*" >&2
  if (( cutover )); then on_error 1; fi
  exit 1
}
restore_path() {
  local live=$1 old=$2
  if [[ -L "$live" ]]; then unlink "$live"; fi
  if [[ -e "$old" || -L "$old" ]]; then mv "$old" "$live"; fi
}
on_error() {
  local code=${1:-$?}
  trap - ERR
  set +e
  printf '部署失败 [%s]，退出码 %s。\n' "$step" "$code" >&2
  if (( cutover )); then
    printf '正在恢复上一版程序、网页和服务配置；数据库备份保留在 %s/backups。\n' "$DEPLOY_ROOT" >&2
    restore_path "$DEPLOY_ROOT/app/dashboard_api" "$rollback_dir/dashboard_api"
    restore_path "$DEPLOY_ROOT/web/dist" "$rollback_dir/dist"
    restore_path "$DEPLOY_ROOT/venv" "$rollback_dir/venv"
    cp -a "$rollback_dir/service.conf" "$DEPLOY_SERVICE_FILE"
    cp -a "$rollback_dir/nginx.conf" "$DEPLOY_NGINX_FILE"
    systemctl daemon-reload || true
    nginx -t && systemctl reload nginx || true
    systemctl restart "$DEPLOY_SERVICE" || true
  fi
  printf '请查看上面的失败步骤及 journalctl -u %s；需要恢复数据库时，先停止服务，再从备份目录选取升级前 SQLite 快照。\n' "${DEPLOY_SERVICE:-服务名}" >&2
  exit "$code"
}
trap on_error ERR

[[ $EUID -eq 0 ]] || fail '请用 sudo 运行此脚本'
[[ $(uname -s) == Linux ]] || fail '部署入口只在 Linux 上运行'
config=${NQD_DEPLOY_CONFIG:-/etc/nuclear-quality-dashboard-deploy.conf}
[[ -f "$config" ]] || fail "缺少首次接入配置 $config；请参照 deploy/update-linux.conf.example"
# This root-owned file contains paths and names only; credentials stay in the service env file.
[[ $(stat -c %u "$config") == 0 ]] || fail '部署配置必须由 root 持有'
# shellcheck disable=SC1090
source "$config"
for key in DEPLOY_BRANCH DEPLOY_ROOT DEPLOY_GIT_USER DEPLOY_SERVICE_USER DEPLOY_SERVICE DEPLOY_PYTHON DEPLOY_ENV_FILE DEPLOY_SERVICE_FILE DEPLOY_NGINX_FILE DEPLOY_API_URL DEPLOY_WEB_URL; do
  [[ -n ${!key:-} ]] || fail "首次接入配置缺少 $key"
done
[[ $DEPLOY_BRANCH =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && $DEPLOY_BRANCH != *..* ]] || fail '部署分支名称无效'
[[ $DEPLOY_ROOT == /* && $DEPLOY_PYTHON == /* && $DEPLOY_ENV_FILE == /* ]] || fail '部署路径必须是绝对路径'
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
for command in git tar npm runuser systemctl nginx curl "$DEPLOY_PYTHON"; do
  command -v "$command" >/dev/null || fail "缺少命令：$command"
done
id "$DEPLOY_GIT_USER" >/dev/null || fail 'Git 操作用户不存在'
id "$DEPLOY_SERVICE_USER" >/dev/null || fail '服务用户不存在'
[[ -f "$DEPLOY_ENV_FILE" ]] || fail "服务环境文件不存在：$DEPLOY_ENV_FILE"
for live in "$DEPLOY_ROOT/app/dashboard_api" "$DEPLOY_ROOT/web/dist" "$DEPLOY_ROOT/venv" "$DEPLOY_SERVICE_FILE" "$DEPLOY_NGINX_FILE"; do
  [[ -e "$live" || -L "$live" ]] || fail "现有部署路径不存在：$live；此脚本用于从上一版升级"
done
[[ $(runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" rev-parse --show-toplevel) == "$repo" ]] || fail '请从服务器的 Git 检出目录执行'
[[ $(runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" branch --show-current) == "$DEPLOY_BRANCH" ]] || fail '当前分支与部署分支不一致'
runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" diff --quiet || fail '服务器检出目录有未提交修改'
runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" diff --cached --quiet || fail '服务器检出目录有暂存修改'
grep -Fq "WorkingDirectory=$DEPLOY_ROOT/app" "$repo/deploy/nuclear-quality-dashboard-api.service" || fail 'systemd 模板与 DEPLOY_ROOT 不一致'
grep -Fq "ExecStart=$DEPLOY_ROOT/venv/bin/uvicorn" "$repo/deploy/nuclear-quality-dashboard-api.service" || fail 'systemd Python 环境与 DEPLOY_ROOT 不一致'
grep -Fq "User=$DEPLOY_SERVICE_USER" "$repo/deploy/nuclear-quality-dashboard-api.service" || fail 'systemd 服务用户与配置不一致'
grep -Fq "EnvironmentFile=$DEPLOY_ENV_FILE" "$repo/deploy/nuclear-quality-dashboard-api.service" || fail 'systemd 环境文件与配置不一致'
grep -Fq "root $DEPLOY_ROOT/web/dist;" "$repo/deploy/nuclear-quality-dashboard.nginx.conf" || fail 'Nginx 模板与 DEPLOY_ROOT 不一致'

step='拉取部署分支'
runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" fetch origin "refs/heads/$DEPLOY_BRANCH:refs/remotes/origin/$DEPLOY_BRANCH"
runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" merge --ff-only "origin/$DEPLOY_BRANCH"
revision=$(runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" rev-parse --short HEAD)

step='准备隔离发布目录'
release_id=$(date +%Y%m%d-%H%M%S)-$revision
install -d -m 755 "$DEPLOY_ROOT/releases" "$DEPLOY_ROOT/backups"
stage="$DEPLOY_ROOT/releases/$release_id"
[[ ! -e "$stage" ]] || fail "发布目录已存在：$stage"
install -d -o "$DEPLOY_GIT_USER" -g "$(id -gn "$DEPLOY_GIT_USER")" "$stage"
runuser -u "$DEPLOY_GIT_USER" -- git -C "$repo" archive HEAD dashboard_api nuclear-quality-dashboard deploy | tar -x -C "$stage"
[[ -f "$stage/dashboard_api/requirements.txt" && -f "$stage/nuclear-quality-dashboard/package-lock.json" ]] || fail '发布源码不完整'
grep -Fq "WorkingDirectory=$DEPLOY_ROOT/app" "$stage/deploy/nuclear-quality-dashboard-api.service" || fail '新版本 systemd 模板与部署根目录不一致'
grep -Fq "ExecStart=$DEPLOY_ROOT/venv/bin/uvicorn" "$stage/deploy/nuclear-quality-dashboard-api.service" || fail '新版本 systemd Python 环境与部署根目录不一致'
grep -Fq "User=$DEPLOY_SERVICE_USER" "$stage/deploy/nuclear-quality-dashboard-api.service" || fail '新版本 systemd 服务用户与配置不一致'
grep -Fq "EnvironmentFile=$DEPLOY_ENV_FILE" "$stage/deploy/nuclear-quality-dashboard-api.service" || fail '新版本 systemd 环境文件与配置不一致'
grep -Fq "root $DEPLOY_ROOT/web/dist;" "$stage/deploy/nuclear-quality-dashboard.nginx.conf" || fail '新版本 Nginx 模板与部署根目录不一致'

step='安装并构建前端'
runuser -u "$DEPLOY_GIT_USER" -- npm ci --prefix "$stage/nuclear-quality-dashboard"
runuser -u "$DEPLOY_GIT_USER" -- npm run build --prefix "$stage/nuclear-quality-dashboard"
[[ -s "$stage/nuclear-quality-dashboard/dist/index.html" ]] || fail '前端构建没有生成首页'
rm -rf "$stage/nuclear-quality-dashboard/node_modules"

step='准备后端实际运行环境'
chown -R "$DEPLOY_SERVICE_USER:$(id -gn "$DEPLOY_SERVICE_USER")" "$stage"
runuser -u "$DEPLOY_SERVICE_USER" -- "$DEPLOY_PYTHON" -m venv "$stage/venv"
runuser -u "$DEPLOY_SERVICE_USER" -- "$stage/venv/bin/python" -m pip install -r "$stage/dashboard_api/requirements.txt"
runuser -u "$DEPLOY_SERVICE_USER" -- "$stage/venv/bin/python" -m pip check
runuser -u "$DEPLOY_SERVICE_USER" -- env PYTHONPATH="$stage" "$stage/venv/bin/python" -c 'import pdfplumber; from dashboard_api.main import app'

step='备份并升级业务数据库'
# Read only the database paths. Do not execute or export the service's secret-bearing environment file.
db_output=$("$DEPLOY_PYTHON" - "$DEPLOY_ENV_FILE" <<'PY'
import sys
values = {}
for line in open(sys.argv[1], encoding='utf-8'):
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    if key.strip() in ('PLAN_CATALOG_PATH', 'ECS_DB_PATH'):
        values[key.strip()] = value.strip().strip(chr(34) + chr(39))
for key in ('PLAN_CATALOG_PATH', 'ECS_DB_PATH'):
    print(values.get(key, ''))
PY
)
mapfile -t db_paths <<< "$db_output"
PLAN_CATALOG_PATH=${db_paths[0]:-}
ECS_DB_PATH=${db_paths[1]:-}
[[ ${PLAN_CATALOG_PATH:-} == /* && ${ECS_DB_PATH:-} == /* ]] || fail '服务环境必须设置绝对路径 PLAN_CATALOG_PATH 和 ECS_DB_PATH'
chown "$DEPLOY_SERVICE_USER:$(id -gn "$DEPLOY_SERVICE_USER")" "$DEPLOY_ROOT/backups"
runuser -u "$DEPLOY_SERVICE_USER" -- env -i PATH=/usr/bin:/bin PYTHONPATH="$stage" PLAN_CATALOG_PATH="$PLAN_CATALOG_PATH" ECS_DB_PATH="$ECS_DB_PATH" NQD_BACKUP_DIR="$DEPLOY_ROOT/backups" "$stage/venv/bin/python" -m dashboard_api.migrations

step='切换发布版本'
release="$stage"
stage=''
rollback_dir="$DEPLOY_ROOT/releases/previous-$release_id"
mkdir -m 700 "$rollback_dir"
cp -a "$DEPLOY_SERVICE_FILE" "$rollback_dir/service.conf"
cp -a "$DEPLOY_NGINX_FILE" "$rollback_dir/nginx.conf"
cutover=1
systemctl stop "$DEPLOY_SERVICE"
mv "$DEPLOY_ROOT/app/dashboard_api" "$rollback_dir/dashboard_api"
mv "$DEPLOY_ROOT/web/dist" "$rollback_dir/dist"
mv "$DEPLOY_ROOT/venv" "$rollback_dir/venv"
ln -s "$release/dashboard_api" "$DEPLOY_ROOT/app/dashboard_api"
ln -s "$release/nuclear-quality-dashboard/dist" "$DEPLOY_ROOT/web/dist"
ln -s "$release/venv" "$DEPLOY_ROOT/venv"
install -m 644 "$release/deploy/nuclear-quality-dashboard-api.service" "$DEPLOY_SERVICE_FILE"
install -m 644 "$release/deploy/nuclear-quality-dashboard.nginx.conf" "$DEPLOY_NGINX_FILE"
nginx -t
systemctl daemon-reload
systemctl reload nginx
systemctl restart "$DEPLOY_SERVICE"

step='检查首页和 API'
systemctl is-active --quiet "$DEPLOY_SERVICE"
ready=0
for attempt in {1..15}; do
  if curl --fail --silent --show-error --max-time 5 "$DEPLOY_API_URL/api/health" >/dev/null && \
     curl --fail --silent --show-error --max-time 5 "$DEPLOY_API_URL/api/catalog/pdf/latest" >/dev/null; then
    ready=1; break
  fi
  sleep 1
done
(( ready )) || fail 'API 健康检查未通过'
curl --fail --silent --show-error --max-time 10 "$DEPLOY_WEB_URL" | grep -q 'id="app"' || fail '网页首页检查未通过'
cutover=0
printf '部署成功：%s；上一版程序保存在 %s；数据库备份在 %s/backups。\n' "$revision" "$rollback_dir" "$DEPLOY_ROOT"

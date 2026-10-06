from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "lan_sync_config.json"


def load_config() -> dict[str, str]:
    config: dict[str, str] = {}
    if DEFAULT_CONFIG.exists():
        config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    url = os.environ.get("LAN_SYNC_URL", config.get("url", "")).strip().rstrip("/")
    token = os.environ.get("LAN_SYNC_TOKEN", config.get("token", "")).strip()
    if not url or not token or token.startswith("在这里填写"):
        return {}
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return {"url": url, "token": token}


def make_consistent_snapshot(db_path: Path) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"本地汇总数据库不存在：{db_path}")
    fd, raw_path = tempfile.mkstemp(prefix="ecs_snapshot_", suffix=".db")
    os.close(fd)
    snapshot_path = Path(raw_path)
    try:
        with sqlite3.connect(str(db_path), timeout=30) as source, sqlite3.connect(str(snapshot_path)) as target:
            source.backup(target)
        return snapshot_path
    except Exception:
        snapshot_path.unlink(missing_ok=True)
        raise


def push_database(db_path: Path) -> dict | None:
    config = load_config()
    if not config:
        print("[LAN同步] 未配置 LAN_SYNC_URL / LAN_SYNC_TOKEN，跳过内网推送。", flush=True)
        return None

    snapshot_path = make_consistent_snapshot(db_path)
    try:
        payload = snapshot_path.read_bytes()
        request = Request(
            config["url"] + "/api/sync/database",
            data=payload,
            method="PUT",
            headers={
                "Authorization": "Bearer " + config["token"],
                "Content-Type": "application/vnd.sqlite3",
                "Content-Length": str(len(payload)),
            },
        )
        try:
            with urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(f"内网服务器拒绝数据库推送：HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"无法连接内网看板服务器：{exc.reason}") from exc
        print(
            f"[LAN同步] 数据库已推送：{result.get('documentCount', '?')} 条，"
            f"接收时间 {result.get('receivedAt', '?')}",
            flush=True,
        )
        return result
    finally:
        snapshot_path.unlink(missing_ok=True)

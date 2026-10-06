from __future__ import annotations

import csv
import hmac
import io
import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import queries
from .db import resolve_db_path


app = FastAPI(title="核电质量计划看板 API", version="1.0.0")
MAX_DATABASE_BYTES = 512 * 1024 * 1024
REQUIRED_DOCUMENT_COLUMNS = {
    "文件名称", "文件编号", "文件版本", "所属项目", "制造单位", "流程状态", "版本状态",
    "是否分章节", "创建时间", "发起人", "文件类别", "适用机组号", "供应商名称", "设备名称",
    "合同号", "核安全报送级别", "是否采购分包", "是否含SPV设备", "SPV位号", "总包方部门",
    "板块", "相关供方工作模式", "制造单位供方级别", "审查结论", "发起单位", "fetched_at",
}


def sync_status_path() -> Path:
    return resolve_db_path().parent / "sync_status.json"


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    db_path = resolve_db_path()
    return {
        "ok": db_path.exists(),
        "dbPath": str(db_path),
        "message": "ready" if db_path.exists() else "database missing",
    }


@app.get("/api/sync/status")
def sync_status() -> dict:
    path = sync_status_path()
    if not path.exists():
        return {"ok": False, "message": "尚未收到公网采集端推送"}
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        return {"ok": True, **status}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "message": f"读取同步状态失败：{exc}"}


@app.put("/api/sync/database")
async def receive_database(request: Request, authorization: str = Header(default="")) -> dict:
    expected = os.environ.get("LAN_SYNC_TOKEN", "").strip()
    supplied = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="unauthorized")

    db_path = resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".ecs_receive_", suffix=".db", dir=db_path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    total_bytes = 0
    try:
        with temp_path.open("wb") as target:
            async for chunk in request.stream():
                total_bytes += len(chunk)
                if total_bytes > MAX_DATABASE_BYTES:
                    raise HTTPException(status_code=413, detail="database snapshot too large")
                target.write(chunk)
        if total_bytes < 100:
            raise HTTPException(status_code=400, detail="empty or invalid database snapshot")

        try:
            conn = sqlite3.connect(temp_path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                check = conn.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise ValueError("SQLite integrity check failed")
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"documents", "document_changes"}.issubset(tables):
                    raise ValueError("required dashboard tables are missing")
                columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
                missing = REQUIRED_DOCUMENT_COLUMNS - columns
                if missing:
                    raise ValueError(f"required document columns are missing: {', '.join(sorted(missing))}")
                change_columns = {row[1] for row in conn.execute("PRAGMA table_info(document_changes)")}
                if not {"文件编号", "field_name", "old_value", "new_value", "changed_at", "source_file", "sync_batch_id"}.issubset(change_columns):
                    raise ValueError("required change tracking columns are missing")
                document_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
                latest_fetched_at = conn.execute("SELECT MAX(fetched_at) FROM documents").fetchone()[0]
            finally:
                conn.close()
        except (sqlite3.DatabaseError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid dashboard database: {exc}") from exc

        os.replace(temp_path, db_path)
        received_at = datetime.now().astimezone().isoformat(timespec="seconds")
        status = {
            "receivedAt": received_at,
            "documentCount": document_count,
            "latestFetchedAt": latest_fetched_at,
            "databaseBytes": total_bytes,
        }
        sync_status_path().write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, **status}
    finally:
        temp_path.unlink(missing_ok=True)


@app.get("/api/filters")
def filters() -> dict:
    return queries.get_filter_options()


@app.get("/api/overview")
def overview(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
) -> dict:
    return queries.get_overview(project, group, period)


@app.get("/api/documents")
def documents(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
    status: str = Query("全部"),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=200),
) -> dict:
    return queries.get_documents(project, group, period, status, q, page, pageSize)


@app.get("/api/trace")
def trace(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
) -> dict:
    return queries.get_trace(project, group, period)


@app.get("/api/suppliers")
def suppliers(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
) -> dict:
    return queries.get_suppliers(project, group, period)


@app.get("/api/governance")
def governance() -> dict:
    return queries.get_governance()


@app.get("/api/export")
def export_csv(
    project: str = Query("全部"),
    group: str = Query("全部"),
    period: str = Query("全部"),
    status: str = Query("全部"),
    q: str = Query(""),
) -> StreamingResponse:
    rows = queries.export_rows(project, group, period, status, q)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["文件名称", "文件编号", "制造单位", "流程状态", "创建时间", "适用机组号", "核安全报送级别", "合同号"])
    for row in rows:
        writer.writerow(
            [
                row["name"],
                row["code"],
                row["company"],
                row["status"],
                row["date"],
                row["unit"],
                row["reportLevel"],
                row["contractNo"],
            ]
        )
    payload = "\ufeff" + buffer.getvalue()
    return StreamingResponse(
        iter([payload.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nuclear-quality-plans.csv"'},
    )


def main() -> None:
    import uvicorn

    host = os.environ.get("DASHBOARD_API_HOST", "0.0.0.0")
    port = int(os.environ.get("DASHBOARD_API_PORT", "8787"))
    uvicorn.run("dashboard_api.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

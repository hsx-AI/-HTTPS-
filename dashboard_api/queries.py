from __future__ import annotations

from datetime import date, datetime, timedelta
from contextlib import closing

from . import catalog
from typing import Any

from .db import connect, qident, resolve_db_path, available_sources, SOURCES, active_source


STATUS_COLORS = {
    "完成": "#27b99a",
    "审查/选点": "#f4ad48",
    "制造方编制": "#668ff0",
    "制造方审核": "#9c82ed",
    "其他": "#9aaabc",
}
COMPANY_COLORS = ["#29bfd0", "#668ff0", "#27b99a", "#f4ad48", "#9c82ed", "#5a88e4", "#e79b35", "#20ad89"]
REPORT_COLORS = ["#29bfd0", "#668ff0", "#f4ad48", "#9c82ed", "#9aaabc", "#27b99a"]

STATUS_SHORT = {
    "完成": "完成",
    "上海院监造人员审查/选点": "审查/选点",
    "制造方编制": "制造方编制",
    "制造方审核": "制造方审核",
}

STATUS_TONE = {
    "完成": "green",
    "审查/选点": "orange",
    "制造方编制": "blue",
    "制造方审核": "purple",
}


def short_status(raw: str) -> str:
    value = (raw or "").strip()
    return STATUS_SHORT.get(value, value or "未填写")


def short_company(name: str) -> str:
    text = (name or "").strip()
    for token in ("股份有限公司", "有限公司", "有限责任公司", "集团公司", "集团"):
        text = text.replace(token, "")
    return text[:10] or "未填写"


def status_tone(raw: str) -> str:
    return STATUS_TONE.get(short_status(raw), "blue")


def period_start(period: str) -> str | None:
    today = date.today()
    if period == "近30天":
        return (today - timedelta(days=30)).isoformat()
    if period == "本季度":
        quarter = (today.month - 1) // 3
        return date(today.year, quarter * 3 + 1, 1).isoformat()
    if period == "本年度":
        return date(today.year, 1, 1).isoformat()
    return None


def build_filters(project: str, group: str, period: str, status: str = "", q: str = "", report_level: str = "", company: str = "") -> tuple[str, list[Any]]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if project and project != "全部":
        clauses.append(f"{qident('所属项目')}=?")
        params.append(project)
    if group and group != "全部":
        clauses.append(f"{qident('适用机组号')}=?")
        params.append(group)
    start = period_start(period)
    if start:
        clauses.append(f"{qident('创建时间')}>=?")
        params.append(start)
    if report_level == '平台未提供':
        clauses.append("source_id='cgn'")
    elif report_level and report_level != "全部":
        clauses.append(f"COALESCE(NULLIF(TRIM({qident('核安全报送级别')}), ''), '未填写')=?")
        params.append(report_level)
    if company:
        clauses.append(f"{qident('制造单位')}=?")
        params.append(company)
    if status == "处理中":
        clauses.append("completion_state='active'")
    elif status == "完成":
        clauses.append("completion_state='done'")
    elif status == "完成情况待确认":
        clauses.append("completion_state='unknown'")
    elif status == "未填写":
        clauses.append(f"COALESCE(TRIM({qident('流程状态')}), '')=''")
    elif status and status != "全部":
        # Accept either short or full status labels.
        full_values = [k for k, v in STATUS_SHORT.items() if v == status]
        if full_values:
            placeholders = ", ".join("?" for _ in full_values)
            clauses.append(f"{qident('流程状态')} IN ({placeholders})")
            params.extend(full_values)
        else:
            clauses.append(f"{qident('流程状态')}=?")
            params.append(status)
    if q.strip():
        like = f"%{q.strip()}%"
        clauses.append(
            "("
            f"{qident('文件名称')} LIKE ? OR "
            f"{qident('文件编号')} LIKE ? OR "
            f"{qident('制造单位')} LIKE ?"
            ")"
        )
        params.extend([like, like, like])
    return " AND ".join(clauses), params


def fetch_distinct(conn, column: str) -> list[str]:
    rows = conn.execute(
        f"SELECT DISTINCT {qident(column)} AS v FROM documents "
        f"WHERE {qident(column)} IS NOT NULL AND TRIM({qident(column)})!='' "
        f"ORDER BY {qident(column)}"
    ).fetchall()
    return [str(row["v"]) for row in rows]


def group_count(conn, column: str, where: str, params: list[Any], limit: int | None = None) -> list[dict]:
    label_sql = f"COALESCE(NULLIF(TRIM({qident(column)}), ''), '未填写')"
    if column == '核安全报送级别': label_sql = f"CASE WHEN source_id='cgn' THEN '平台未提供' ELSE {label_sql} END"
    sql = (
        f"SELECT {label_sql} AS label, COUNT(*) AS value "
        f"FROM documents WHERE {where} "
        f"GROUP BY 1 ORDER BY value DESC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [{"label": row["label"], "value": int(row["value"])} for row in conn.execute(sql, params)]


def meta(conn) -> dict:
    row = conn.execute(
        f"SELECT COUNT(*) AS total, MAX(fetched_at) AS last_fetched, "
        f"MIN({qident('创建时间')}) AS min_created, MAX({qident('创建时间')}) AS max_created "
        f"FROM documents"
    ).fetchone()
    change_count = conn.execute("SELECT COUNT(*) FROM document_changes").fetchone()[0]
    return {
        "dbPath": str(resolve_db_path()),
        "sources": [dict(r) for r in conn.execute('SELECT source_id AS source, source_label AS label, COUNT(*) AS count, MAX(fetched_at) AS lastFetchedAt FROM documents GROUP BY source_id,source_label')],
        "totalDocuments": int(row["total"] or 0),
        "lastFetchedAt": row["last_fetched"],
        "createdRange": [row["min_created"], row["max_created"]],
        "changeCount": int(change_count or 0),
    }


def get_filter_options() -> dict:
    with closing(connect()) as conn:
        pairs = [(row[0], row[1]) for row in conn.execute('SELECT DISTINCT "所属项目", "适用机组号" FROM documents')]
        pairs += [(r['project'], r['unit']) for r in catalog.read_catalog() if active_source.get() in ('全部', r.get('dataSource','ae'))]
        project_groups = {}
        for project, unit in pairs:
            if project:
                project_groups.setdefault(project, set())
                if unit:
                    project_groups[project].add(unit)
        return {
            "sources": available_sources(),
            "projects": ["全部", *sorted(project_groups)],
            "groups": ["全部", *sorted({u for _, u in pairs if u})],
            "projectGroups": {p: ["全部", *sorted(units)] for p, units in project_groups.items()},
            "periods": ["全部", "近30天", "本季度", "本年度"],
            "statuses": ["全部", "处理中", "完成情况待确认", *sorted({short_status(r[0]) for r in conn.execute('SELECT DISTINCT "流程状态" FROM documents')})],
            "reportLevels": ["全部", *[r['label'] for r in group_count(conn, '核安全报送级别', '1=1', [])]],
            "meta": meta(conn),
        }


def get_overview(project: str, group: str, period: str) -> dict:
    where, params = build_filters(project, group, period)
    with closing(connect()) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where}", params).fetchone()[0]
        status_rows = group_count(conn, "流程状态", where, params)
        company_rows = group_count(conn, "制造单位", where, params)
        report_rows = group_count(conn, "核安全报送级别", where, params)
        unit_rows = group_count(conn, "适用机组号", where, params)

        status_stats = []
        for row in status_rows:
            label = short_status(row["label"])
            existing = next((item for item in status_stats if item["label"] == label), None)
            if existing:
                existing["value"] += row["value"]
            else:
                status_stats.append(
                    {
                        "label": label,
                        "value": row["value"],
                        "color": STATUS_COLORS.get(label, STATUS_COLORS["其他"]),
                    }
                )

        completed = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where} AND completion_state='done'", params).fetchone()[0]
        in_progress = conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where} AND completion_state='active'", params).fetchone()[0]
        unknown = total - completed - in_progress
        review = next((item["value"] for item in status_stats if item["label"] == "审查/选点"), 0)
        drafting = next((item["value"] for item in status_stats if item["label"] == "制造方编制"), 0)
        auditing = next((item["value"] for item in status_stats if item["label"] == "制造方审核"), 0)
        company_count = len(company_rows)
        top_companies = [
            {
                "label": short_company(item["label"]),
                "fullLabel": item["label"],
                "value": item["value"],
                "color": COMPANY_COLORS[index % len(COMPANY_COLORS)],
            }
            for index, item in enumerate(company_rows[:5])
        ]
        others = sum(item["value"] for item in company_rows[5:])
        reporting_stats = [
            {
                "label": item["label"],
                "value": item["value"],
                "color": REPORT_COLORS[index % len(REPORT_COLORS)],
            }
            for index, item in enumerate(report_rows)
        ]
        filled_report = sum(item["value"] for item in report_rows if item["label"] not in ("未填写", "平台未提供"))
        top_company_note = (
            f"{top_companies[0]['label']} {top_companies[0]['value']} 份"
            if top_companies
            else "暂无制造单位"
        )

        latest = conn.execute(
            f"""
            SELECT {qident('文件名称')} AS name,
                   {qident('文件编号')} AS code, display_code AS displayCode, source_id AS source, source_label AS sourceLabel,
                   {qident('制造单位')} AS company,
                   {qident('流程状态')} AS status,
                   {qident('创建时间')} AS date
            FROM documents
            WHERE {where}
            ORDER BY {qident('创建时间')} DESC, {qident('文件编号')} DESC
            LIMIT 20
            """,
            params,
        ).fetchall()
        plans = [
            {
                "name": row["name"],
                "code": row["code"], "displayCode": row["displayCode"], "source": row["source"], "sourceLabel": row["sourceLabel"],
                "company": row["company"],
                "status": short_status(row["status"]),
                "tone": status_tone(row["status"]),
                "date": row["date"] or "",
            }
            for row in latest
        ]

        completion_rate = round(completed * 100 / total, 1) if total else 0.0
        in_progress_rate = round(in_progress * 100 / total, 1) if total else 0.0
        report_total = sum(item['value'] for item in report_rows if item['label'] != '平台未提供')
        report_rate = round(filled_report * 100 / report_total, 1) if report_total else None

        return {
            "meta": meta(conn),
            "metrics": [
                {
                    "label": "质量计划总数",
                    "value": str(total),
                    "unit": "份质量计划",
                    "note": f"覆盖 {len(unit_rows)} 个机组号",
                    "icon": "document",
                    "tone": "cyan",
                },
                {
                    "label": "流程已完成",
                    "value": str(completed),
                    "unit": "份",
                    "note": f"按明确完成的记录统计 · 待确认 {unknown} 份" if unknown else f"完成率 {completion_rate}%",
                    "icon": "check",
                    "tone": "green",
                    "progress": completion_rate,
                },
                {
                    "label": "流程处理中",
                    "value": str(in_progress),
                    "unit": "份",
                    "note": f"{unknown} 份完成情况待确认" if unknown else f"{review} 审查/选点 · {drafting + auditing} 编制/审核",
                    "icon": "clock",
                    "tone": "orange",
                    "progress": in_progress_rate,
                },
                {
                    "label": "制造单位",
                    "value": str(company_count),
                    "unit": "家",
                    "note": top_company_note,
                    "icon": "building",
                    "tone": "blue",
                },
            ],
            "statusStats": status_stats,
            "companyStats": top_companies,
            "companyFootnote": f"其余 {max(company_count - 5, 0)} 家制造单位共 {others} 份",
            "reportingStats": reporting_stats,
            "reportingFilled": filled_report,
            "reportingRate": report_rate,
            "plans": plans,
            "unitStats": [
                {"label": item["label"], "value": item["value"], "color": COMPANY_COLORS[i % len(COMPANY_COLORS)]}
                for i, item in enumerate(unit_rows)
            ],
        }


def document_items(project="全部", group="全部", period="全部", status="全部", q="", report_level="", company="") -> list[dict]:
    where, params = build_filters(project, group, period, status, report_level=report_level, company=company)
    with closing(connect()) as conn:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(documents)')}
        def optional(names):
            return next((qident(n) for n in names if n in columns), "NULL")
        rows = conn.execute(
            f"""SELECT
              {qident('文件名称')} AS name, {qident('文件编号')} AS code,
              display_code AS displayCode, source_id AS source, source_label AS sourceLabel, raw_data AS rawData, completion_state AS completionState,
              {qident('文件版本')} AS version, {qident('所属项目')} AS project,
              {qident('制造单位')} AS company, {qident('流程状态')} AS status,
              {qident('版本状态')} AS versionStatus, {qident('创建时间')} AS createdAt,
              {qident('发起人')} AS initiator, {qident('文件类别')} AS category,
              {qident('适用机组号')} AS unit, {qident('核安全报送级别')} AS reportLevel,
              {qident('相关供方工作模式')} AS workMode, {qident('合同号')} AS contractNo,
              {optional(['内部编号', '内部文件编号'])} AS internalCode,
              NULLIF({optional(['最新审批流程时间', '最新审批时间'])}, '') AS latestApprovalAt,
              fetched_at AS fetchedAt, updated_at AS updatedAt
            FROM documents WHERE {where}
            ORDER BY {qident('创建时间')} DESC, {qident('文件编号')} DESC""", params).fetchall()
        items = [{**dict(row), 'statusShort': short_status(row['status']), 'tone': status_tone(row['status']), 'date': row['createdAt']} for row in rows]
    # Resolve against the full snapshot so filtering cannot turn an ambiguous name match into a unique one.
    if (project, group, period, status, report_level, company) != ('全部', '全部', '全部', '全部', '', ''):
        full = {r['code']: r for r in document_items()}
        for item in items:
            for key in ('internalCode', 'latestApprovalAt', 'internalCodeSource', 'latestApprovalSource'):
                item[key] = full.get(item['code'], {}).get(key)
    else:
        catalog.enrich_documents(items)
    if q.strip():
        needle = q.strip().casefold()
        items = [r for r in items if any(needle in str(r.get(k) or '').casefold() for k in ('name', 'code', 'displayCode', 'internalCode', 'company', 'initiator'))]
    return items


def get_documents(project, group, period, status, q, page, page_size, report_level='', company='') -> dict:
    items = document_items(project, group, period, status, q, report_level, company)
    page, page_size = max(1, page), min(max(1, page_size), 200)
    return {'total': len(items), 'page': page, 'pageSize': page_size, 'items': items[(page-1)*page_size:page*page_size]}


def get_trace(project, group, period, q='', code='', page=1, page_size=15, change_page=1) -> dict:
    rows = document_items(project, group, period, '处理中', q)
    visible = rows[(page-1)*page_size:page*page_size]
    selected = next((r for r in visible if r['code'] == code), None)
    where, params = build_filters(project, group, period)
    with closing(connect()) as conn:
        pipeline = [{'label': short_status(r['label']), 'value': r['value'], 'tone': status_tone(r['label']), 'color': STATUS_COLORS.get(short_status(r['label']), STATUS_COLORS['其他'])} for r in group_count(conn, '流程状态', where, params)]
        changes, change_count = [], 0
        if selected:
            change_count = conn.execute('SELECT COUNT(*) FROM document_changes WHERE "文件编号"=? AND source_id=?', [code, selected['source']]).fetchone()[0]
            changes = [dict(r) for r in conn.execute(
                'SELECT "文件编号" AS code, field_name AS fieldName, old_value AS oldValue, new_value AS newValue, changed_at AS changedAt, source_file AS sourceFile, source_id AS source, source_label AS sourceLabel, display_code AS displayCode FROM document_changes WHERE "文件编号"=? AND source_id=? ORDER BY changed_at DESC, id DESC LIMIT 30 OFFSET ?',
                [code, selected['source'], (change_page-1)*30])]
    return {'pipeline': pipeline, 'inProgress': visible, 'total': len(rows), 'page': page, 'pageSize': page_size, 'selectedCode': selected['code'] if selected else '', 'recentChanges': changes, 'changeTotal': change_count, 'changePage': change_page, 'changePageSize': 30}


def get_suppliers(project: str, group: str, period: str) -> dict:
    where, params = build_filters(project, group, period)
    with closing(connect()) as conn:
        companies = group_count(conn, "制造单位", where, params)
        modes = group_count(conn, "相关供方工作模式", where, params)
        levels = group_count(conn, "制造单位供方级别", where, params)
        ranking = [
            {
                "rank": index + 1,
                "label": short_company(item["label"]),
                "fullLabel": item["label"],
                "value": item["value"],
                "share": 0.0,
                "color": COMPANY_COLORS[index % len(COMPANY_COLORS)],
            }
            for index, item in enumerate(companies)
        ]
        total = sum(item["value"] for item in ranking) or 1
        for item in ranking:
            item["share"] = round(item["value"] * 100 / total, 1)
        return {
            "ranking": ranking,
            "workModes": [
                {
                    "label": item["label"],
                    "value": item["value"],
                    "color": COMPANY_COLORS[index % len(COMPANY_COLORS)],
                }
                for index, item in enumerate(modes)
            ],
            "supplierLevels": [
                {
                    "label": item["label"],
                    "value": item["value"],
                    "color": REPORT_COLORS[index % len(REPORT_COLORS)],
                }
                for index, item in enumerate(levels)
            ],
            "totalCompanies": len(companies),
            "totalPlans": total if companies else 0,
        }


def get_governance() -> dict:
    fields = [
        "文件名称",
        "文件编号",
        "制造单位",
        "流程状态",
        "创建时间",
        "发起人",
        "核安全报送级别",
        "合同号",
        "相关供方工作模式",
        "审查结论",
    ]
    with closing(connect()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] or 1
        fill_rates = []
        for field in fields:
            applicable = "source_id='ae'" if field in ('核安全报送级别','相关供方工作模式') else '1=1'
            eligible = conn.execute(f'SELECT COUNT(*) FROM documents WHERE {applicable}').fetchone()[0]
            actual_total = conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
            filled = conn.execute(
                f"SELECT COUNT(*) FROM documents WHERE {applicable} AND TRIM(COALESCE({qident(field)}, ''))!=''"
            ).fetchone()[0]
            fill_rates.append(
                {
                    "field": field,
                    "filled": int(filled),
                    "missing": int(eligible - filled), "notProvided": actual_total - eligible,
                    "rate": round(filled * 100 / eligible, 1) if eligible else None,
                }
            )
        batches = conn.execute(
            """
            SELECT sync_batch_id AS batchId, source_id AS source, source_label AS sourceLabel,
                   COUNT(*) AS changeCount,
                   COUNT(DISTINCT "文件编号") AS documentCount,
                   MIN(changed_at) AS startedAt,
                   MAX(changed_at) AS finishedAt
            FROM document_changes
            GROUP BY source_id, sync_batch_id
            ORDER BY MAX(id) DESC
            LIMIT 20
            """
        ).fetchall()
        recent = conn.execute(
            f"""
            SELECT
              {qident('文件编号')} AS code,
              source_id AS source, source_label AS sourceLabel, display_code AS displayCode,
              field_name AS fieldName,
              old_value AS oldValue,
              new_value AS newValue,
              changed_at AS changedAt,
              source_file AS sourceFile,
              sync_batch_id AS syncBatchId
            FROM document_changes
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()
        info = meta(conn)
        return {
            "meta": info,
            "fillRates": fill_rates,
            "syncBatches": [dict(row) for row in batches],
            "recentChanges": [dict(row) for row in recent],
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


def export_rows(project, group, period, status, q, report_level='', company='') -> list[dict]:
    return document_items(project, group, period, status, q, report_level, company)

#!/usr/bin/env python3
"""
Script chay logic cua FETCH_ENDPOINT_METRICS_DAG_KIBANA
Xuat ra file SQL INSERT cho tung ngay tu 2026-08-01 den 2026-09-21.

Cach chay:
    python3 scripts/export_endpoint_metrics_sql.py

Cau hinh bien moi truong hoac sua truc tiep:
    KIBANA_URL, KIBANA_USER, KIBANA_PASS
"""
from __future__ import annotations

import json
import os
import sys
import requests
from datetime import datetime, timedelta

KIBANA_URL = os.environ.get("KIBANA_URL", "http://10.120.54.62:9998")
KIBANA_USER = os.environ.get("KIBANA_USER", "fetek")
KIBANA_PASS = os.environ.get("KIBANA_PASS", "stl_fetek_dt2")

START_DATE = "2026-08-01"
END_DATE = "2026-09-21"

TABLE_NAME = "endpoint_metrics"

ENDPOINTS = [
    "/mobileservice/api/v3/auth/login",
    "/api/bccs/v1.0/partner/topup/payment",
    "/services/bccs/api/bccs/v1.0/partner/topup/payment",
    "/mobileservice/api/v3/transfer/lapnet/confirm",
    "/mobileservice/api/miniapp/transfer/lapnet/confirm",
    "/services/utilitiesconnector/api/v3/lapnet/transfer",
    "/mobileservice/api/v3/topup/confirm",
    "/mobileservice/api/miniapp/topup/confirm",
    "/mobileservice/api/v3/transfer/umoney/confirm",
    "/mobileservice/api/miniapp/transfer/umoney/confirm",
    "/mobileservice/api/v3/data/package/confirm",
    "/mobileservice/api/v3/partner/electricity/confirm",
    "/mobileservice/api/v3/internetPayment/confirm",
    "/mobileservice/api/v3/saleman/data/confirm",
    "/mobileservice/api/miniapp/saleman/data/confirm",
    "/mobileservice/api/v3/savings/validateOpenSavingsAccount",
    "/mobileservice/api/v3/savings/confirmOpenSavingAccount",
    "/mobileservice/api/v3/savings/settlementManual",
]

SERVICE_MAP = {
    "/mobileservice/api/v3/auth/login": "LOGIN",
    "/api/bccs/v1.0/partner/topup/payment": "TOPUP_PARTNER",
    "/services/bccs/api/bccs/v1.0/partner/topup/payment": "TOPUP_PARTNER",
    "/mobileservice/api/v3/transfer/lapnet/confirm": "W2BLAPNET",
    "/mobileservice/api/miniapp/transfer/lapnet/confirm": "W2BLAPNET",
    "/services/utilitiesconnector/api/v3/lapnet/transfer": "B2WLAPNET",
    "/mobileservice/api/v3/topup/confirm": "TOPUP_TELCO",
    "/mobileservice/api/miniapp/topup/confirm": "TOPUP_TELCO",
    "/mobileservice/api/v3/transfer/umoney/confirm": "TRANSFER_UMONEY",
    "/mobileservice/api/miniapp/transfer/umoney/confirm": "TRANSFER_UMONEY",
    "/mobileservice/api/v3/data/package/confirm": "DATA_UMONEY",
    "/mobileservice/api/v3/partner/electricity/confirm": "PAYMENT_ELECTRIC",
    "/mobileservice/api/v3/internetPayment/confirm": "PAYMENT_FTTH",
    "/mobileservice/api/v3/saleman/data/confirm": "SALEMAN_DATA",
    "/mobileservice/api/miniapp/saleman/data/confirm": "SALEMAN_DATA",
    "/mobileservice/api/v3/savings/validateOpenSavingsAccount": "SAVINGS_OPEN",
    "/mobileservice/api/v3/savings/confirmOpenSavingAccount": "SAVINGS_OPEN",
    "/mobileservice/api/v3/savings/settlementManual": "SAVINGS_SETTLEMENT",
}


def kibana_login(session: requests.Session) -> None:
    login_url = f"{KIBANA_URL}/internal/security/login"
    payload = {
        "providerType": "basic",
        "providerName": "basic",
        "currentURL": f"{KIBANA_URL}/login?next=%2Fapp%2Fdev_tools#/console",
        "params": {"username": KIBANA_USER, "password": KIBANA_PASS},
    }
    headers = {"kbn-version": "8.7.0", "Content-Type": "application/json"}
    resp = session.post(login_url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    print(f"[OK] Kibana login: {KIBANA_URL}")


def build_metrics_query(target_date: str) -> dict:
    next_date = (
        datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"direction.keyword": "Response"}},
                    {"terms": {"endpoint.keyword": ENDPOINTS}},
                    {"terms": {"code.keyword": ["200", "400", "500"]}},
                    {
                        "range": {
                            "@timestamp": {
                                "gte": target_date,
                                "lt": next_date,
                                "format": "yyyy-MM-dd",
                                "time_zone": "Asia/Ho_Chi_Minh",
                            }
                        }
                    },
                ]
            }
        },
        "aggs": {
            "by_endpoint": {
                "terms": {"field": "endpoint.keyword", "size": 100},
                "aggs": {
                    "success_count": {
                        "filter": {"term": {"code.keyword": "200"}}
                    },
                    "failure_count": {
                        "filter": {"term": {"code.keyword": "500"}}
                    },
                    "user_error_count": {
                        "filter": {"term": {"code.keyword": "400"}}
                    },
                    "duration_stats": {"stats": {"field": "executionTime"}},
                    "duration_percentiles": {
                        "percentiles": {
                            "field": "executionTime",
                            "percents": [95, 99],
                        }
                    },
                },
            }
        },
    }


def fetch_data(session: requests.Session, target_date: str) -> dict:
    index = f"logs-{target_date.replace('-', '.')}"
    proxy_url = f"{KIBANA_URL}/api/console/proxy"
    params = {"path": f"{index}/_search", "method": "GET"}
    headers = {"kbn-version": "8.7.0", "Content-Type": "application/json"}
    resp = session.post(
        proxy_url,
        params=params,
        headers=headers,
        json=build_metrics_query(target_date),
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def build_rows(data: dict, metric_date_value: str) -> list[tuple]:
    rows = []
    buckets = data.get("aggregations", {}).get("by_endpoint", {}).get("buckets", [])
    data_by_ep = {ep["key"]: ep for ep in buckets}

    for endpoint in ENDPOINTS:
        service_type = SERVICE_MAP.get(endpoint)
        ep = data_by_ep.get(endpoint)

        if ep is None:
            rows.append((
                metric_date_value, endpoint, 0, 0, 0, 0, 0.0,
                None, None, None, None, None, service_type,
            ))
            continue

        success = ep["success_count"]["doc_count"]
        failure = ep["failure_count"]["doc_count"]
        user_error = ep["user_error_count"]["doc_count"]
        total = success + failure
        success_rate = round(success / total * 100, 4) if total else 0.0
        stats = ep["duration_stats"]
        pcts = ep["duration_percentiles"]["values"]
        rows.append((
            metric_date_value,
            endpoint,
            total,
            success,
            failure,
            user_error,
            success_rate,
            stats.get("min"),
            stats.get("max"),
            round(stats["avg"], 2) if stats.get("avg") is not None else None,
            round(pcts["95.0"], 2) if pcts.get("95.0") is not None else None,
            round(pcts["99.0"], 2) if pcts.get("99.0") is not None else None,
            service_type,
        ))
    return rows


def fmt_val(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return f"'{v}'"
    return str(v)


def rows_to_sql(rows: list[tuple]) -> list[str]:
    lines = []
    for (
        metric_date, endpoint, total, success, failure, user_error,
        success_rate, min_d, max_d, avg_d, p95, p99, service_type,
    ) in rows:
        ep_escaped = endpoint.replace("'", "''")
        svc = f"'{service_type}'" if service_type else "NULL"
        lines.append(
            f"INSERT INTO {TABLE_NAME} ("
            f"METRIC_DATE, ENDPOINT, TOTAL_COUNT, SUCCESS_COUNT, FAILURE_COUNT, "
            f"USER_ERROR_COUNT, SUCCESS_RATE, MIN_DURATION_MS, MAX_DURATION_MS, "
            f"AVG_DURATION_MS, P95_DURATION_MS, P99_DURATION_MS, "
            f"COLLECTED_AT, SERVICE_TYPE"
            f") VALUES ("
            f"TO_DATE('{metric_date}', 'YYYY-MM-DD HH24:MI:SS'), "
            f"'{ep_escaped}', {total}, {success}, {failure}, "
            f"{user_error}, {success_rate}, {fmt_val(min_d)}, {fmt_val(max_d)}, "
            f"{fmt_val(avg_d)}, {fmt_val(p95)}, {fmt_val(p99)}, "
            f"SYSTIMESTAMP, {svc});"
        )
    return lines


def daterange(start: str, end: str) -> list[str]:
    """List ngay YYYY-MM-DD tu start den end (inclusive)."""
    dt_start = datetime.strptime(start, "%Y-%m-%d")
    dt_end = datetime.strptime(end, "%Y-%m-%d")
    days = []
    cur = dt_start
    while cur <= dt_end:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def main():
    output_file = f"endpoint_metrics_{START_DATE}_to_{END_DATE}.sql"

    session = requests.Session()
    kibana_login(session)

    days = daterange(START_DATE, END_DATE)
    print(f"[INFO] Query {len(days)} days: {START_DATE} -> {END_DATE}")

    all_sql: list[str] = []
    total_rows = 0

    for day in days:
        metric_date_value = f"{day} 00:00:00"
        print(f"  Fetching {day}...", end=" ", flush=True)
        try:
            data = fetch_data(session, day)
            rows = build_rows(data, metric_date_value)
            sql_lines = rows_to_sql(rows)
            all_sql.append(f"-- ===== {day} =====")
            all_sql.append(
                f"DELETE FROM {TABLE_NAME} "
                f"WHERE METRIC_DATE >= TO_DATE('{day}', 'YYYY-MM-DD') "
                f"AND METRIC_DATE < TO_DATE('{day}', 'YYYY-MM-DD') + 1;"
            )
            all_sql.extend(sql_lines)
            all_sql.append("")
            total_rows += len(rows)
            print(f"{len(rows)} rows")
        except Exception as e:
            print(f"ERROR: {e}")
            all_sql.append(f"-- ERROR fetching {day}: {e}")
            all_sql.append("")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"-- Endpoint metrics: {START_DATE} to {END_DATE}\n")
        f.write(f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"-- Total days: {len(days)}, Total rows: {total_rows}\n\n")
        f.write("\n".join(all_sql))
        f.write("\nCOMMIT;\n")

    print(f"\n[OK] Output: {output_file}")
    print(f"     Total days: {len(days)}")
    print(f"     Total rows: {total_rows}")


if __name__ == "__main__":
    main()

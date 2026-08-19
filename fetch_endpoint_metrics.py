#!/Users/dungvv/dev/fetek/unitel/superset_4.1.2/.venv/bin/python3
"""
Fetch endpoint metrics from Kibana/Elasticsearch every 15 minutes
and generate Oracle INSERT statements for endpoint_metrics table.

Run:
    /Users/dungvv/dev/fetek/unitel/superset_4.1.2/.venv/bin/python fetch_endpoint_metrics.py

Or use a process manager (systemd, supervisord, screen, etc.) to keep it alive.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from time import sleep

import requests
import schedule

# ---------------------------------------------------------------------------
# CONFIGURATION - edit these values or set environment variables
# ---------------------------------------------------------------------------
CONFIG = {
    "kibana_url": "http://10.120.54.62:9998",
    "username": os.environ.get("KIBANA_USER", "fetek"),
    "password": os.environ.get("KIBANA_PASS", "stl_fetek_dt2"),
    # Common Kibana login endpoints:
    #   - "/api/security/v1/login"            (basic form login)
    #   - "/internal/security/login"          (Kibana 8.x UI login)
    "login_endpoint": "/internal/security/login",
    "output_dir": "/Users/dungvv/dev/fetek/unitel/superset_4.1.2",
    "interval_minutes": 15,
    # True  -> query yesterday's index (useful when running after midnight)
    # False -> query today's index
    "use_yesterday": False,
    "endpoints": [
        "/mobileservice/api/v3/auth/login",
        "/umoney/api/v1/partner/view/check_account_info",
        "/umoney/api/v1/partner/topup",
        "/mobileservice/api/v3/lapnet/checkAccount",
        "/mobileservice/api/miniapp/lapnet/checkAccount",
        "/mobileservice/api/v3/transfer/lapnet/confirm",
        "/mobileservice/api/miniapp/transfer/lapnet/confirm",
        "/lapnet/inquiry",
        "/lapnet/transfer",
        "/mobileservice/api/v3/topup/check",
        "/mobileservice/api/miniapp/topup/check",
        "/mobileservice/api/v3/topup/confirm",
        "/mobileservice/api/miniapp/topup/confirm",
        "/mobileservice/api/v3/getFee",
        "/mobileservice/api/miniapp/getFee",
        "/mobileservice/api/v3/transfer/umoney/confirm",
        "/mobileservice/api/miniapp/transfer/umoney/confirm",
        "/mobileservice/api/v3/data/package/list",
        "/mobileservice/api/v3/data/package/detail",
        "/mobileservice/api/v3/data/package/confirm",
        "/mobileservice/api/v3/electricity/account/check",
        "/mobileservice/api/v3/partner/electricity/confirm",
        "/mobileservice/api/v3/internetPayment/check",
        "/mobileservice/api/v3/internetPayment/confirm",
        "/mobileservice/api/v3/saleman/data/getOtp",
        "/mobileservice/api/miniapp/saleman/data/getOtp",
        "/mobileservice/api/v3/saleman/data/confirm",
        "/mobileservice/api/miniapp/saleman/data/confirm",
        "/mobileservice/api/v3/savings/validateOpenSavingsAccount",
        "/mobileservice/api/v3/savings/confirmOpenSavingAccount",
        "/mobileservice/api/v3/savings/settlementManual",
    ],
    "service_map": {
        "/mobileservice/api/v3/auth/login": "LOGIN",
        "/umoney/api/v1/partner/view/check_account_info": "TOPUP_PARTNER",
        "/umoney/api/v1/partner/topup": "TOPUP_PARTNER",
        "/mobileservice/api/v3/lapnet/checkAccount": "W2BLAPNET",
        "/mobileservice/api/miniapp/lapnet/checkAccount": "W2BLAPNET",
        "/mobileservice/api/v3/transfer/lapnet/confirm": "W2BLAPNET",
        "/mobileservice/api/miniapp/transfer/lapnet/confirm": "W2BLAPNET",
        "/lapnet/inquiry": "B2WLAPNET",
        "/lapnet/transfer": "B2WLAPNET",
        "/mobileservice/api/v3/topup/check": "TOPUP_TELCO",
        "/mobileservice/api/miniapp/topup/check": "TOPUP_TELCO",
        "/mobileservice/api/v3/topup/confirm": "TOPUP_TELCO",
        "/mobileservice/api/miniapp/topup/confirm": "TOPUP_TELCO",
        "/mobileservice/api/v3/getFee": "TRANSFER_UMONEY",
        "/mobileservice/api/miniapp/getFee": "TRANSFER_UMONEY",
        "/mobileservice/api/v3/transfer/umoney/confirm": "TRANSFER_UMONEY",
        "/mobileservice/api/miniapp/transfer/umoney/confirm": "TRANSFER_UMONEY",
        "/mobileservice/api/v3/data/package/list": "DATA_UMONEY",
        "/mobileservice/api/v3/data/package/detail": "DATA_UMONEY",
        "/mobileservice/api/v3/data/package/confirm": "DATA_UMONEY",
        "/mobileservice/api/v3/electricity/account/check": "PAYMENT_ELECTRIC",
        "/mobileservice/api/v3/partner/electricity/confirm": "PAYMENT_ELECTRIC",
        "/mobileservice/api/v3/internetPayment/check": "PAYMENT_FTTH",
        "/mobileservice/api/v3/internetPayment/confirm": "PAYMENT_FTTH",
        "/mobileservice/api/v3/saleman/data/getOtp": "SALEMAN_DATA",
        "/mobileservice/api/miniapp/saleman/data/getOtp": "SALEMAN_DATA",
        "/mobileservice/api/v3/saleman/data/confirm": "SALEMAN_DATA",
        "/mobileservice/api/miniapp/saleman/data/confirm": "SALEMAN_DATA",
        "/mobileservice/api/v3/savings/validateOpenSavingsAccount": "SAVINGS_OPEN",
        "/mobileservice/api/v3/savings/confirmOpenSavingAccount": "SAVINGS_OPEN",
        "/mobileservice/api/v3/savings/settlementManual": "SAVINGS_SETTLEMENT",
    },
}

HEADERS_COMMON = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:153.0) Gecko/20100101 Firefox/153.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "kbn-version": "8.7.0",
    "x-kbn-context": json.dumps({
        "type": "application",
        "name": "dev_tools",
        "url": "/app/dev_tools",
        "page": "console",
    }),
}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _fmt(value):
    return "NULL" if value is None else str(value)


def login(session: requests.Session) -> None:
    """Authenticate to Kibana and store cookies in the session."""
    url = f"{CONFIG['kibana_url']}{CONFIG['login_endpoint']}"
    headers = {
        **HEADERS_COMMON,
        "Content-Type": "application/json",
        "Referer": f"{CONFIG['kibana_url']}/login?next=%2Fapp%2Fdev_tools",
        "Origin": CONFIG["kibana_url"],
        "x-kbn-context": json.dumps({
            "type": "application",
            "name": "security_login",
            "url": "/login",
        }),
    }
    payload = {
        "providerType": "basic",
        "providerName": "basic",
        "currentURL": f"{CONFIG['kibana_url']}/login?next=%2Fapp%2Fdev_tools#/console",
        "params": {
            "username": CONFIG["username"],
            "password": CONFIG["password"],
        },
    }

    resp = session.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    logging.info("Kibana login succeeded for user: %s", CONFIG["username"])


def build_search_body(target_date: str) -> dict:
    """Build the Elasticsearch aggregation query for a single day."""
    next_date = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"direction.keyword": "Response"}},
                    {"terms": {"endpoint.keyword": CONFIG["endpoints"]}},
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
                "terms": {
                    "field": "endpoint.keyword",
                    "size": 100,
                },
                "aggs": {
                    "by_day": {
                        "date_histogram": {
                            "field": "@timestamp",
                            "calendar_interval": "day",
                            "time_zone": "Asia/Ho_Chi_Minh",
                            "min_doc_count": 0,
                            "extended_bounds": {
                                "min": target_date,
                                "max": next_date,
                            },
                        },
                        "aggs": {
                            "success_count": {
                                "filter": {"term": {"code.keyword": "200"}}
                            },
                            "failure_count": {
                                "filter": {
                                    "bool": {
                                        "must_not": {"term": {"code.keyword": "200"}}
                                    }
                                }
                            },
                            "duration_stats": {
                                "stats": {"field": "executionTime"}
                            },
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
        },
    }


def fetch_data(session: requests.Session, target_date: str) -> dict:
    """Call Kibana console proxy to run the aggregation search."""
    index_name = f"logs-{target_date.replace('-', '.')}"
    url = f"{CONFIG['kibana_url']}/api/console/proxy"
    params = {"path": f"{index_name}/_search", "method": "GET"}
    headers = {
        **HEADERS_COMMON,
        "Content-Type": "application/json",
        "Referer": f"{CONFIG['kibana_url']}/app/dev_tools",
        "Origin": CONFIG["kibana_url"],
    }
    body = build_search_body(target_date)

    resp = session.post(url, params=params, headers=headers, json=body, timeout=120)
    resp.raise_for_status()
    return resp.json()


def generate_sql(data: dict, target_date: str) -> str:
    """Convert aggregation JSON into Oracle INSERT statements."""
    inserts = []
    by_endpoint = data.get("aggregations", {}).get("by_endpoint", {}).get("buckets", [])

    for endpoint_bucket in by_endpoint:
        endpoint = endpoint_bucket["key"]
        service_type = CONFIG["service_map"].get(endpoint)

        for day in endpoint_bucket.get("by_day", {}).get("buckets", []):
            total = day["doc_count"]
            if total == 0:
                continue

            date_str = day["key_as_string"].split("T")[0]
            success = day["success_count"]["doc_count"]
            failure = day["failure_count"]["doc_count"]
            success_rate = round(success / total * 100, 4) if total else None

            stats = day["duration_stats"]
            percentiles = day["duration_percentiles"]["values"]

            min_d = stats.get("min")
            max_d = stats.get("max")
            avg_d = round(stats["avg"], 2) if stats.get("avg") is not None else None
            p95 = round(percentiles["95.0"], 2) if percentiles.get("95.0") is not None else None
            p99 = round(percentiles["99.0"], 2) if percentiles.get("99.0") is not None else None

            service_val = f"'{service_type}'" if service_type else "NULL"
            sql = f"""INSERT INTO endpoint_metrics (
    METRIC_DATE, ENDPOINT, TOTAL_COUNT, SUCCESS_COUNT, FAILURE_COUNT,
    SUCCESS_RATE, MIN_DURATION_MS, MAX_DURATION_MS, AVG_DURATION_MS,
    P95_DURATION_MS, P99_DURATION_MS, COLLECTED_AT, SERVICE_TYPE
) VALUES (
    DATE '{date_str}', '{endpoint.replace("'", "''")}', {total}, {success}, {failure},
    {_fmt(success_rate)}, {_fmt(min_d)}, {_fmt(max_d)}, {_fmt(avg_d)},
    {_fmt(p95)}, {_fmt(p99)}, SYSTIMESTAMP, {service_val}
);"""
            inserts.append(sql)

    return "\n\n".join(inserts)


def get_target_date() -> str:
    """Return the regular date to query based on configuration."""
    now = datetime.now()
    if CONFIG["use_yesterday"]:
        now -= timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def get_today() -> str:
    """Return today's date."""
    return datetime.now().strftime("%Y-%m-%d")


def get_state_file_path() -> str:
    return os.path.join(CONFIG["output_dir"], ".fetch_endpoint_metrics_last_run")


def read_last_run_date() -> str | None:
    """Read the last run date from state file, if any."""
    path = get_state_file_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except Exception:
        return None


def write_last_run_date(date_str: str) -> None:
    """Persist the last run date to state file."""
    path = get_state_file_path()
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(date_str)


def save_sql(sql: str, target_date: str) -> str:
    """Write generated SQL to a daily file."""
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    suffix = target_date.replace("-", "")
    path = os.path.join(CONFIG["output_dir"], f"endpoint_metrics_insert_{suffix}.sql")
    with open(path, "w", encoding="utf-8") as f:
        f.write(sql)
    return path


def run_for_date(target_date: str) -> None:
    """Login, fetch and generate SQL for a single date."""
    logging.info("Running job for date: %s", target_date)

    if not CONFIG["username"] or not CONFIG["password"]:
        logging.error("KIBANA_USER and KIBANA_PASS must be set in CONFIG or environment variables")
        return

    session = requests.Session()
    try:
        login(session)
        data = fetch_data(session, target_date)
        sql = generate_sql(data, target_date)
        path = save_sql(sql, target_date)
        logging.info("Generated %d INSERT statements -> %s", sql.count("INSERT INTO"), path)
    except requests.exceptions.RequestException as exc:
        logging.error("Network/API error: %s", exc)
    except Exception as exc:
        logging.exception("Unexpected error: %s", exc)


# ---------------------------------------------------------------------------
# MAIN JOB
# ---------------------------------------------------------------------------
def job() -> None:
    today = get_today()
    primary_date = get_target_date()
    last_run_date = read_last_run_date()

    if last_run_date != today:
        # First run of the day: process both N-1 and N.
        secondary_date = today if CONFIG["use_yesterday"] else (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)
        ).strftime("%Y-%m-%d")

        logging.info("First run of the day (last_run=%s, today=%s). Processing %s and %s.",
                     last_run_date, today, primary_date, secondary_date)

        run_for_date(primary_date)
        run_for_date(secondary_date)

        write_last_run_date(today)
    else:
        # Subsequent runs: process the regular date only.
        run_for_date(primary_date)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    schedule.every(CONFIG["interval_minutes"]).minutes.do(job)
    logging.info("Scheduler started. Running every %d minutes.", CONFIG["interval_minutes"])

    # Run immediately on startup
    job()

    while True:
        schedule.run_pending()
        sleep(60)


if __name__ == "__main__":
    main()

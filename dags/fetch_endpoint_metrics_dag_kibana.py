"""DAG 13 phút — endpoint metrics Kibana → Oracle.

Nguồn: Kibana API proxy (logs-YYYY.MM.DD)
Đích:  endpoint_metrics (conn=oracle_default)

Mỗi lần chạy (không sensor dependency):
  1) Xóa METRIC_DATE thuộc hôm qua VÀ hôm nay (Asia/Ho_Chi_Minh)
  2) Tính KPI 2 ngày (hôm qua + hôm nay) → INSERT lại

METRIC_DATE:
  - Ngày N-1: YYYY-MM-DD 00:00:00 (số liệu ngày đã chốt)
  - Ngày N:   YYYY-MM-DD HH24:MI:SS theo thời điểm run (near-realtime)

Lịch: */13 (Asia/Ho_Chi_Minh)
Conf (optional): data_dates = "YYYY-MM-DD,YYYY-MM-DD" — override list ngày load
"""
from __future__ import annotations


import logging
import requests
from datetime import datetime, timedelta


import common.utils as utils
import pendulum
from airflow import DAG
from airflow.models import Variable
from airflow.operators.dummy_operator import DummyOperator
from airflow.operators.python_operator import PythonOperator
from airflow.providers.oracle.hooks.oracle import OracleHook
from airflow.utils.task_group import TaskGroup


logger = logging.getLogger(__name__)


vn_tz = pendulum.timezone("Asia/Ho_Chi_Minh")
DATE_FMT = "YYYY-MM-DD"


KIBANA_URL = Variable.get("kibana_url", default_var="http://10.120.54.62:9998")
KIBANA_USER = Variable.get("kibana_user", default_var="fetek")
KIBANA_PASS = Variable.get("kibana_pass", default_var="stl_fetek_dt2")
ORACLE_CONN_ID = Variable.get("oracle_conn_id", default_var="dwh_oracle")


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




def generate_info_endpoint_metrics(**kwargs) -> None:
    """
    Mặc định load **hôm qua + hôm nay** (Asia/Ho_Chi_Minh).


    Conf:
      data_dates: "2026-08-05,2026-08-06" — list ngày METRIC_DATE (CSV)
      data_date:  1 ngày — chỉ load ngày đó
    """
    ti = kwargs["ti"]
    dag_run = kwargs.get("dag_run")
    conf = (dag_run.conf or {}) if dag_run else {}


    if conf.get("data_dates"):
        days = [
            pendulum.from_format(d.strip(), DATE_FMT, tz=vn_tz).start_of("day")
            for d in str(conf["data_dates"]).split(",")
            if d.strip()
        ]
        if not days:
            raise ValueError("conf data_dates rỗng.")
    elif conf.get("data_date"):
        days = [
            pendulum.from_format(
                str(conf["data_date"]).strip(), DATE_FMT, tz=vn_tz
            ).start_of("day")
        ]
    else:
        today = pendulum.now(vn_tz).start_of("day")
        days = [today.subtract(days=1), today]


    days = sorted({d.start_of("day") for d in days}, key=lambda x: x.int_timestamp)
    day_labels = [d.format(DATE_FMT) for d in days]
    run_at = pendulum.now(vn_tz)


    ti.xcom_push(key="start_time", value=run_at.strftime("%Y-%m-%d %H:%M:%S"))
    ti.xcom_push(key="run_at", value=run_at.strftime("%Y-%m-%d %H:%M:%S"))
    ti.xcom_push(key="today", value=run_at.format(DATE_FMT))
    ti.xcom_push(key="metric_dates", value=",".join(day_labels))
    ti.xcom_push(key="pre_date", value=day_labels[0])
    ti.xcom_push(key="execution_date", value=day_labels[-1])
    print(
        f"generate_info_endpoint_metrics: METRIC_DATE load={day_labels} "
        f"(delete+insert mỗi ngày)"
    )




def _kibana_login(session: requests.Session) -> None:
    """Login vào Kibana để lấy session cookie."""
    login_url = f"{KIBANA_URL}/internal/security/login"
    payload = {
        "providerType": "basic",
        "providerName": "basic",
        "currentURL": f"{KIBANA_URL}/login?next=%2Fapp%2Fdev_tools#/console",
        "params": {
            "username": KIBANA_USER,
            "password": KIBANA_PASS,
        },
    }
    headers = {
        "kbn-version": "8.7.0",
        "Content-Type": "application/json",
    }
    response = session.post(login_url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    logger.info("Kibana login successful")




def _build_metrics_query(target_date: str) -> dict:
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




def _fetch_data(session: requests.Session, target_date: str) -> dict:
    """Gọi Kibana API proxy để query Elasticsearch."""
    index = f"logs-{target_date.replace('-', '.')}"
    proxy_url = f"{KIBANA_URL}/api/console/proxy"
    params = {
        "path": f"{index}/_search",
        "method": "GET",
    }
    headers = {
        "kbn-version": "8.7.0",
        "Content-Type": "application/json",
    }
    query_body = _build_metrics_query(target_date)
    
    response = session.post(
        proxy_url,
        params=params,
        headers=headers,
        json=query_body,
        timeout=120,
    )
    response.raise_for_status()
    return response.json()




def _build_insert_rows(data: dict, metric_date_value: str) -> list[tuple]:
    """
    Build row tuples cho bulk insert.

    metric_date_value:
      - N-1 / ngày lịch sử: YYYY-MM-DD 00:00:00
      - ngày N hiện tại:    thời điểm run YYYY-MM-DD HH24:MI:SS

    Nếu endpoint không có data (hit=0), vẫn insert với total/success/failure = 0.
    total_count = success_count + failure_count (không tính user_error)
    """
    rows = []
    buckets = data.get("aggregations", {}).get("by_endpoint", {}).get("buckets", [])
    data_by_endpoint = {ep["key"]: ep for ep in buckets}

    for endpoint in ENDPOINTS:
        service_type = SERVICE_MAP.get(endpoint)
        ep_bucket = data_by_endpoint.get(endpoint)

        if ep_bucket is None:
            rows.append((
                metric_date_value,
                endpoint,
                0,
                0,
                0,
                0,
                0.0,
                None,
                None,
                None,
                None,
                None,
                service_type,
            ))
            continue

        success = ep_bucket["success_count"]["doc_count"]
        failure = ep_bucket["failure_count"]["doc_count"]
        user_error = ep_bucket["user_error_count"]["doc_count"]
        total = success + failure
        success_rate = round(success / total * 100, 4) if total else 0.0
        stats = ep_bucket["duration_stats"]
        pcts = ep_bucket["duration_percentiles"]["values"]
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




def _metric_date_value(day_label: str, today: str, run_at: str) -> str:
    return run_at if day_label == today else f"{day_label} 00:00:00"




def _delete_and_insert(dest_table_name: str, days: list[str], rows_by_day: dict[str, list[tuple]]) -> int:
    hook = OracleHook(oracle_conn_id=ORACLE_CONN_ID)
    conn = hook.get_conn()
    try:
        cursor = conn.cursor()
        total_deleted = 0
        for d in days:
            cursor.execute(
                f"DELETE FROM {dest_table_name} "
                "WHERE METRIC_DATE >= TO_DATE(:d, 'YYYY-MM-DD') "
                "AND METRIC_DATE < TO_DATE(:d, 'YYYY-MM-DD') + 1",
                {"d": d},
            )
            total_deleted += cursor.rowcount or 0
            print(f"DELETE METRIC_DATE={d}, rows={cursor.rowcount}")

        total_inserted = 0
        for day_label, rows in rows_by_day.items():
            if rows:
                cursor.executemany(
                    f"""INSERT INTO {dest_table_name} (
                        METRIC_DATE, ENDPOINT, TOTAL_COUNT, SUCCESS_COUNT, FAILURE_COUNT,
                        USER_ERROR_COUNT, SUCCESS_RATE, MIN_DURATION_MS, MAX_DURATION_MS,
                        AVG_DURATION_MS, P95_DURATION_MS, P99_DURATION_MS,
                        COLLECTED_AT, SERVICE_TYPE
                    ) VALUES (
                        TO_DATE(:0, 'YYYY-MM-DD HH24:MI:SS'), :1, :2, :3, :4,
                        :5, :6, :7, :8, :9,
                        :10, :11, SYSTIMESTAMP, :12
                    )""",
                    rows,
                )
            total_inserted += len(rows)
            print(f"INSERT day={day_label}, rows={len(rows)}")

        conn.commit()
        print(f"COMMIT: deleted={total_deleted}, inserted={total_inserted}")
        return total_inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()




default_args = {
    "owner": "NamND FETEK",
    "depends_on_past": False,
    "start_date": pendulum.datetime(2026, 8, 19, tz=vn_tz),
    "retries": 2,
    "retry_delay": pendulum.duration(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": pendulum.duration(minutes=13),
    "on_failure_callback": utils.failure_callback,
}




with DAG(
    dag_id="FETCH_ENDPOINT_METRICS_DAG_KIBANA",
    default_args=default_args,
    description=(
        "Kibana API endpoint metrics → endpoint_metrics "
        "mỗi 13' — xóa+ghi hôm qua & hôm nay (không dependency)"
    ),
    schedule_interval="*/13 * * * *",
    concurrency=5,
    max_active_runs=1,
    tags=["kibana", "oracle", "metrics", "endpoint_metrics"],
    catchup=False,
) as dag:


    dest_conn_id = ORACLE_CONN_ID
    dest_table_name = "endpoint_metrics"


    start_task = DummyOperator(task_id="start_task")


    generate_info_task = PythonOperator(
        task_id="generate_info",
        python_callable=generate_info_endpoint_metrics,
    )


    with TaskGroup("sync_fact_append_taskgroup", dag=dag) as sync_fact_append_taskgroup:


        def delete_today_and_yesterday(**kwargs):
            """Xóa toàn bộ METRIC_DATE thuộc các ngày cần reload."""
            ti = kwargs["ti"]
            raw = ti.xcom_pull(task_ids="generate_info", key="metric_dates")
            if not raw:
                raise ValueError("generate_info phải có metric_dates.")
            days = [d.strip() for d in str(raw).split(",") if d.strip()]
            sql = (
                f"DELETE FROM {dest_table_name} "
                "WHERE METRIC_DATE >= TO_DATE(:d, 'YYYY-MM-DD') "
                "AND METRIC_DATE < TO_DATE(:d, 'YYYY-MM-DD') + 1"
            )
            hook = OracleHook(oracle_conn_id=dest_conn_id)
            conn = hook.get_conn()
            try:
                cursor = conn.cursor()
                total = 0
                for d in days:
                    cursor.execute(sql, {"d": d})
                    total += cursor.rowcount or 0
                    print(f"delete METRIC_DATE={d}, rows={cursor.rowcount}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            print(f"delete_today_and_yesterday: days={days}, deleted={total}")


        def fetch_and_insert_all_days(**kwargs):
            """Query Kibana API từng ngày trong metric_dates rồi INSERT vào Oracle."""
            ti = kwargs["ti"]
            raw = ti.xcom_pull(task_ids="generate_info", key="metric_dates")
            today = ti.xcom_pull(task_ids="generate_info", key="today")
            run_at = ti.xcom_pull(task_ids="generate_info", key="run_at")
            if not raw or not today or not run_at:
                raise ValueError("generate_info phải có metric_dates / today / run_at.")


            days = [d.strip() for d in str(raw).split(",") if d.strip()]
            
            # Tạo session và login Kibana
            session = requests.Session()
            _kibana_login(session)
            
            rows_by_day = {}
            for day_label in days:
                metric_date_value = _metric_date_value(day_label, today, run_at)
                data = _fetch_data(session, day_label)
                rows = _build_insert_rows(data, metric_date_value)
                rows_by_day[day_label] = rows
                print(
                    f"fetch: day={day_label}, "
                    f"METRIC_DATE={metric_date_value}, rows={len(rows)}"
                )
            
            _delete_and_insert(dest_table_name, days, rows_by_day)


        delete_task = PythonOperator(
            task_id="delete_today_and_yesterday",
            python_callable=delete_today_and_yesterday,
            execution_timeout=timedelta(minutes=10),
        )


        fetch_and_insert_task = PythonOperator(
            task_id="fetch_and_insert",
            python_callable=fetch_and_insert_all_days,
            execution_timeout=timedelta(minutes=30),
        )


        delete_task >> fetch_and_insert_task


    (
        start_task
        >> generate_info_task
        >> sync_fact_append_taskgroup
    )

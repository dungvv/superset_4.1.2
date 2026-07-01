BEGIN;

CREATE SCHEMA IF NOT EXISTS "DWH_APP";

CREATE TABLE IF NOT EXISTS "DWH_APP"."IPCC_UNITEL_UMONEY_ANSWER_CALL_GT20S_DAILY" (
  "START_DATE" date NOT NULL,
  "ANSWER_CALL_COUNT" numeric(18, 0) NOT NULL,
  "TOTAL_CALL" numeric(18, 0)
);

CREATE TABLE IF NOT EXISTS "DWH_APP"."UNITEL_SURVEY_DASHBOARD_DAILY" (
  "KENH" varchar(20) NOT NULL,
  "NGAY" date NOT NULL,
  "TONG_KH_DANH_GIA" numeric(19, 0),
  "TONG_KH_HAI_LONG" numeric(19, 0),
  "TY_LE_HAI_LONG_PCT" numeric(10, 2)
);

CREATE TABLE IF NOT EXISTS "DWH_APP"."CC_PAKN_UMONEY_BO_IN_SLA" (
  "STAT_DATE" date NOT NULL,
  "PAKN_COUNT" numeric(18, 0) NOT NULL,
  "TOTAL_PAKN" numeric(18, 0)
);

CREATE TABLE IF NOT EXISTS "DWH_APP"."IPCC_UNITEL_UMONEY_SERVICE_LEVEL_168" (
  "STAT_DATE" date NOT NULL,
  "AVG_ANSWER_TIME" numeric(18, 2) NOT NULL,
  "AVG_WAITING_TIME" numeric(18, 2) NOT NULL,
  "TOTALREALDEMAND" numeric(18, 0) NOT NULL,
  "TOTALANSWERED" numeric(18, 0) NOT NULL
);

CREATE TABLE IF NOT EXISTS "DWH_APP"."IPCC_UNITEL_UMONEY_DTV_HANDLED_CALL" (
  "STAT_DATE" date NOT NULL,
  "SUCCESS_HANDLED_CALL_COUNT" numeric(18, 0) NOT NULL,
  "TOTALREALDEMAND" numeric(18, 0) NOT NULL
);

CREATE TABLE IF NOT EXISTS "DWH_APP"."CC_PROBLEM_LIST_BO_DAILY" (
  "STAT_DATE" date,
  "BO_LIST_COUNT" numeric(18, 0),
  "STATUS_FILTER_LIST_COUNT" numeric(18, 0),
  "ON_SITE_PROBLEM_COUNT" numeric(18, 0)
);

WITH metrics AS (
  SELECT
    d::date AS stat_date,
    (d::date - DATE '2026-04-01')::int AS n,
    EXTRACT(isodow FROM d)::int AS dow
  FROM generate_series(DATE '2026-04-01', DATE '2026-05-21', INTERVAL '1 day') AS d
),
rows AS (
  SELECT
    stat_date,
    n,
    (920 + (n % 17) * 18 + CASE WHEN dow IN (6, 7) THEN -95 ELSE 0 END)::numeric(18, 0) AS total_call
  FROM metrics
)
INSERT INTO "DWH_APP"."IPCC_UNITEL_UMONEY_ANSWER_CALL_GT20S_DAILY" (
  "START_DATE",
  "ANSWER_CALL_COUNT",
  "TOTAL_CALL"
)
SELECT
  stat_date,
  floor(total_call * (0.82 + ((n % 9)::numeric / 100)))::numeric(18, 0),
  total_call
FROM rows
WHERE NOT EXISTS (
  SELECT 1
  FROM "DWH_APP"."IPCC_UNITEL_UMONEY_ANSWER_CALL_GT20S_DAILY" existing
  WHERE existing."START_DATE" = rows.stat_date
);

WITH metrics AS (
  SELECT
    d::date AS stat_date,
    (d::date - DATE '2026-04-01')::int AS n,
    EXTRACT(isodow FROM d)::int AS dow
  FROM generate_series(DATE '2026-04-01', DATE '2026-05-21', INTERVAL '1 day') AS d
),
channels AS (
  SELECT *
  FROM (VALUES
    ('APP'::varchar(20), 0),
    ('USSD'::varchar(20), 16),
    ('CALL_CENTER'::varchar(20), 28),
    ('BRANCH'::varchar(20), 44)
  ) AS channel("KENH", offset_value)
),
rows AS (
  SELECT
    channels."KENH",
    metrics.stat_date,
    (155 + channels.offset_value + (metrics.n % 12) * 7 + CASE WHEN metrics.dow IN (6, 7) THEN -20 ELSE 0 END)::numeric(19, 0) AS total_reviews,
    (0.86 + ((metrics.n + channels.offset_value) % 7)::numeric / 100) AS satisfaction_rate
  FROM metrics
  CROSS JOIN channels
)
INSERT INTO "DWH_APP"."UNITEL_SURVEY_DASHBOARD_DAILY" (
  "KENH",
  "NGAY",
  "TONG_KH_DANH_GIA",
  "TONG_KH_HAI_LONG",
  "TY_LE_HAI_LONG_PCT"
)
SELECT
  "KENH",
  stat_date,
  total_reviews,
  floor(total_reviews * satisfaction_rate)::numeric(19, 0),
  round((floor(total_reviews * satisfaction_rate) * 100.0 / total_reviews)::numeric, 2)::numeric(10, 2)
FROM rows
WHERE NOT EXISTS (
  SELECT 1
  FROM "DWH_APP"."UNITEL_SURVEY_DASHBOARD_DAILY" existing
  WHERE existing."NGAY" = rows.stat_date
    AND existing."KENH" = rows."KENH"
);

WITH metrics AS (
  SELECT
    d::date AS stat_date,
    (d::date - DATE '2026-04-01')::int AS n,
    EXTRACT(isodow FROM d)::int AS dow
  FROM generate_series(DATE '2026-04-01', DATE '2026-05-21', INTERVAL '1 day') AS d
),
rows AS (
  SELECT
    stat_date,
    n,
    (78 + (n % 14) * 4 + CASE WHEN dow IN (6, 7) THEN -12 ELSE 0 END)::numeric(18, 0) AS total_pakn
  FROM metrics
)
INSERT INTO "DWH_APP"."CC_PAKN_UMONEY_BO_IN_SLA" (
  "STAT_DATE",
  "PAKN_COUNT",
  "TOTAL_PAKN"
)
SELECT
  stat_date,
  floor(total_pakn * (0.88 + (n % 6)::numeric / 100))::numeric(18, 0),
  total_pakn
FROM rows
WHERE NOT EXISTS (
  SELECT 1
  FROM "DWH_APP"."CC_PAKN_UMONEY_BO_IN_SLA" existing
  WHERE existing."STAT_DATE" = rows.stat_date
);

WITH metrics AS (
  SELECT
    d::date AS stat_date,
    (d::date - DATE '2026-04-01')::int AS n,
    EXTRACT(isodow FROM d)::int AS dow
  FROM generate_series(DATE '2026-04-01', DATE '2026-05-21', INTERVAL '1 day') AS d
),
rows AS (
  SELECT
    stat_date,
    n,
    (1180 + (n % 20) * 22 + CASE WHEN dow IN (6, 7) THEN -150 ELSE 0 END)::numeric(18, 0) AS total_demand
  FROM metrics
)
INSERT INTO "DWH_APP"."IPCC_UNITEL_UMONEY_SERVICE_LEVEL_168" (
  "STAT_DATE",
  "AVG_ANSWER_TIME",
  "AVG_WAITING_TIME",
  "TOTALREALDEMAND",
  "TOTALANSWERED"
)
SELECT
  stat_date,
  round((14.5 + (n % 8) * 0.65)::numeric, 2)::numeric(18, 2),
  round((24.0 + (n % 10) * 1.15)::numeric, 2)::numeric(18, 2),
  total_demand,
  floor(total_demand * (0.84 + (n % 8)::numeric / 100))::numeric(18, 0)
FROM rows
WHERE NOT EXISTS (
  SELECT 1
  FROM "DWH_APP"."IPCC_UNITEL_UMONEY_SERVICE_LEVEL_168" existing
  WHERE existing."STAT_DATE" = rows.stat_date
);

WITH metrics AS (
  SELECT
    d::date AS stat_date,
    (d::date - DATE '2026-04-01')::int AS n,
    EXTRACT(isodow FROM d)::int AS dow
  FROM generate_series(DATE '2026-04-01', DATE '2026-05-21', INTERVAL '1 day') AS d
),
rows AS (
  SELECT
    stat_date,
    n,
    (1040 + (n % 18) * 24 + CASE WHEN dow IN (6, 7) THEN -130 ELSE 0 END)::numeric(18, 0) AS total_demand
  FROM metrics
)
INSERT INTO "DWH_APP"."IPCC_UNITEL_UMONEY_DTV_HANDLED_CALL" (
  "STAT_DATE",
  "SUCCESS_HANDLED_CALL_COUNT",
  "TOTALREALDEMAND"
)
SELECT
  stat_date,
  floor(total_demand * (0.79 + (n % 10)::numeric / 100))::numeric(18, 0),
  total_demand
FROM rows
WHERE NOT EXISTS (
  SELECT 1
  FROM "DWH_APP"."IPCC_UNITEL_UMONEY_DTV_HANDLED_CALL" existing
  WHERE existing."STAT_DATE" = rows.stat_date
);

WITH metrics AS (
  SELECT
    d::date AS stat_date,
    (d::date - DATE '2026-04-01')::int AS n,
    EXTRACT(isodow FROM d)::int AS dow
  FROM generate_series(DATE '2026-04-01', DATE '2026-05-21', INTERVAL '1 day') AS d
),
rows AS (
  SELECT
    stat_date,
    (62 + (n % 11) * 5 + CASE WHEN dow IN (6, 7) THEN -9 ELSE 0 END)::numeric(18, 0) AS bo_list_count,
    (42 + (n % 9) * 4 + CASE WHEN dow IN (6, 7) THEN -7 ELSE 0 END)::numeric(18, 0) AS status_filter_list_count,
    (9 + (n % 5) * 2 + CASE WHEN dow IN (6, 7) THEN -2 ELSE 0 END)::numeric(18, 0) AS on_site_problem_count
  FROM metrics
)
INSERT INTO "DWH_APP"."CC_PROBLEM_LIST_BO_DAILY" (
  "STAT_DATE",
  "BO_LIST_COUNT",
  "STATUS_FILTER_LIST_COUNT",
  "ON_SITE_PROBLEM_COUNT"
)
SELECT
  stat_date,
  bo_list_count,
  status_filter_list_count,
  on_site_problem_count
FROM rows
WHERE NOT EXISTS (
  SELECT 1
  FROM "DWH_APP"."CC_PROBLEM_LIST_BO_DAILY" existing
  WHERE existing."STAT_DATE" = rows.stat_date
);

COMMIT;

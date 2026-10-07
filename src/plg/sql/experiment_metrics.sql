-- One row per enrolled user with experiment outcomes and the pre-period covariate.
--   activated_{n}d : reached the activation event within $activation_days of assignment
--   paid_{n}d      : subscribed within $paid_days of assignment
--   active_days    : distinct active days on days 1..$active_days_window after signup
--   pre_pageviews  : marketing pageviews in the 14 days before assignment (CUPED covariate)
WITH enrolled AS (
    SELECT a.user_id, a.variant, a.assigned_ts, CAST(u.signup_ts AS DATE) AS signup_date
    FROM assignments AS a
    JOIN users AS u USING (user_id)
    WHERE a.experiment = $experiment
),
activation AS (
    SELECT DISTINCT n.user_id
    FROM enrolled AS n
    JOIN events AS e USING (user_id)
    WHERE e.event_name = $activation_event
      AND e.event_ts >= n.assigned_ts
      AND e.event_ts <= n.assigned_ts + to_days(CAST($activation_days AS INTEGER))
),
paid AS (
    SELECT DISTINCT n.user_id
    FROM enrolled AS n
    JOIN events AS e USING (user_id)
    WHERE e.event_name = $paid_event
      AND e.event_ts >= n.assigned_ts
      AND e.event_ts <= n.assigned_ts + to_days(CAST($paid_days AS INTEGER))
),
active AS (
    SELECT n.user_id, count(DISTINCT CAST(e.event_ts AS DATE)) AS active_days
    FROM enrolled AS n
    JOIN events AS e USING (user_id)
    WHERE e.event_name = $activity_event
      AND date_diff('day', n.signup_date, CAST(e.event_ts AS DATE))
          BETWEEN 1 AND $active_days_window
    GROUP BY ALL
),
covariate AS (
    SELECT n.user_id, count(*) AS pre_pageviews
    FROM enrolled AS n
    JOIN events AS e USING (user_id)
    WHERE e.event_name = $covariate_event
      AND e.event_ts < n.assigned_ts
      AND e.event_ts >= n.assigned_ts - INTERVAL 14 DAY
    GROUP BY ALL
)
SELECT
    n.user_id,
    n.variant,
    n.assigned_ts,
    CAST(act.user_id IS NOT NULL AS INTEGER) AS activated,
    CAST(p.user_id IS NOT NULL AS INTEGER) AS paid,
    coalesce(ad.active_days, 0) AS active_days,
    coalesce(c.pre_pageviews, 0) AS pre_pageviews
FROM enrolled AS n
LEFT JOIN activation AS act USING (user_id)
LEFT JOIN paid AS p USING (user_id)
LEFT JOIN active AS ad USING (user_id)
LEFT JOIN covariate AS c USING (user_id)
ORDER BY n.assigned_ts, n.user_id

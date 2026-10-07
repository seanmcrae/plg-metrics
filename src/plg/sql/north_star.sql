-- North-star metric: Weekly Engaged Activated Users (WEAU), users who had reached
-- the activation event by the end of the week and were active on at least
-- $min_active_days distinct days in that calendar week. Complete weeks only.
WITH activity AS (
    SELECT DISTINCT user_id, CAST(event_ts AS DATE) AS activity_date
    FROM events
    WHERE event_name = $activity_event AND event_ts < $observation_end
),
weekly AS (
    SELECT
        user_id,
        CAST(date_trunc('week', activity_date) AS DATE) AS week,
        count(*) AS active_days
    FROM activity
    GROUP BY ALL
),
activation AS (
    SELECT user_id, min(event_ts) AS activated_ts
    FROM events
    WHERE event_name = $activation_event
    GROUP BY ALL
)
SELECT
    w.week,
    count(*) AS weekly_active_users,
    count(*) FILTER (
        WHERE w.active_days >= $min_active_days
          AND a.activated_ts < w.week + INTERVAL 7 DAY
    ) AS weau
FROM weekly AS w
LEFT JOIN activation AS a USING (user_id)
WHERE w.week + 7 <= CAST($observation_end AS DATE)
GROUP BY w.week
ORDER BY w.week

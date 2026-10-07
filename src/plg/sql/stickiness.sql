-- Daily DAU, trailing-7-day WAU, and trailing-28-day MAU over a date spine.
WITH activity AS (
    SELECT DISTINCT user_id, CAST(event_ts AS DATE) AS activity_date
    FROM events
    WHERE event_name = $activity_event AND event_ts < $observation_end
),
spine AS (
    SELECT CAST(unnest(generate_series(
        (SELECT min(activity_date) FROM activity),
        CAST($observation_end AS DATE) - 1,
        INTERVAL 1 DAY
    )) AS DATE) AS day
)
SELECT
    s.day,
    count(DISTINCT a.user_id) FILTER (WHERE a.activity_date = s.day) AS dau,
    count(DISTINCT a.user_id) FILTER (WHERE a.activity_date > s.day - 7) AS wau,
    count(DISTINCT a.user_id) AS mau,
    s.day - 27 >= (SELECT min(activity_date) FROM activity) AS mau_window_complete
FROM spine AS s
LEFT JOIN activity AS a
  ON a.activity_date <= s.day AND a.activity_date > s.day - 28
GROUP BY s.day
ORDER BY s.day

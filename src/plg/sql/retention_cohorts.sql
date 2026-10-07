-- Weekly signup cohorts x user-relative week (days 0-6 since signup = week 0).
--   retained_bounded:   active at least once during that week ("N-week" retention)
--   retained_unbounded: active during that week or any later observed week
--   complete:           every user in the cohort has fully lived through that week
WITH cohort AS (
    SELECT
        user_id,
        CAST(date_trunc('week', signup_ts) AS DATE) AS cohort_week,
        CAST(signup_ts AS DATE) AS signup_date
    FROM users
    WHERE signup_ts < $observation_end
),
activity AS (
    SELECT DISTINCT
        e.user_id,
        c.cohort_week,
        date_diff('day', c.signup_date, CAST(e.event_ts AS DATE)) // 7 AS week_number
    FROM events AS e
    JOIN cohort AS c USING (user_id)
    WHERE e.event_name = $activity_event
      AND e.event_ts < $observation_end
      AND e.event_ts >= c.signup_date
),
last_active AS (
    SELECT user_id, cohort_week, max(week_number) AS last_week
    FROM activity
    GROUP BY ALL
),
sizes AS (
    SELECT cohort_week, count(*) AS cohort_size, max(signup_date) AS last_signup
    FROM cohort
    GROUP BY ALL
),
grid AS (
    SELECT s.cohort_week, w.week_number
    FROM sizes AS s
    CROSS JOIN (SELECT unnest(range(0, $max_weeks + 1)) AS week_number) AS w
),
bounded AS (
    SELECT cohort_week, week_number, count(*) AS retained
    FROM activity
    GROUP BY ALL
),
unbounded AS (
    SELECT g.cohort_week, g.week_number, count(*) AS retained
    FROM grid AS g
    JOIN last_active AS l
      ON l.cohort_week = g.cohort_week AND l.last_week >= g.week_number
    GROUP BY ALL
)
SELECT
    g.cohort_week,
    g.week_number,
    s.cohort_size,
    coalesce(b.retained, 0) AS retained_bounded,
    coalesce(u.retained, 0) AS retained_unbounded,
    s.last_signup + CAST(7 * g.week_number + 6 AS INTEGER) < CAST($observation_end AS DATE) AS complete
FROM grid AS g
JOIN sizes AS s USING (cohort_week)
LEFT JOIN bounded AS b USING (cohort_week, week_number)
LEFT JOIN unbounded AS u USING (cohort_week, week_number)
ORDER BY g.cohort_week, g.week_number

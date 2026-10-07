-- Early-behavior counts and the week-N retention label for activation search.
-- Only users observed through the end of the target window are included.
WITH eligible AS (
    SELECT user_id, signup_ts, CAST(signup_ts AS DATE) AS signup_date
    FROM users
    WHERE CAST(signup_ts AS DATE) + CAST($target_end_day AS INTEGER)
          < CAST($observation_end AS DATE)
),
counts AS (
    SELECT e.user_id, e.event_name, count(*) AS n
    FROM events AS e
    JOIN eligible AS u USING (user_id)
    WHERE list_contains($candidates, e.event_name)
      AND e.event_ts >= u.signup_ts
      AND e.event_ts < u.signup_ts + to_days(CAST($early_days AS INTEGER))
    GROUP BY ALL
),
retained AS (
    SELECT DISTINCT e.user_id
    FROM events AS e
    JOIN eligible AS u USING (user_id)
    WHERE e.event_name = $activity_event
      AND date_diff('day', u.signup_date, CAST(e.event_ts AS DATE))
          BETWEEN $target_start_day AND $target_end_day
)
SELECT
    u.user_id,
    c.event_name,
    coalesce(c.n, 0) AS n,
    r.user_id IS NOT NULL AS retained
FROM eligible AS u
LEFT JOIN counts AS c USING (user_id)
LEFT JOIN retained AS r USING (user_id)

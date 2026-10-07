-- Classic day-N retention: share of users active exactly N calendar days after
-- signup, among users whose day N falls inside the observation window.
WITH days AS (
    SELECT unnest($days) AS day_n
),
eligible AS (
    SELECT d.day_n, u.user_id, CAST(u.signup_ts AS DATE) AS signup_date
    FROM days AS d
    JOIN users AS u
      ON CAST(u.signup_ts AS DATE) + CAST(d.day_n AS INTEGER) < CAST($observation_end AS DATE)
),
activity AS (
    SELECT DISTINCT user_id, CAST(event_ts AS DATE) AS activity_date
    FROM events
    WHERE event_name = $activity_event AND event_ts < $observation_end
)
SELECT
    e.day_n,
    count(*) AS eligible_users,
    count(a.user_id) AS retained_users,
    count(a.user_id) / count(*) AS retention
FROM eligible AS e
LEFT JOIN activity AS a
  ON a.user_id = e.user_id
 AND a.activity_date = e.signup_date + CAST(e.day_n AS INTEGER)
GROUP BY ALL
ORDER BY e.day_n

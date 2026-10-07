-- One row per (user, calendar day) with at least one activity event.
-- day_number counts calendar days since the signup date (signup day = 0).
SELECT DISTINCT
    e.user_id,
    CAST(e.event_ts AS DATE) AS activity_date,
    date_diff('day', CAST(u.signup_ts AS DATE), CAST(e.event_ts AS DATE)) AS day_number
FROM events AS e
JOIN users AS u USING (user_id)
WHERE e.event_name = $activity_event
  AND e.event_ts < $observation_end

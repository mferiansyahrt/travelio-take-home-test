-- C1: Average nightly revenue per property type,
--     for completed bookings created in the last 90 days.
--
-- Assumptions
--   nights           = DATEDIFF(checkout_date, checkin_date)
--   nightly revenue  = total_amount / nights, per booking, then averaged per property type
--   last 90 days     = rolling window on created_at (MySQL session timezone)
--   currency         = IDR and USD are not averaged together (no FX table given), so the result is split by currency
--   invalid stays    = rows with a NULL date or nights <= 0 are left out (division by zero / negative rate);
--                      the second query counts them so they don't disappear silently
--
-- Index that helps: (status, created_at)

SELECT
    property_type,
    currency,
    COUNT(*)                                                        AS completed_bookings,
    SUM(DATEDIFF(checkout_date, checkin_date))                      AS total_nights,
    ROUND(AVG(total_amount / DATEDIFF(checkout_date, checkin_date)), 2)
                                                                    AS avg_nightly_revenue,
    -- Night-weighted version (total revenue / total nights). A 30-night stay weighs 30x a 1-night stay here.
    ROUND(SUM(total_amount) / SUM(DATEDIFF(checkout_date, checkin_date)), 2)
                                                                    AS weighted_nightly_revenue
FROM bookings
WHERE status = 'completed'
  AND created_at >= NOW() - INTERVAL 90 DAY
  AND checkout_date > checkin_date              -- also false when either date is NULL
GROUP BY property_type, currency
ORDER BY property_type, currency;


-- Completed bookings in the same window that the query above left out.
SELECT
    COUNT(*)                                                        AS excluded_bookings,
    SUM(checkin_date IS NULL OR checkout_date IS NULL)              AS missing_dates,
    SUM(checkout_date <= checkin_date)                              AS zero_or_negative_nights
FROM bookings
WHERE status = 'completed'
  AND created_at >= NOW() - INTERVAL 90 DAY
  AND (checkin_date IS NULL OR checkout_date IS NULL OR checkout_date <= checkin_date);


-- With an FX table, e.g. fx_rates(rate_date, currency, idr_rate), convert first and drop currency from the GROUP BY:
--
--   SELECT b.property_type,
--          ROUND(AVG(b.total_amount * fx.idr_rate / DATEDIFF(b.checkout_date, b.checkin_date)), 2) AS avg_nightly_revenue_idr
--   FROM bookings b
--   JOIN fx_rates fx ON fx.rate_date = DATE(b.created_at) AND fx.currency = b.currency
--   WHERE b.status = 'completed'
--     AND b.created_at >= NOW() - INTERVAL 90 DAY
--     AND b.checkout_date > b.checkin_date
--   GROUP BY b.property_type;

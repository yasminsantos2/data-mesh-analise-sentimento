-- @query vw_sentiment_by_age
SELECT
  age_band,
  sentiment,
  SUM(review_count) AS total_reviews,
  ROUND(AVG(avg_rating), 2) AS media_nota
FROM customer_sentiment.customer_sentiment_by_age
GROUP BY age_band, sentiment
ORDER BY age_band, sentiment;

-- @query vw_sentiment_by_dept
SELECT
  department_name,
  sentiment,
  SUM(review_count) AS total_reviews,
  ROUND(AVG(avg_rating), 2) AS media_nota
FROM customer_sentiment.customer_sentiment_by_age
GROUP BY department_name, sentiment
ORDER BY department_name;

-- @query vw_daily_trend
SELECT
  dt,
  sentiment,
  SUM(review_count) AS total_reviews
FROM customer_sentiment.customer_sentiment_by_age
GROUP BY dt, sentiment
ORDER BY dt, sentiment;

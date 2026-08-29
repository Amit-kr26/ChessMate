## Grafana queries

Provisioned via `monitoring/grafana/provisioning/datasources/datasource.yml` (`uid aeo2c8b4jnrwgc`) and `provisioning/dashboards/dashboard.yml`. All time-series now use `WHERE $__timeFilter(timestamp)` so Grafana time picker works (was ignored).

Answer relevance from user's perspective:

```sql
SELECT
  COALESCE(SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END),0) as thumbs_up,
  COALESCE(SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END),0) as thumbs_down
FROM feedback
WHERE $__timeFilter(timestamp)
```

Relevance of LLM answers:

```sql
SELECT
  relevance,
  COUNT(*) as count
FROM conversations
WHERE $__timeFilter(timestamp)
GROUP BY relevance
```

Prompt Token Usage:

```sql
SELECT
  timestamp AS time,
  prompt_tokens,
  completion_tokens,
  total_tokens
FROM conversations
WHERE $__timeFilter(timestamp)
ORDER BY timestamp
```

Evaluation Token Usage:

```sql
SELECT
  timestamp AS time,
  eval_prompt_tokens,
  eval_completion_tokens,
  eval_total_tokens
FROM conversations
WHERE $__timeFilter(timestamp)
ORDER BY timestamp
```

RAG response time (sec) – `response_time` (LLM) vs `total_time` (RAG + eval) both stored:

```sql
SELECT
  timestamp AS time,
  response_time,
  total_time
FROM conversations
WHERE $__timeFilter(timestamp)
ORDER BY timestamp
```

Last conversations:

```sql
SELECT
  timestamp AS time,
  question,
  answer,
  relevance
FROM conversations
WHERE $__timeFilter(timestamp)
ORDER BY timestamp DESC
LIMIT 5
```

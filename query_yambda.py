import os
import clickhouse_connect

CA_CERT  = "/usr/local/share/ca-certificates/Yandex/RootCA.crt"
CH_HOST  = os.environ["CH_HOST"]
CH_USER  = os.environ["CH_USER"]
CH_PASS  = os.environ["CH_PASS"]

client = clickhouse_connect.get_client(
    host     = CH_HOST,
    port     = 8443,
    username = CH_USER,
    password = CH_PASS,
    database = "yambda",
    secure   = True,
    verify   = True,
    ca_cert  = CA_CERT,
)

# ── Топ-10 самых прослушиваемых треков ─────────────────────────────────────────
df_top = client.query_df("""
    SELECT
        item_id,
        count()                         AS listens,
        countIf(is_organic = 1)         AS organic,
        round(avg(played_ratio_pct), 1) AS avg_completion_pct,
        round(avg(track_length_seconds) / 60.0, 2) AS avg_min
    FROM listens
    GROUP BY item_id
    ORDER BY listens DESC
    LIMIT 10
""")
print(df_top.to_string(index=False))

# ── Распределение completion rate (сколько % трека слушают) ────────────────────
df_completion = client.query_df("""
    SELECT
        intDiv(least(played_ratio_pct, 100), 10) * 10 AS bucket_start,
        count()                                        AS cnt
    FROM listens
    GROUP BY bucket_start
    ORDER BY bucket_start
""")
print(df_completion)

# ── Уникальные пользователи и треки ────────────────────────────────────────────
row = client.query("SELECT uniq(uid), uniq(item_id), count() FROM listens").first_row
print(f"Пользователей: {row[0]:,} | Треков: {row[1]:,} | Событий: {row[2]:,}")

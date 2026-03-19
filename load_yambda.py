#!/usr/bin/env python3
# load_yambda.py — загрузка в Managed ClickHouse

import os
import pyarrow.parquet as pq
import pandas as pd
import clickhouse_connect
from huggingface_hub import hf_hub_download
from tqdm import tqdm

# ── Параметры подключения ───────────────────────────────────────────────────────
CA_CERT  = os.environ.get("CA_CERT")
CH_HOST  = os.environ["CH_HOST"]
CH_USER  = os.environ["CH_USER"]
CH_PASS  = os.environ["CH_PASS"]

BATCH_SIZE = 500_000

client = clickhouse_connect.get_client(
    host=CH_HOST, port=8443,
    username=CH_USER, password=CH_PASS,
    database="yambda",
    secure=True, verify=True, ca_cert=CA_CERT,
)

# ── Создаём схему ────────────────────────────────────────────────
client.command("CREATE DATABASE IF NOT EXISTS yambda ON CLUSTER '{cluster}'")

client.command("""
CREATE TABLE IF NOT EXISTS yambda.listens ON CLUSTER '{cluster}'
(
    uid                  UInt32    COMMENT 'ID пользователя',
    item_id              UInt32    COMMENT 'ID трека',
    timestamp            DateTime  COMMENT 'Время события (Unix, 5-сек гранулярность)',
    is_organic           UInt8     COMMENT '1 = органическое, 0 = рекомендация',
    played_ratio_pct     UInt16    COMMENT '% трека прослушан (может быть >100 при перемотке)',
    track_length_seconds UInt32    COMMENT 'Длина трека в секундах'
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/yambda/listens', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (uid, timestamp)
""")

client.command("""
CREATE TABLE IF NOT EXISTS yambda.likes ON CLUSTER '{cluster}'
(
    uid        UInt32   COMMENT 'ID пользователя',
    item_id    UInt32   COMMENT 'ID трека',
    timestamp  DateTime COMMENT 'Время лайка',
    is_organic UInt8    COMMENT '1 = органический, 0 = из рекомендаций'
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/yambda/likes', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (uid, item_id, timestamp)
""")

client.command("""
CREATE TABLE IF NOT EXISTS yambda.dislikes ON CLUSTER '{cluster}'
(
    uid        UInt32   COMMENT 'ID пользователя',
    item_id    UInt32   COMMENT 'ID трека',
    timestamp  DateTime COMMENT 'Время дизлайка',
    is_organic UInt8    COMMENT '1 = органический, 0 = из рекомендаций'
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/yambda/dislikes', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (uid, item_id, timestamp)
""")

client.command("""
CREATE TABLE IF NOT EXISTS yambda.events ON CLUSTER '{cluster}'
(
    uid                  UInt32,
    item_id              UInt32,
    timestamp            DateTime,
    is_organic           UInt8,
    event_type           LowCardinality(String),
    played_ratio_pct     Nullable(UInt16),
    track_length_seconds Nullable(UInt32)
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/yambda/events', '{replica}')
PARTITION BY toYYYYMM(timestamp)
ORDER BY (event_type, uid, timestamp)
""")

client.command("""
CREATE MATERIALIZED VIEW IF NOT EXISTS yambda.daily_stats ON CLUSTER '{cluster}'
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(day)
ORDER BY (day, is_organic)
AS
SELECT
    toDate(timestamp)           AS day,
    is_organic,
    count()                     AS listens_count,
    uniq(uid)                   AS unique_users,
    uniq(item_id)               AS unique_tracks,
    sum(played_ratio_pct)       AS total_played_pct,
    sum(track_length_seconds)   AS total_track_seconds
FROM yambda.listens
GROUP BY day, is_organic
""")

print("Схема создана (или уже существует)")


def download_parquet(filename: str) -> str:
    """Скачивает файл из flat/50m репозитория Yambda."""
    print(f"Загружаем {filename} из HuggingFace...")
    local_path = hf_hub_download(
        repo_id   = "yandex/yambda",
        filename  = f"flat/50m/{filename}",
        repo_type = "dataset",
        local_dir = "/tmp/yambda",
    )
    print(f"  → сохранён: {local_path}")
    return local_path


def load_parquet_to_ch(parquet_path: str, table: str, transform_fn=None):
    pf         = pq.ParquetFile(parquet_path)
    total_rows = pf.metadata.num_rows
    inserted   = 0

    print(f"\nЗагружаем {total_rows:,} строк в yambda.{table}")

    with tqdm(total=total_rows, unit="rows", unit_scale=True) as pbar:
        for batch in pf.iter_batches(batch_size=BATCH_SIZE):
            df = batch.to_pandas()

            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=False)

            if transform_fn:
                df = transform_fn(df)

            client.insert_df(table, df)
            inserted += len(df)
            pbar.update(len(df))

    print(f"  Вставлено {inserted:,} строк в {table}")


# ── Загружаем listens  ──────────────────────────
listens_path = download_parquet("listens.parquet")
load_parquet_to_ch(listens_path, "listens")

# ── Загружаем likes ─────────────────────────────────────────────────────────────
likes_path = download_parquet("likes.parquet")
load_parquet_to_ch(likes_path, "likes")

# ── Загружаем dislikes ──────────────────────────────────────────────────────────
dislikes_path = download_parquet("dislikes.parquet")
load_parquet_to_ch(dislikes_path, "dislikes")

# ── Загружаем events (multi_event — все типы событий в одной таблице) ──────────
def prepare_events(df: pd.DataFrame) -> pd.DataFrame:
    """played_ratio_pct и track_length_seconds — Nullable в multi_event."""
    df["played_ratio_pct"]     = df["played_ratio_pct"].astype("UInt16")
    df["track_length_seconds"] = df["track_length_seconds"].astype("UInt32")
    return df

events_path = download_parquet("multi_event.parquet")
load_parquet_to_ch(events_path, "events", transform_fn=prepare_events)

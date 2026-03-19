# Код для вебинара: Managed ClickHouse в Yandex Cloud

---

## БЛОК 1. Managed ClickHouse без публичного доступа

### 1.1 Terraform — структура проекта

```
terraform/
├── main.tf
├── variables.tf
├── outputs.tf
└── terraform.tfvars   # не коммитить — добавить в .gitignore
```

---

### 1.2 `variables.tf`

[terraform/variables.tf](terraform/variables.tf)

---

### 1.3 `main.tf`

[terraform/main.tf](terraform/main.tf)

---

### 1.4 `outputs.tf`

[terraform/outputs.tf](terraform/outputs.tf)

---

### 1.5 `terraform.tfvars` (шаблон)

```hcl
cloud_id       = "b1g..."
folder_id      = "b1g..."
ch_password    = "Yambda2024!"
ssh_public_key = "ssh-ed25519 AAAA..."
# yc_token задаётся через переменную среды — не хранить в файле
```

---

### 1.6 Запуск Terraform

```bash
terraform init

# Безопасная передача токена через env-переменную
export TF_VAR_yc_token=$(yc iam create-token)

terraform plan
terraform apply

# Сохраняем FQDN для дальнейшей работы
export CH_HOST=$(terraform output -raw clickhouse_fqdn)
export JUMP_IP=$(terraform output -raw jump_public_ip)

echo "ClickHouse: $CH_HOST"
echo "Jump host:  $JUMP_IP"
```

---

### 1.7 Подготовка jump-хоста (выполнить один раз)

```bash
# Подключаемся к jump-хосту
ssh ubuntu@$JUMP_IP -i ~/.ssh/key

# ── Устанавливаем CA-сертификат Yandex Cloud ────────────────────────────────────
# Обязателен для TLS
sudo mkdir -p /usr/local/share/ca-certificates/Yandex
sudo wget "https://storage.yandexcloud.net/cloud-certs/RootCA.pem" \
    -O /usr/local/share/ca-certificates/Yandex/RootCA.crt
sudo chmod 655 /usr/local/share/ca-certificates/Yandex/RootCA.crt
sudo update-ca-certificates

# ── Задаём переменные окружения ─────────────────────────────────────────────────
export CH_HOST="rc1a-<id>.mdb.yandexcloud.net"   # из terraform output
export CH_USER="admin"
export CH_PASS="Yambda2024!"
export CA_CERT="/usr/local/share/ca-certificates/Yandex/RootCA.crt"
```

---

### 1.8 Способ 1 — clickhouse-client (нативный протокол, порт 9440)

```bash
# Установка
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg
curl -fsSL 'https://packages.clickhouse.com/rpm/lts/repodata/repomd.xml.key' | \
    sudo gpg --dearmor -o /usr/share/keyrings/clickhouse-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/clickhouse-keyring.gpg] \
    https://packages.clickhouse.com/deb stable main" | \
    sudo tee /etc/apt/sources.list.d/clickhouse.list
sudo apt-get update && sudo apt-get install -y clickhouse-client

# Загрузка файла конфигурации clickhouse-client
mkdir -p ~/.clickhouse-client && \
wget "https://storage.yandexcloud.net/doc-files/clickhouse-client.conf.example" \
  --output-document ~/.clickhouse-client/config.xml

# Интерактивный режим (без пароля в командной строке — спросит при запуске)
clickhouse-client \
  --host "$CH_HOST" \
  --secure \
  --user "$CH_USER" \
  --database yambda \
  --port 9440 \
  --ask-password

# Интерактивный режим (с паролем в командной строке)
clickhouse-client \
  --host "$CH_HOST" --port 9440 \
  --user "$CH_USER" --password "$CH_PASS" \
  --database yambda --secure

# Неинтерактивный запрос — топ-10 треков по числу прослушиваний
clickhouse-client \
  --host "$CH_HOST" --port 9440 \
  --user "$CH_USER" --password "$CH_PASS" \
  --database yambda --secure \
  --query "
    SELECT
        item_id,
        count()                                             AS listens,
        round(avg(played_ratio_pct), 1)                    AS avg_completion_pct,
        any(track_length_seconds)                           AS track_length_seconds
    FROM listens
    GROUP BY item_id
    ORDER BY listens DESC
    LIMIT 10
    FORMAT PrettyCompact"
```

---

### 1.9 Способ 2 — curl (HTTP-интерфейс, порт 8443)

```bash
# Проверка
curl "https://$CH_HOST:8443/?query=SELECT+version()" \
  --user "$CH_USER:$CH_PASS" \
  --cacert "$CA_CERT"

# Органические vs рекомендованные прослушивания
curl "https://$CH_HOST:8443/?database=yambda" \
  --user "$CH_USER:$CH_PASS" \
  --cacert "$CA_CERT" \
  --data-binary "
    SELECT
        is_organic,
        count()                          AS events,
        round(100.0 * count() / sum(count()) OVER (), 2) AS pct
    FROM listens
    GROUP BY is_organic
    FORMAT JSONEachRow"

```

---

### 1.10 Способ 3 — mysql-client (порт 3306)

```bash
sudo apt-get install -y mysql-client

# ClickHouse эмулирует MySQL Wire Protocol — полезно для BI-инструментов 
# mysql_protocol = true уже включён в main.tf 
mysql \
  --host="$CH_HOST" --port=3306 \
  --ssl-ca="$CA_CERT" --ssl-mode=VERIFY_IDENTITY \
  --user="$CH_USER" --password \
  yambda

# Активность по часам — первые 20 часовых бакетов датасета
mysql \
  --host="$CH_HOST" --port=3306 \
  --ssl-ca="$CA_CERT" --ssl-mode=VERIFY_IDENTITY \
  --user="$CH_USER" --password \
  yambda \
  --execute="
    SELECT
        toStartOfHour(timestamp)  AS hour_bucket,
        count()                   AS listens_count
    FROM listens
    GROUP BY hour_bucket
    ORDER BY hour_bucket
    LIMIT 20;"
```

---

### 1.11 Способ 4 — Docker

```bash
sudo apt-get install -y docker.io
sudo usermod -aG docker ubuntu && newgrp docker
```

`Dockerfile` — образ с clickhouse-client и сертификатами Yandex Cloud:

```dockerfile
FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install wget --yes apt-transport-https ca-certificates dirmngr && \
    apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv 8919F6BD2B48D754 && \
    echo "deb https://packages.clickhouse.com/deb stable main" | tee \
        /etc/apt/sources.list.d/clickhouse.list && \
    apt-get update && \
    apt-get install wget clickhouse-client --yes && \
    mkdir --parents ~/.clickhouse-client && \
    wget "https://storage.yandexcloud.net/doc-files/clickhouse-client.conf.example" \
         --output-document ~/.clickhouse-client/config.xml && \
    mkdir --parents /usr/local/share/ca-certificates/Yandex/ && \
    wget "https://storage.yandexcloud.net/cloud-certs/RootCA.pem" \
         --output-document /usr/local/share/ca-certificates/Yandex/RootCA.crt && \
    wget "https://storage.yandexcloud.net/cloud-certs/IntermediateCA.pem" \
         --output-document /usr/local/share/ca-certificates/Yandex/IntermediateCA.crt && \
    chmod 655 \
         /usr/local/share/ca-certificates/Yandex/RootCA.crt \
         /usr/local/share/ca-certificates/Yandex/IntermediateCA.crt && \
    update-ca-certificates

ENTRYPOINT ["clickhouse-client"]
```

```bash
docker build -t ch-client .

# Подключение к кластеру
docker run --rm -it ch-client \
  --host "$CH_HOST" --port 9440 \
  --user "$CH_USER" --password "$CH_PASS" \
  --database yambda --secure \
  --query "SELECT count() FROM listens"
```

---

### 1.12 Способ 5 — clickhouse-connect (Python)

```bash
python3 -m venv ~/venv/clickhouse-connect
source ~/venv/clickhouse-connect/bin/activate
pip install clickhouse-connect pyarrow pandas tqdm
```

[query_yambda.py](query_yambda.py)

---

### 1.13 Способ 6 — SQLAlchemy (Python)

```bash
python3 -m venv ~/venv/sqlalchemy
source ~/venv/sqlalchemy/bin/activate
pip install sqlalchemy clickhouse-connect
```

```python
# sqlalchemy_yambda.py
import os
from sqlalchemy import create_engine, text, Column, Integer, SmallInteger, DateTime
from sqlalchemy.orm import DeclarativeBase, Session

CA_CERT  = os.environ["CA_CERT"]
CH_HOST  = os.environ["CH_HOST"]
CH_USER  = os.environ["CH_USER"]
CH_PASS  = os.environ["CH_PASS"]

# clickhousedb:// — диалект clickhouse-connect; порт 8443 + ca_cert для TLS
engine = create_engine(
    f"clickhousedb://{CH_USER}:{CH_PASS}@{CH_HOST}:8443/yambda"
    f"?secure=True&ca_cert={CA_CERT}",
    echo=False,
)

# ── Raw SQL через text() ────────────────────────────────────────────────────────
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT
            toStartOfDay(timestamp)         AS day,
            sum(is_organic = 1)             AS organic_listens,
            sum(is_organic = 0)             AS rec_listens,
            round(100.0 * sum(is_organic = 1) / count(), 2) AS organic_pct
        FROM listens
        GROUP BY day
        ORDER BY day
        LIMIT 14
    """))
    print(f"{'День':<12} {'Органика':>12} {'Рекоменд.':>12} {'% органики':>12}")
    print("-" * 50)
    for row in result:
        print(f"{str(row.day):<12} {row.organic_listens:>12,} {row.rec_listens:>12,} {row.organic_pct:>11.1f}%")

# ── ORM-модель ──────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass

class Listen(Base):
    __tablename__  = "listens"
    __table_args__ = {"schema": "yambda"}

    uid                  = Column(Integer, primary_key=True)
    item_id              = Column(Integer)
    timestamp            = Column(DateTime)
    is_organic           = Column(SmallInteger)
    played_ratio_pct     = Column(SmallInteger)
    track_length_seconds = Column(Integer)

with Session(engine) as session:
    # Треки с полным прослушиванием (>= 90%) от органических источников
    full_plays = (
        session.query(Listen.item_id)
        .filter(Listen.played_ratio_pct >= 90, Listen.is_organic == 1)
        .limit(5)
        .all()
    )
    print("Треки с полным органическим прослушиванием:", [r[0] for r in full_plays])
```
---

## БЛОК 2. Managed ClickHouse с публичным доступом

### 2.1 Создание инфраструктуры через YC CLI

```bash
# ── Установка YC CLI (если ещё не установлен) ───────────────────────────────────
curl -sSL https://storage.yandexcloud.net/yandexcloud-yc/install.sh | bash
source ~/.bashrc
yc init

# ── Сеть ────────────────────────────────────────────────────────────────────────
yc vpc network create --name ch-network-public-webinar

# ── Подсети в 3 зонах (ClickHouse — a+b, Keeper — a+b+d) ───────────────────────
yc vpc subnet create \
  --name ch-subnet-public-webinar-a --zone ru-central1-a \
  --network-name ch-network-public-webinar --range 10.20.1.0/24

yc vpc subnet create \
  --name ch-subnet-public-webinar-b --zone ru-central1-b \
  --network-name ch-network-public-webinar --range 10.20.2.0/24

yc vpc subnet create \
  --name ch-subnet-public-webinar-d --zone ru-central1-d \
  --network-name ch-network-public-webinar --range 10.20.3.0/24

SUBNET_A=$(yc vpc subnet get ch-subnet-public-webinar-a --format json | jq -r '.id')
SUBNET_B=$(yc vpc subnet get ch-subnet-public-webinar-b --format json | jq -r '.id')
SUBNET_D=$(yc vpc subnet get ch-subnet-public-webinar-d --format json | jq -r '.id')

# ── Группа безопасности ─────────────────────────────────────────────────────────
yc vpc security-group create \
  --name         ch-sg-public-webinar \
  --network-name ch-network-public-webinar \
  --rule         "direction=ingress,port=9440,protocol=tcp,v4-cidrs=[0.0.0.0/0],description=ClickHouse-native-TLS" \
  --rule         "direction=ingress,port=8443,protocol=tcp,v4-cidrs=[0.0.0.0/0],description=ClickHouse-HTTPS" \
  --rule         "direction=egress,from-port=0,to-port=65535,protocol=any,v4-cidrs=[0.0.0.0/0]"

SG_ID=$(yc vpc security-group get ch-sg-public-webinar --format json | jq -r '.id')

# ── HA-кластер: 2 ClickHouse + 3 Keeper на отдельных хостах ────────────────────
export CH_PASSWORD='Yambda2024!'

yc managed-clickhouse cluster create \
  --name                        ch-public-webinar \
  --environment                 production \
  --network-name                ch-network-public-webinar \
  --security-group-ids          ${SG_ID} \
  --clickhouse-resource-preset  s3-c2-m8 \
  --clickhouse-disk-type        network-ssd \
  --clickhouse-disk-size        50 \
  --zookeeper-resource-preset   s3-c2-m8 \
  --zookeeper-disk-type         network-ssd \
  --zookeeper-disk-size         10 \
  --host                        type=clickhouse,zone-id=ru-central1-a,subnet-id=${SUBNET_A},assign-public-ip=true \
  --host                        type=clickhouse,zone-id=ru-central1-b,subnet-id=${SUBNET_B},assign-public-ip=true \
  --host                        type=keeper,zone-id=ru-central1-a,subnet-id=${SUBNET_A} \
  --host                        type=keeper,zone-id=ru-central1-b,subnet-id=${SUBNET_B} \
  --host                        type=keeper,zone-id=ru-central1-d,subnet-id=${SUBNET_D} \
  --user                        name=admin,password=${CH_PASSWORD} \
  --database                    name=yambda \
  --async

# ── Мониторим создание ──────────────────────────────────────────────────────────
watch -n 10 'yc managed-clickhouse cluster get ch-public-webinar \
    --format json | jq -r ".status"'


# ── Проверяем подключение ────────────────────────────────────────────────────────
curl "https://${CH_HOST}:8443/?query=SELECT+version()" \
  --user "admin:${CH_PASS}" \
  --cacert /usr/local/share/ca-certificates/Yandex/RootCA.crt
```

### 2.2 Загрузка данных в публичный кластер

Схема и скрипт загрузки — см. **раздел 3.2**. Перед запуском переопределить `CH_HOST`:

```bash
export CH_HOST="<FQDN публичного кластера>"   # из yc managed-clickhouse hosts list
export CH_USER="admin"
export CH_PASS='Yambda2024!'

# Запускаем загрузку (раздел 3.2)
source ~/venv/yambda/bin/activate
python3 load_yambda.py
```

---

### 2.3 DBeaver — параметры подключения

| Параметр       | Значение                                              |
|----------------|-------------------------------------------------------|
| Driver         | ClickHouse                                            |
| Host           | `rc1a-<id>.mdb.yandexcloud.net`                       |
| Port           | `8443`                                                |
| Database       | `yambda`                                              |
| Username       | `admin`                                               |
| Password       | `Yambda2024!`                                         |
| SSL            | Включить (`Use SSL`)                                |
| CA Certificate | `/Users/<you>/.yandex/RootCA.crt` (полный путь, ~ не работает) |
| SSL Mode       | `STRICT`                                         |



Демо-запрос в DBeaver — пользователи по активности:

```sql
-- Распределение пользователей по количеству прослушиваний 
SELECT
    multiIf(
        listens_count < 100,   '<100',
        listens_count < 500,   '100–499',
        listens_count < 2000,  '500–1999',
        listens_count < 10000, '2K–9.9K',
        '10K+'
    )                    AS activity_bucket,
    count()              AS users_count
FROM (
    SELECT uid, count() AS listens_count
    FROM yambda.listens
    GROUP BY uid
)
GROUP BY activity_bucket
ORDER BY min(listens_count);
```

---

### 2.4 Play UI (встроенный веб-интерфейс ClickHouse)

Открыть в браузере:
```
https://rc1a-<id>.mdb.yandexcloud.net:8443/play
```

Демо-запросы в Play UI:

```sql
-- Активность по часам суток — выявляем паттерн слушания
SELECT
    toHour(timestamp)  AS hour_of_day,
    count()            AS listens,
    bar(count(), 0, max(count()) OVER (), 40) AS chart
FROM yambda.listens
GROUP BY hour_of_day
ORDER BY hour_of_day;
```

---

## БЛОК 3. ClickHouse + DataLens

---

### 3.2 Загрузка датасета

> Если при подключении возникает ошибка сертификата — см. **[раздел 1.7](#17-подготовка-jump-хоста-выполнить-один-раз)** (установка CA-сертификата Yandex Cloud).

```bash
# Устанавливаем зависимости 
sudo apt install python3.10-venv
python3 -m venv ~/venv/yambda
source ~/venv/yambda/bin/activate
pip install clickhouse-connect pyarrow pandas huggingface_hub tqdm

```

[load_yambda.py](load_yambda.py)

---

### 3.3 Запросы для WebSQL и DataLens

```sql
-- ── 1. Топ-20 треков по числу прослушиваний ────────────────────────────────────
SELECT
    toString(item_id)       AS track_id,
    countIf(is_organic = 1) AS organic,
    countIf(is_organic = 0) AS from_recommendation,
    count()                 AS total
FROM yambda.listens
GROUP BY item_id
ORDER BY total DESC
LIMIT 20;

-- ── 2. Доля органики и рекомендаций─────────────────────────
SELECT
    if(is_organic = 1, 'Органика', 'Рекомендации')                        AS source,
    sum(listens_count)                                                     AS listens,
    round(100.0 * sum(listens_count) / sum(sum(listens_count)) OVER (), 2) AS pct
FROM yambda.daily_stats
GROUP BY source;
```

#### Визуализация в DataLens

**Запрос 1 — Столбчатая диаграмма «Топ-20 треков»**

1. В DataLens создайте **Connection → ClickHouse**.
2. Создайте **Dataset** → выберите тип источника **SQL-запрос** и вставьте запрос 1 выше.
3. Создайте **Chart** → тип **Bar chart** (горизонтальные полосы).
   - **X :** `track_id`
   - **Y :** `organic` и `from_recommendation` — два сегмента
4. Сохраните и добавьте на **Dashboard**.

**Запрос 2 — Круговая диаграмма «Доля органики и рекомендаций»**

1. Создайте **Dataset** → выберите тип источника **SQL-запрос** и вставьте запрос 2 выше.
   > Колонки `listens` и `pct` появляются только в результате запроса; в сырой MV `yambda.daily_stats` столбец называется `listens_count`, а `pct` отсутствует.
2. Создайте **Чарты** → тип **Круговая диаграмма**.
   - **Категории:** `source`
   - **Показатели:** `pct`
   - **Подписи:** `pct` — подписи на секторах
3. Сохраните и добавьте на **Dashboard**.

---

## Справочник портов Managed ClickHouse (Yandex Cloud)

| Протокол         | Порт | TLS | Типичное использование                     |
|------------------|------|-----|--------------------------------------------|
| Native TCP + TLS | 9440 | да  | clickhouse-client, clickhouse-connect      |
| HTTPS            | 8443 | да  | curl, DBeaver, Play UI, SQLAlchemy, DataLens |
| MySQL + TLS      | 3306 | да  | mysql-client, MySQL-совместимые BI-клиенты |
| Native TCP       | 9000 | нет  | только внутри кластера                     |
| HTTP             | 8123 | нет  | только внутри кластера                     |

---

## Удаление ресурсов

### Terraform (Блок 1)

```bash
cd terraform
export TF_VAR_yc_token=$(yc iam create-token)
terraform destroy
```

### YC CLI (Блок 2)

```bash
# 1. Кластер
yc managed-clickhouse cluster delete ch-public-webinar --async

# Ждём удаления
watch -n 10 'yc managed-clickhouse cluster list'

# 2. Группа безопасности
yc vpc security-group delete ch-sg-public-webinar

# 3. Подсети
yc vpc subnet delete ch-subnet-public-webinar-a
yc vpc subnet delete ch-subnet-public-webinar-b
yc vpc subnet delete ch-subnet-public-webinar-d

# 4. Сеть
yc vpc network delete ch-network-public-webinar
```

### UI - через ручное удаление каждого ресурса

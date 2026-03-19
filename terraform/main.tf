terraform {
  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = "0.192.0"
    }
  }
  required_version = ">= 1.5.0"
}

provider "yandex" {
  token     = var.yc_token
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
}

# ── Сетевая инфраструктура ──────────────────────────────────────────────────────

resource "yandex_vpc_network" "main" {
  name = "clickhouse-network-webinar"
}

resource "yandex_vpc_subnet" "main" {
  name           = "clickhouse-subnet-webinar-a"
  zone           = "ru-central1-a"
  network_id     = yandex_vpc_network.main.id
  v4_cidr_blocks = ["10.10.1.0/24"]
}

resource "yandex_vpc_subnet" "b" {
  name           = "clickhouse-subnet-webinar-b"
  zone           = "ru-central1-b"
  network_id     = yandex_vpc_network.main.id
  v4_cidr_blocks = ["10.10.2.0/24"]
}

resource "yandex_vpc_subnet" "d" {
  name           = "clickhouse-subnet-webinar-d"
  zone           = "ru-central1-d"
  network_id     = yandex_vpc_network.main.id
  v4_cidr_blocks = ["10.10.3.0/24"]
}

# ── Группа безопасности ─────────────────────────────────────────────────────────

resource "yandex_vpc_security_group" "jump" {
  name       = "jump-sg-webinar"
  network_id = yandex_vpc_network.main.id

  ingress {
    description    = "SSH"
    protocol       = "TCP"
    port           = 22
    v4_cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description    = "Весь исходящий трафик"
    protocol       = "ANY"
    from_port      = 0
    to_port        = 65535
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "clickhouse" {
  name       = "clickhouse-sg-webinar"
  network_id = yandex_vpc_network.main.id

  # Разрешаем все порты ClickHouse только с jump-хоста 
  ingress {
    description       = "ClickHouse HTTP :8123"
    protocol          = "TCP"
    port              = 8123
    security_group_id = yandex_vpc_security_group.jump.id
  }

  ingress {
    description       = "ClickHouse HTTPS :8443"
    protocol          = "TCP"
    port              = 8443
    security_group_id = yandex_vpc_security_group.jump.id
  }

  ingress {
    description       = "ClickHouse native :9000"
    protocol          = "TCP"
    port              = 9000
    security_group_id = yandex_vpc_security_group.jump.id
  }

  ingress {
    description       = "ClickHouse native TLS :9440"
    protocol          = "TCP"
    port              = 9440
    security_group_id = yandex_vpc_security_group.jump.id
  }

  ingress {
    description       = "ClickHouse MySQL :3306"
    protocol          = "TCP"
    port              = 3306
    security_group_id = yandex_vpc_security_group.jump.id
  }

}

# ── Managed ClickHouse (без публичного IP) ──────────────────────────────────────

resource "yandex_mdb_clickhouse_cluster_v2" "private" {
  name               = "clickhouse-private-webinar"
  environment        = "PRODUCTION"
  network_id         = yandex_vpc_network.main.id
  security_group_ids = [yandex_vpc_security_group.clickhouse.id]

  # ClickHouse хосты
  clickhouse = {
    resources = {
      resource_preset_id = "s3-c4-m16"   
      disk_type_id       = "network-ssd"
      disk_size          = 20
    }
    config = {
      mysql_protocol = true
    }
  }

  # ClickHouse Keeper хосты — ресурсы задаются через zookeeper-блок
  zookeeper = {
    resources = {
      resource_preset_id = "s3-c2-m8"   
      disk_type_id       = "network-ssd"
      disk_size          = 10
    }
  }

  # Хосты кластера —
  hosts = {
    "ca" = {
      type             = "CLICKHOUSE"
      zone             = "ru-central1-a"
      subnet_id        = yandex_vpc_subnet.main.id
      assign_public_ip = false
    }
    "cb" = {
      type             = "CLICKHOUSE"
      zone             = "ru-central1-b"
      subnet_id        = yandex_vpc_subnet.b.id
      assign_public_ip = false
    }
    "ka" = {
      type      = "KEEPER"
      zone      = "ru-central1-a"
      subnet_id = yandex_vpc_subnet.main.id
    }
    "kb" = {
      type      = "KEEPER"
      zone      = "ru-central1-b"
      subnet_id = yandex_vpc_subnet.b.id
    }
    "kd" = {
      type      = "KEEPER"
      zone      = "ru-central1-d"
      subnet_id = yandex_vpc_subnet.d.id
    }
  }



  maintenance_window {
    type = "ANYTIME"
  }
}

data "yandex_mdb_clickhouse_cluster_v2" "private" {
  cluster_id = yandex_mdb_clickhouse_cluster_v2.private.id
}

resource "yandex_mdb_clickhouse_database" "yambda" {
  cluster_id = yandex_mdb_clickhouse_cluster_v2.private.id
  name       = "yambda"
}

resource "yandex_mdb_clickhouse_user" "admin" {
  cluster_id = yandex_mdb_clickhouse_cluster_v2.private.id
  name       = "admin"
  password   = var.ch_password
  permission {
    database_name = yandex_mdb_clickhouse_database.yambda.name
  }
}

# ── Compute Cloud (jump-хост с публичным IP) ────────────────────────────────────

data "yandex_compute_image" "ubuntu" {
  family    = "ubuntu-2204-lts"
  folder_id = "standard-images"
}

resource "yandex_compute_instance" "jump" {
  name        = "clickhouse-jump-webinar"
  platform_id = "standard-v3"   
  zone        = "ru-central1-a"

  resources {
    cores         = 4      
    memory        = 16     
    core_fraction = 100
  }

  boot_disk {
    initialize_params {
      image_id = data.yandex_compute_image.ubuntu.id
      type     = "network-ssd"
      size     = 30
    }
  }

  network_interface {
    subnet_id          = yandex_vpc_subnet.main.id
    security_group_ids = [yandex_vpc_security_group.jump.id]
    nat                = true   
  }

  metadata = {
    ssh-keys = "ubuntu:${var.ssh_public_key}"
  }
}
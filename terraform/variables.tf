variable "yc_token" {
  description = "Yandex Cloud OAuth-токен (yc iam create-token)"
  type        = string
  sensitive   = true
}

variable "cloud_id" {
  description = "ID облака"
  type        = string
}

variable "folder_id" {
  description = "ID каталога"
  type        = string
}

variable "ch_password" {
  description = "Пароль пользователя admin кластера ClickHouse"
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "Публичный SSH-ключ для доступа к ВМ"
  type        = string
}

variable "zone" {
  description = "Зона доступности"
  type        = string
  default     = "ru-central1-a"
}
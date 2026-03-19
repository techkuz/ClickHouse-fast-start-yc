output "clickhouse_hosts" {
  description = "FQDNы всех хостов ClickHouse"
  value = [
    for h in data.yandex_mdb_clickhouse_cluster_v2.private.hosts :
    h.fqdn if h.type == "CLICKHOUSE"
  ]
}

output "clickhouse_fqdn" {
  description = "FQDN первого хоста ClickHouse"
  value = [
    for h in data.yandex_mdb_clickhouse_cluster_v2.private.hosts :
    h.fqdn if h.type == "CLICKHOUSE"
  ][0]
}

output "jump_public_ip" {
  description = "Публичный IP jump-хоста"
  value       = yandex_compute_instance.jump.network_interface[0].nat_ip_address
}

output "ssh_command" {
  description = "Команда SSH для подключения к jump-хосту"
  value       = "ssh ubuntu@${yandex_compute_instance.jump.network_interface[0].nat_ip_address} -i ./ssh/key"
}

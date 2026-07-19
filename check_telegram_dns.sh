#!/bin/bash
set -uo pipefail

echo "=================================================="
echo " Диагностика сети/DNS для api.telegram.org (Docker)"
echo " Дата: $(date)"
echo "=================================================="

echo -e "\n[1] Проверка резолва через системный DNS (getent hosts)"
getent hosts api.telegram.org || echo "  -> getent не смог резолвить"

echo -e "\n[2] Содержимое /etc/resolv.conf внутри контейнера"
cat /etc/resolv.conf 2>/dev/null || echo "  -> /etc/resolv.conf отсутствует"

echo -e "\n[3] Содержимое /etc/hosts"
cat /etc/hosts 2>/dev/null

echo -e "\n[4] Проверка наличия dig/nslookup/curl/ping/traceroute/mtr"
for tool in dig nslookup curl ping traceroute mtr; do
  if command -v "$tool" >/dev/null 2>&1; then
    echo "  [OK] $tool найден: $(command -v $tool)"
  else
    echo "  [--] $tool не установлен"
  fi
done

echo -e "\n[5] Резолв через дефолтный (системный) резолвер"
if command -v dig >/dev/null 2>&1; then
  dig api.telegram.org +short
else
  getent hosts api.telegram.org
fi

echo -e "\n[6] Резолв A-записи через публичные DNS (8.8.8.8, 1.1.1.1, 9.9.9.9)"
if command -v dig >/dev/null 2>&1; then
  for dns in 8.8.8.8 1.1.1.1 9.9.9.9; do
    echo "  через $dns:"
    dig @"$dns" api.telegram.org +short | sed 's/^/    /'
  done
else
  echo "  dig не установлен, пропускаем (см. блок установки утилит ниже)"
fi

echo -e "\n[7] Проверка AAAA (IPv6) записи"
if command -v dig >/dev/null 2>&1; then
  dig api.telegram.org AAAA +short
  echo "  (если тут есть адреса, а IPv6 недоступен на хосте/в контейнере - это частая причина 'no route to host')"
fi

echo -e "\n[8] Проверка наличия IPv6 внутри контейнера"
if [ -f /proc/net/if_inet6 ]; then
  echo "  IPv6 включен в контейнере, интерфейсов: $(wc -l < /proc/net/if_inet6)"
else
  echo "  IPv6 отключен/недоступен в контейнере"
fi

echo -e "\n[9] Определение первого резолвнутого IPv4-адреса api.telegram.org"
IP=""
if command -v dig >/dev/null 2>&1; then
  IP=$(dig @8.8.8.8 api.telegram.org +short | grep -E '^[0-9]+\.' | head -1)
elif command -v nslookup >/dev/null 2>&1; then
  IP=$(nslookup api.telegram.org 8.8.8.8 2>/dev/null | awk '/^Address: / {print $2}' | tail -1)
fi

if [ -z "$IP" ]; then
  echo "  Не удалось определить IP автоматически, задайте вручную: IP=149.154.167.220"
else
  echo "  Используем IP: $IP"

  echo -e "\n[10] Ping до $IP (4 пакета)"
  if command -v ping >/dev/null 2>&1; then
    ping -c4 -W2 "$IP" || echo "  -> ping не прошел (может быть заблокирован ICMP - не всегда критично)"
  fi

  echo -e "\n[11] Traceroute до $IP"
  if command -v traceroute >/dev/null 2>&1; then
    traceroute -w1 -m 15 "$IP" 2>&1
  else
    echo "  traceroute не установлен"
  fi

  echo -e "\n[12] TCP-соединение на 443 порт (curl -v, только заголовки соединения)"
  if command -v curl >/dev/null 2>&1; then
    curl -4 -v --connect-timeout 5 "https://$IP/" -H "Host: api.telegram.org" 2>&1 | head -30
    echo "  ---"
    echo "  Аналогично, но принудительно через доменное имя (IPv4-only):"
    curl -4 -v --connect-timeout 5 "https://api.telegram.org/" 2>&1 | head -20
    echo "  ---"
    echo "  То же самое, но без ограничения на IPv4 (может уйти в IPv6):"
    curl -v --connect-timeout 5 "https://api.telegram.org/" 2>&1 | head -20
  else
    echo "  curl не установлен"
  fi
fi

echo -e "\n[13] Проверка сетевого режима контейнера (изнутри)"
echo "  hostname: $(hostname)"
echo "  ip route (если доступно):"
if command -v ip >/dev/null 2>&1; then
  ip route show 2>&1
else
  echo "  утилита ip не установлена (busybox/alpine может требовать iproute2)"
fi

echo -e "\n[14] DNS-сервер, который реально резолвит запросы Python (через getaddrinfo)"
python3 - <<'PYEOF' 2>/dev/null || echo "  python3 недоступен в контейнере"
import socket
try:
    infos = socket.getaddrinfo("api.telegram.org", 443)
    seen = set()
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.add(addr)
            print(f"  getaddrinfo -> {addr} (family={info[0]})")
except Exception as e:
    print(f"  Ошибка getaddrinfo: {e}")
PYEOF

echo -e "\n[15] Проверка реального TCP/TLS-соединения на api.telegram.org:443 через Python (обходя curl)"
python3 - <<'PYEOF' 2>/dev/null
import socket, ssl, time
host = "api.telegram.org"
try:
    t0 = time.time()
    with socket.create_connection((host, 443), timeout=5) as sock:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            print(f"  TLS OK за {time.time()-t0:.2f}с, cipher={ssock.cipher()}")
except Exception as e:
    print(f"  Соединение не удалось: {e}")
PYEOF

echo -e "\n=================================================="
echo " Диагностика завершена. Если на шаге [10]/[11] пакеты"
echo " умирают в первых 1-3 хопах внутри сети хостера - это"
echo " проблема маршрутизации/пиринга провайдера, а не DNS."
echo " Если [9] дает IP, а [15] не может установить TLS -"
echo " это подтверждает 'адрес без маршрута'."
echo "=================================================="

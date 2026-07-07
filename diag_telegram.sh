#!/usr/bin/env bash
# diag_telegram.sh — диагностика сетевого канала bot -> api.telegram.org
# Запускать ВНУТРИ контейнера bot. Ничего не меняет, только читает/пингует.

set -u
HOST="api.telegram.org"
PINNED_IP="149.154.167.220"   # то, что прибито в docker-compose extra_hosts
TIMEOUT=15
LINE="------------------------------------------------------------"

say() { printf "\n%s\n%s\n%s\n" "$LINE" "$1" "$LINE"; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- маскировка токена для вывода ---
mask() {
  local t="${1:-}"
  if [ -z "$t" ]; then echo "(пусто)"; return; fi
  echo "${t:0:6}...${t: -4}"
}

say "0. ОКРУЖЕНИЕ"
echo "date (UTC):        $(date -u '+%Y-%m-%d %H:%M:%S')"
echo "hostname:          $(hostname)"
echo "python:            $(python --version 2>&1)"
echo "TELEGRAM token:    $(mask "${TELEGRAM_BOT_TOKEN:-}")"
echo "доступные утилиты: curl=$(have curl && echo yes || echo no)  getent=$(have getent && echo yes || echo no)  nc=$(have nc && echo yes || echo no)  ping=$(have ping && echo yes || echo no)"

say "1. /etc/hosts (проверяем прибитый extra_hosts)"
grep -i "telegram" /etc/hosts || echo "(записей о telegram в /etc/hosts нет)"
echo "resolv.conf:"; cat /etc/resolv.conf 2>/dev/null || echo "(нет)"

say "2. DNS-резолв $HOST"
if have getent; then
  echo "getent hosts:"; getent hosts "$HOST" || echo "  getent не разрешил имя"
fi
python - "$HOST" <<'PY'
import socket, sys
host = sys.argv[1]
try:
    name, aliases, ips = socket.gethostbyname_ex(host)
    print("gethostbyname_ex ->", name, ips)
except Exception as e:
    print("DNS FAIL:", repr(e))
try:
    infos = {t[4][0] for t in socket.getaddrinfo(host, 443)}
    print("getaddrinfo IPs ->", sorted(infos))
except Exception as e:
    print("getaddrinfo FAIL:", repr(e))
PY

say "3. TCP-доступность до РЕЗОЛВНУТОГО адреса (порт 443)"
python - "$HOST" "$TIMEOUT" <<'PY'
import socket, sys, time
host, timeout = sys.argv[1], float(sys.argv[2])
try:
    ip = socket.gethostbyname(host)
except Exception as e:
    print("не смог резолвить:", repr(e)); raise SystemExit
t = time.time()
try:
    s = socket.create_connection((ip, 443), timeout=timeout)
    s.close()
    print(f"OK  TCP {ip}:443 connect за {round((time.time()-t)*1000)} ms")
except Exception as e:
    print(f"FAIL TCP {ip}:443 -> {repr(e)}  (ждали до {timeout}s)")
PY

say "4. TCP-доступность до ПРИБИТОГО IP $PINNED_IP:443 (extra_hosts)"
python - "$PINNED_IP" "$TIMEOUT" <<'PY'
import socket, sys, time
ip, timeout = sys.argv[1], float(sys.argv[2])
t = time.time()
try:
    s = socket.create_connection((ip, 443), timeout=timeout)
    s.close()
    print(f"OK  прибитый IP {ip}:443 отвечает за {round((time.time()-t)*1000)} ms")
except Exception as e:
    print(f"FAIL прибитый IP {ip}:443 -> {repr(e)}  <-- если тут FAIL, это и есть причина таймаутов")
PY

say "5. HTTPS-запрос к https://$HOST/ (python urllib, замер времени)"
python - "$HOST" "$TIMEOUT" <<'PY'
import urllib.request, sys, time
host, timeout = sys.argv[1], float(sys.argv[2])
url = f"https://{host}/"
t = time.time()
try:
    r = urllib.request.urlopen(url, timeout=timeout)
    print(f"OK  HTTP {r.status} за {round((time.time()-t)*1000)} ms")
except Exception as e:
    print(f"FAIL {url} -> {repr(e)}  (ждали до {timeout}s)")
PY

say "6. HTTPS через прибитый IP (эмуляция того, как ходит контейнер)"
python - "$HOST" "$PINNED_IP" "$TIMEOUT" <<'PY'
import socket, ssl, sys, time
host, ip, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
ctx = ssl.create_default_context()
t = time.time()
try:
    raw = socket.create_connection((ip, 443), timeout=timeout)
    tls = ctx.wrap_socket(raw, server_hostname=host)
    req = f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    tls.sendall(req.encode())
    data = tls.recv(200)
    tls.close()
    print(f"OK  TLS+HTTP через {ip}: {data.splitlines()[0].decode(errors='replace')} за {round((time.time()-t)*1000)} ms")
except Exception as e:
    print(f"FAIL TLS через {ip} -> {repr(e)}")
PY

say "7. Латентность: 5 замеров getMe (Bot API, как реально работает бот)"
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  python - "${TELEGRAM_BOT_TOKEN}" "$HOST" "$TIMEOUT" <<'PY'
import urllib.request, json, sys, time
token, host, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
url = f"https://{host}/bot{token}/getMe"
ok = 0
for i in range(1, 6):
    t = time.time()
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        j = json.load(r)
        ms = round((time.time()-t)*1000)
        name = j.get("result", {}).get("username", "?")
        print(f"  #{i}: OK @{name} за {ms} ms")
        ok += 1
    except Exception as e:
        print(f"  #{i}: FAIL -> {repr(e)}")
    time.sleep(0.5)
print(f"Итог getMe: {ok}/5 успешных")
PY
else
  echo "TELEGRAM_BOT_TOKEN не задан в окружении — пропускаю."
fi

say "8. getWebhookInfo (последняя ошибка глазами Telegram)"
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  python - "${TELEGRAM_BOT_TOKEN}" "$HOST" "$TIMEOUT" <<'PY'
import urllib.request, json, sys
token, host, timeout = sys.argv[1], sys.argv[2], float(sys.argv[3])
url = f"https://{host}/bot{token}/getWebhookInfo"
try:
    r = urllib.request.urlopen(url, timeout=timeout)
    j = json.load(r).get("result", {})
    for k in ("url", "pending_update_count", "last_error_date", "last_error_message", "last_synchronization_error_date"):
        print(f"  {k}: {j.get(k)}")
except Exception as e:
    print("FAIL:", repr(e))
PY
else
  echo "нет токена — пропускаю."
fi

say "9. (доп.) Проверка канала до AiTunnel (LLM/STT) — на всякий случай"
python - "$TIMEOUT" <<'PY'
import urllib.request, sys, time
timeout = float(sys.argv[1])
url = "https://api.aitunnel.ru/v1/models"
t = time.time()
try:
    r = urllib.request.urlopen(url, timeout=timeout)
    print(f"OK  AiTunnel ответил {r.status} за {round((time.time()-t)*1000)} ms")
except Exception as e:
    # 401 без ключа — это нормально, важно что канал живой
    print(f"ответ/ошибка AiTunnel: {repr(e)}")
PY

say "ГОТОВО. Как читать:"
cat <<'TXT'
- Блок 4 FAIL (прибитый 149.154.167.220 не отвечает), а блок 3/5 через DNS OK
    -> причина найдена: устаревший extra_hosts в docker-compose. IP надо обновить или снять pin.
- Блоки 3,4,5,6,7 периодически FAIL по таймауту
    -> нестабильный маршрут/блокировки до Telegram (инфраструктура провайдера/сервера).
- Всё OK и быстро (getMe 5/5, латентность низкая)
    -> таймаут был разовым сетевым моргком. Тогда единственная надёжная защита — правка кода
       (try/except + ретрай в cb_finalize_report), иначе следующий моргок снова откатит finalize.
TXT

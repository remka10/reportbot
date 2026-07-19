#!/usr/bin/env python3
"""Диагностика сетевой доступности до Telegram Bot API из контейнера бота.

Зачем: на этом сервере DNS/маршрут до api.telegram.org нестабилен — соединение
«раз через раз» и иногда полностью отваливается (Connection timeout на connect).
Скрипт проверяет, КАКОЙ путь до Telegram вообще жив, чтобы выбрать решение:
сменить IP в extra_hosts / уйти на IPv6 / поднять прокси / писать тикет хостеру.

Запуск (БЕЗ -it и без heredoc — никаких TTY-подводных камней):
    docker exec reportbot-bot-1 python3 /app/check_net.py

Никаких зависимостей — только стандартная библиотека, работает в slim-образе.
"""

import socket
import ssl
import time

# Порт HTTPS Telegram Bot API. Проверяем именно 443 — тот же порт, что и у бота.
PORT = 443
CONNECT_TIMEOUT = 5.0  # сек на попытку; «мёртвый» адрес не должен вешать скрипт

# IPv4-адреса дата-центров Telegram Bot API + контрольные точки «жив ли интернет
# вообще» (cloudflare/google). Диапазоны 149.154.167.x и 149.154.175.x — это
# основные подсети Bot API; 91.108.x — соседний диапазон Telegram.
IPV4_TARGETS = [
    ("telegram 149.154.167.220", "149.154.167.220"),  # текущий в extra_hosts
    ("telegram 149.154.167.221", "149.154.167.221"),
    ("telegram 149.154.167.222", "149.154.167.222"),
    ("telegram 149.154.175.50", "149.154.175.50"),
    ("telegram 149.154.175.100", "149.154.175.100"),
    ("telegram 91.108.4.5", "91.108.4.5"),
    ("cloudflare 1.1.1.1", "1.1.1.1"),  # контроль: жив ли исходящий интернет
    ("google 8.8.8.8", "8.8.8.8"),      # контроль: жив ли исходящий интернет
]

# IPv6-адрес api.telegram.org (тот, что отдаёт DNS на этом сервере, шаг [1]/[5]
# в check_telegram_dns.sh). Если IPv4 мёртв, а он жив — можно уйти на IPv6.
IPV6_TARGETS = [
    ("telegram IPv6", "2001:67c:4e8:f004::9"),
]


def _try_tcp(ip: str, family: int) -> tuple[bool, str]:
    """Одна попытка TCP-connect на PORT. Возвращает (успех, сообщение/время)."""
    t0 = time.time()
    try:
        # AF_INET/AF_INET6 задаём явно, чтобы проверять конкретный стек.
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        sock.connect((ip, PORT))
        sock.close()
        return True, f"{time.time() - t0:.2f}s"
    except Exception as e:  # noqa: BLE001 — нам важен любой тип сбоя, без падения
        return False, f"{type(e).__name__}: {e}"


def _try_tls_by_name(host: str) -> tuple[bool, str]:
    """Полный путь как у бота: резолв ИМЕНИ + TCP + TLS-handshake.

    Это самый показательный тест — именно так ходит aiogram. Если тут OK, то и
    бот сможет подключиться; если FAIL — воспроизводит реальную ошибку бота."""
    t0 = time.time()
    try:
        with socket.create_connection((host, PORT), timeout=CONNECT_TIMEOUT) as sock:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cipher = ssock.cipher()
                return True, f"{time.time() - t0:.2f}s cipher={cipher[0] if cipher else '?'}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> None:
    print("=" * 60)
    print(" NET CHECK: доступность Telegram Bot API из контейнера")
    print(f" {time.strftime('%Y-%m-%d %H:%M:%S')}  port={PORT}  timeout={CONNECT_TIMEOUT}s")
    print("=" * 60)

    # [1] Что реально резолвит api.telegram.org внутри контейнера (какой стек).
    print("\n[1] getaddrinfo api.telegram.org:")
    try:
        seen: set[str] = set()
        for info in socket.getaddrinfo("api.telegram.org", PORT):
            addr = info[4][0]
            if addr not in seen:
                seen.add(addr)
                fam = "IPv6" if info[0] == socket.AF_INET6 else "IPv4"
                print(f"    -> {addr}  ({fam})")
    except Exception as e:  # noqa: BLE001
        print(f"    Ошибка резолва: {e}")

    # [2] TCP по конкретным IPv4 (telegram + контрольные интернет-точки).
    print("\n[2] TCP-connect по IPv4:")
    for name, ip in IPV4_TARGETS:
        ok, msg = _try_tcp(ip, socket.AF_INET)
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {name:26} {ip:18} {msg}")

    # [3] TCP по IPv6 (если стек включён).
    print("\n[3] TCP-connect по IPv6:")
    for name, ip in IPV6_TARGETS:
        ok, msg = _try_tcp(ip, socket.AF_INET6)
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {name:26} {ip:26} {msg}")

    # [4] Полный путь как у бота: имя -> TCP -> TLS.
    print("\n[4] TLS-handshake по имени api.telegram.org (путь бота):")
    ok, msg = _try_tls_by_name("api.telegram.org")
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {msg}")

    print("\n" + "=" * 60)
    print(" Как читать:")
    print(" - cloudflare/google OK, ВСЕ telegram FAIL -> хостер режет Telegram")
    print("   (лечится прокси/тикетом хостеру, кодом не обойти).")
    print(" - какой-то другой telegram-IP OK -> меняем адрес в extra_hosts.")
    print(" - IPv6 OK, IPv4 telegram FAIL -> переключаемся на IPv6.")
    print(" - ВСЁ FAIL, включая google/cloudflare -> у контейнера нет")
    print("   исходящего интернета (docker-сеть/фаервол хоста).")
    print("=" * 60)


if __name__ == "__main__":
    main()

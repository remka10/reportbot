"""Нагрузочная проверка внешних лимитов AiTunnel: Gemini LLM и Whisper STT.

Примеры:
    python scripts/load_aitunnel.py --llm 20
    python scripts/load_aitunnel.py --llm 20 --stt 20 --audio samples/voice.ogg

Скрипт не трогает БД и Telegram. Он нужен, чтобы понять, где внешний провайдер
начинает отдавать 429/rate limit, timeout или резко увеличивает latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402


def _client(timeout: float) -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.aitunnel_api_key,
        base_url=settings.aitunnel_base_url,
        timeout=timeout,
    )


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return round(ordered[idx], 3)


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [r["duration_sec"] for r in results if r["ok"]]
    errors: dict[str, int] = {}
    for item in results:
        if item["ok"]:
            continue
        errors[item["error_type"]] = errors.get(item["error_type"], 0) + 1
    return {
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "errors": errors,
        "latency_sec": {
            "min": round(min(durations), 3) if durations else None,
            "avg": round(statistics.mean(durations), 3) if durations else None,
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
            "p99": _percentile(durations, 0.99),
            "max": round(max(durations), 3) if durations else None,
        },
    }


def _error_payload(exc: Exception) -> tuple[str, str | None]:
    status_code = getattr(exc, "status_code", None)
    if status_code:
        return f"http_{status_code}", str(exc)
    return exc.__class__.__name__, str(exc)


async def _run_llm_one(client: AsyncOpenAI, idx: int, prompt_size: int) -> dict[str, Any]:
    settings = get_settings()
    prompt = (
        "Сгенерируй короткий тестовый педагогический комментарий на русском. "
        f"Номер запроса: {idx}. "
        + ("Ученик активно работал в команде. " * prompt_size)
    )
    started = time.perf_counter()
    try:
        response = await client.chat.completions.create(
            model=settings.gemini_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=250,
        )
        text = response.choices[0].message.content or ""
        return {
            "kind": "llm",
            "idx": idx,
            "ok": True,
            "duration_sec": round(time.perf_counter() - started, 3),
            "chars": len(text),
        }
    except Exception as exc:  # noqa: BLE001 — load-test должен собирать любые ошибки
        error_type, message = _error_payload(exc)
        return {
            "kind": "llm",
            "idx": idx,
            "ok": False,
            "duration_sec": round(time.perf_counter() - started, 3),
            "error_type": error_type,
            "error": message,
        }


async def _run_stt_one(client: AsyncOpenAI, idx: int, audio_path: Path) -> dict[str, Any]:
    settings = get_settings()
    started = time.perf_counter()
    try:
        with audio_path.open("rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model=settings.whisper_model,
                file=audio_file,
                language="ru",
                response_format="text",
            )
        text = response if isinstance(response, str) else str(response)
        return {
            "kind": "stt",
            "idx": idx,
            "ok": True,
            "duration_sec": round(time.perf_counter() - started, 3),
            "chars": len(text),
        }
    except Exception as exc:  # noqa: BLE001
        error_type, message = _error_payload(exc)
        return {
            "kind": "stt",
            "idx": idx,
            "ok": False,
            "duration_sec": round(time.perf_counter() - started, 3),
            "error_type": error_type,
            "error": message,
        }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Load test AiTunnel LLM/STT limits")
    parser.add_argument("--llm", type=int, default=20, help="Количество параллельных LLM-запросов")
    parser.add_argument("--stt", type=int, default=0, help="Количество параллельных STT-запросов")
    parser.add_argument("--audio", type=Path, help="Путь к .ogg/.mp3/.wav для STT")
    parser.add_argument("--timeout", type=float, default=180.0, help="Timeout одного запроса, сек")
    parser.add_argument("--prompt-size", type=int, default=8, help="Размер тестового промпта")
    parser.add_argument("--details", action="store_true", help="Печатать результаты каждого запроса")
    args = parser.parse_args()

    if args.stt and not args.audio:
        raise SystemExit("Для --stt нужен --audio path/to/file.ogg")
    if args.audio and not args.audio.exists():
        raise SystemExit(f"Audio file not found: {args.audio}")

    client = _client(args.timeout)
    started = time.perf_counter()
    tasks = []
    tasks.extend(_run_llm_one(client, i + 1, args.prompt_size) for i in range(args.llm))
    if args.stt:
        tasks.extend(_run_stt_one(client, i + 1, args.audio) for i in range(args.stt))

    results = await asyncio.gather(*tasks)
    llm_results = [r for r in results if r["kind"] == "llm"]
    stt_results = [r for r in results if r["kind"] == "stt"]
    report = {
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "llm": _summarize(llm_results),
        "stt": _summarize(stt_results) if stt_results else {"total": 0, "skipped": True},
    }
    if args.details:
        report["details"] = results
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
"""Локальный нагрузочный тест генерации PPTX/PDF/ZIP без БД и Telegram.

Примеры:
    python scripts/load_reports.py --reports 20
    python scripts/load_reports.py --reports 20 --pdf --concurrency 2
    python scripts/load_reports.py --reports 20 --zip

PPTX/PDF — синхронные операции, поэтому скрипт запускает их через
asyncio.to_thread и показывает, насколько тяжело это для CPU/RAM контейнера.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.pptx_service import PptxService  # noqa: E402
from app.services.zip_service import ZipService  # noqa: E402


FINAL_MARKER = "=== ИТОГОВЫЙ ОТЧЁТ ==="


def _sample_report_text(idx: int) -> str:
    answers = []
    for qn in range(1, 14):
        answers.append(
            f"{qn}. Тестовый ответ {idx}.{qn}: ребёнок проявлял инициативу, "
            "работал в команде и постепенно становился увереннее."
        )
    final = (
        f"Участник {idx} за смену показал устойчивый рост: стал увереннее "
        "в коммуникации, чаще брал ответственность и научился связывать игровые "
        "задачи с реальными навыками. В командной работе проявлял спокойствие, "
        "в кризисных моментах искал решение, а не уходил от задачи."
    )
    return "\n".join(answers) + f"\n{FINAL_MARKER}\n" + final


def _sample_objects(idx: int) -> tuple[Any, Any, Any, Any]:
    report = SimpleNamespace(generated_text=_sample_report_text(idx), revision_count=0)
    student = SimpleNamespace(full_name=f"Load Test Student {idx:03d}", department_number=(idx % 9) + 1)
    shift = SimpleNamespace(
        name="Load Test Shift",
        department_id=None,
        start_date=None,
        end_date=None,
        dates="01.07 – 10.07.2026",
    )
    teacher = SimpleNamespace(full_name="Load Test Teacher")
    return report, student, shift, teacher


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
        if not item["ok"]:
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


async def _generate_one(idx: int, as_pdf: bool, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    async with semaphore:
        started = time.perf_counter()
        try:
            svc = PptxService()
            report, student, shift, teacher = _sample_objects(idx)
            if as_pdf:
                path = await asyncio.to_thread(
                    svc.generate_pdf,
                    report=report,
                    student=student,
                    shift=shift,
                    teacher=teacher,
                    shift_context="Тестовая легенда смены для нагрузочной проверки.",
                )
            else:
                path = await asyncio.to_thread(
                    svc.generate,
                    report=report,
                    student=student,
                    shift=shift,
                    teacher=teacher,
                    shift_context="Тестовая легенда смены для нагрузочной проверки.",
                )
            return {
                "idx": idx,
                "ok": True,
                "duration_sec": round(time.perf_counter() - started, 3),
                "path": str(path),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "idx": idx,
                "ok": False,
                "duration_sec": round(time.perf_counter() - started, 3),
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Load test local PPTX/PDF/ZIP generation")
    parser.add_argument("--reports", type=int, default=20, help="Количество отчётов")
    parser.add_argument("--concurrency", type=int, default=4, help="Параллельность генерации")
    parser.add_argument("--pdf", action="store_true", help="Генерировать PDF вместо PPTX")
    parser.add_argument("--zip", action="store_true", help="Дополнительно собрать ZIP одним синхронным проходом")
    parser.add_argument("--details", action="store_true", help="Печатать результаты каждого файла")
    args = parser.parse_args()

    started = time.perf_counter()
    semaphore = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(
        *(_generate_one(i + 1, args.pdf, semaphore) for i in range(args.reports))
    )

    report: dict[str, Any] = {
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "mode": "pdf" if args.pdf else "pptx",
        "concurrency": args.concurrency,
        "generation": _summarize(results),
    }

    if args.zip:
        zip_started = time.perf_counter()
        try:
            shift = _sample_objects(1)[2]
            teacher = _sample_objects(1)[3]
            items = []
            for i in range(args.reports):
                sample_report, sample_student, _, _ = _sample_objects(i + 1)
                items.append(
                    {
                        "report": sample_report,
                        "student": sample_student,
                        "shift_context": "Тестовая легенда смены.",
                        "subfolder": "Load Test",
                    }
                )
            zip_buffer, archive_name, added_count, failed_count = await asyncio.to_thread(
                ZipService().create_zip,
                report_items=items,
                shift=shift,
                teacher=teacher,
                report_service=PptxService(),
                as_pdf=args.pdf,
                archive_label="load_test_reports",
            )
            report["zip"] = {
                "ok": True,
                "duration_sec": round(time.perf_counter() - zip_started, 3),
                "archive_name": archive_name,
                "bytes": len(zip_buffer.getvalue()),
                "added_count": added_count,
                "failed_count": failed_count,
            }
        except Exception as exc:  # noqa: BLE001
            report["zip"] = {
                "ok": False,
                "duration_sec": round(time.perf_counter() - zip_started, 3),
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }

    if args.details:
        report["details"] = results
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
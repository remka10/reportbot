"""Сценарный нагрузочный тест ReportBot через БД и сервисы, без Telegram.

По умолчанию НЕ вызывает AiTunnel и НЕ запускает LibreOffice PDF: это безопасный
быстрый тест БД + репозиториев + PPTX. Для полного боевого профиля включайте
флаги явно.

Примеры:
    python scripts/load_scenario.py --users 20
    python scripts/load_scenario.py --users 20 --with-llm
    python scripts/load_scenario.py --users 20 --with-llm --with-pdf --concurrency 3
    python scripts/load_scenario.py --users 20 --no-cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database.base import AsyncSessionLocal, engine  # noqa: E402
from app.database.models import (  # noqa: E402
    Answer,
    Department,
    DialogRole,
    Question,
    Report,
    RevisionHistory,
    Shift,
    Student,
    TeacherDepartment,
    User,
    UserRole,
)
from app.repositories.answer_repo import AnswerRepository  # noqa: E402
from app.repositories.report_repo import ReportRepository  # noqa: E402
from app.services.llm_service import LLMService  # noqa: E402
from app.services.pptx_service import PptxService  # noqa: E402


FINAL_MARKER = "=== ИТОГОВЫЙ ОТЧЁТ ==="


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


def _fallback_report_text(idx: int) -> str:
    lines = []
    for qn in range(1, 14):
        lines.append(
            f"{qn}. Тестовый ответ {idx}.{qn}: ребёнок проявлял инициативу, "
            "учился взаимодействовать с командой и связывал игровые задачи с навыками."
        )
    lines.append(FINAL_MARKER)
    lines.append(
        f"Тестовый ребёнок {idx} за смену показал устойчивый рост: стал увереннее, "
        "чаще включался в командную работу и спокойнее реагировал на сложные задачи. "
        "В игровом контексте проявлял интерес к миссии департамента и постепенно "
        "переносил полученный опыт в реальные способы коммуникации."
    )
    return "\n".join(lines)


async def _ensure_questions(session) -> tuple[list[Question], list[int]]:
    result = await session.execute(
        select(Question).where(Question.is_active == True).order_by(Question.question_number)
    )
    questions = list(result.scalars().all())
    if questions:
        return questions[:13], []

    created: list[Question] = []
    for qn in range(1, 14):
        question = Question(
            block_number=((qn - 1) // 3) + 1,
            block_title=f"Load Test Block {((qn - 1) // 3) + 1}",
            question_number=qn,
            question_text=f"Load-test вопрос {qn}?",
            is_active=True,
        )
        session.add(question)
        created.append(question)
    await session.flush()
    return created, [q.id for q in created]


async def _seed(users: int, run_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        questions, created_question_ids = await _ensure_questions(session)

        shift = Shift(
            name=f"LOADTEST {run_id}",
            department_id=None,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 10),
            is_active=True,
        )
        session.add(shift)
        await session.flush()

        departments = []
        for dep_number in range(1, 10):
            dep = Department(shift_id=shift.id, department_number=dep_number)
            session.add(dep)
            departments.append(dep)
        await session.flush()
        department = departments[5]  # IT-департамент, department_number=6

        teacher_ids = []
        student_ids = []
        for idx in range(1, users + 1):
            teacher_id = 990_000_000_000 + int(time.time()) % 100_000 + idx
            teacher = User(
                id=teacher_id,
                username=f"loadtest_{run_id}_{idx}",
                full_name=f"Load Test Teacher {idx}",
                role=UserRole.teacher,
                is_active=True,
            )
            student = Student(
                full_name=f"Load Test Student {idx:03d}",
                shift_id=shift.id,
                department_id=department.id,
                position=idx,
            )
            session.add_all([teacher, student])
            await session.flush()
            session.add(
                TeacherDepartment(
                    teacher_id=teacher.id,
                    department_id=department.id,
                    shift_context="Load-test контекст смены: дети строили цифровую систему Корпорации.",
                )
            )
            teacher_ids.append(teacher.id)
            student_ids.append(student.id)

        await session.commit()
        return {
            "shift_id": shift.id,
            "department_id": department.id,
            "teacher_ids": teacher_ids,
            "student_ids": student_ids,
            "question_ids": [q.id for q in questions],
            "created_question_ids": created_question_ids,
        }


async def _one_user_flow(
    idx: int,
    seed: dict[str, Any],
    with_llm: bool,
    with_pdf: bool,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        started = time.perf_counter()
        teacher_id = seed["teacher_ids"][idx - 1]
        student_id = seed["student_ids"][idx - 1]
        shift_id = seed["shift_id"]
        try:
            async with AsyncSessionLocal() as session:
                answer_repo = AnswerRepository(session)
                for pos, question_id in enumerate(seed["question_ids"], start=1):
                    await answer_repo.upsert(
                        teacher_id=teacher_id,
                        student_id=student_id,
                        question_id=question_id,
                        answer_text=(
                            f"Load-test ответ пользователя {idx} на вопрос {pos}: "
                            "ребёнок активно участвовал, пробовал новое и работал с командой."
                        ),
                    )

                qa_pairs = await answer_repo.get_qa_pairs_for_report(teacher_id, student_id)
                if with_llm:
                    generated_text = await LLMService().generate_report(
                        qa_pairs=qa_pairs,
                        shift_context="Департамент создавал цифровую защиту Корпорации.",
                        student_name=f"Load Test Student {idx:03d}",
                    )
                else:
                    generated_text = _fallback_report_text(idx)

                report_repo = ReportRepository(session)
                report = await report_repo.create(
                    teacher_id=teacher_id,
                    student_id=student_id,
                    shift_id=shift_id,
                    generated_text=generated_text,
                )
                await report_repo.add_revision_message(
                    report_id=report.id,
                    role=DialogRole.assistant,
                    content=generated_text,
                )
                await report_repo.finalize(report.id)
                await session.commit()

            async with AsyncSessionLocal() as session:
                report = await session.get(Report, report.id)
                student = await session.get(Student, student_id)
                shift = await session.get(Shift, shift_id)
                teacher = await session.get(User, teacher_id)
                if not report or not student or not shift or not teacher:
                    raise RuntimeError("Seeded objects not found after commit")
                student.department_number = 6
                svc = PptxService()
                if with_pdf:
                    output_path = await asyncio.to_thread(
                        svc.generate_pdf,
                        report=report,
                        student=student,
                        shift=shift,
                        teacher=teacher,
                        shift_context="Департамент создавал цифровую защиту Корпорации.",
                    )
                else:
                    output_path = await asyncio.to_thread(
                        svc.generate,
                        report=report,
                        student=student,
                        shift=shift,
                        teacher=teacher,
                        shift_context="Департамент создавал цифровую защиту Корпорации.",
                    )

            return {
                "idx": idx,
                "ok": True,
                "duration_sec": round(time.perf_counter() - started, 3),
                "report_id": report.id,
                "output": str(output_path),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "idx": idx,
                "ok": False,
                "duration_sec": round(time.perf_counter() - started, 3),
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }


async def _cleanup(seed: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(RevisionHistory).where(RevisionHistory.report_id.in_(select(Report.id).where(Report.shift_id == seed["shift_id"]))))
        await session.execute(delete(Report).where(Report.shift_id == seed["shift_id"]))
        await session.execute(delete(Answer).where(Answer.student_id.in_(seed["student_ids"])))
        await session.execute(delete(TeacherDepartment).where(TeacherDepartment.department_id == seed["department_id"]))
        await session.execute(delete(Student).where(Student.id.in_(seed["student_ids"])))
        await session.execute(delete(Department).where(Department.shift_id == seed["shift_id"]))
        await session.execute(delete(Shift).where(Shift.id == seed["shift_id"]))
        await session.execute(delete(User).where(User.id.in_(seed["teacher_ids"])))
        if seed.get("created_question_ids"):
            await session.execute(delete(Question).where(Question.id.in_(seed["created_question_ids"])))
        await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run 20-user ReportBot service scenario")
    parser.add_argument("--users", type=int, default=20, help="Количество параллельных пользователей")
    parser.add_argument("--concurrency", type=int, default=5, help="Параллельность сценариев")
    parser.add_argument("--with-llm", action="store_true", help="Вызывать реальный Gemini/AiTunnel")
    parser.add_argument("--with-pdf", action="store_true", help="Генерировать PDF через LibreOffice вместо PPTX")
    parser.add_argument("--no-cleanup", action="store_true", help="Не удалять тестовые записи из БД")
    parser.add_argument("--details", action="store_true", help="Печатать результат каждого пользователя")
    args = parser.parse_args()

    run_id = time.strftime("%Y%m%d_%H%M%S")
    started = time.perf_counter()
    seed = await _seed(args.users, run_id)
    semaphore = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(
        *(
            _one_user_flow(i + 1, seed, args.with_llm, args.with_pdf, semaphore)
            for i in range(args.users)
        )
    )
    cleaned = False
    if not args.no_cleanup:
        await _cleanup(seed)
        cleaned = True
    await engine.dispose()

    report: dict[str, Any] = {
        "run_id": run_id,
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "users": args.users,
        "concurrency": args.concurrency,
        "with_llm": args.with_llm,
        "with_pdf": args.with_pdf,
        "cleanup": cleaned,
        "summary": _summarize(results),
    }
    if args.details:
        report["details"] = results
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
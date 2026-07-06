import logging
import secrets
from collections import deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Deque, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.base import get_session
from app.services import model_settings

from app.database.models import (
    Answer,
    DEPARTMENTS,
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

router = APIRouter(prefix="/admin", tags=["admin-panel"])
security = HTTPBasic()
logger = logging.getLogger(__name__)

MAX_MEMORY_LOGS = 1000
MEMORY_LOGS: Deque[dict[str, Any]] = deque(maxlen=MAX_MEMORY_LOGS)


class MemoryLogHandler(logging.Handler):
    """Хранит последние записи логов текущего процесса для страницы /admin."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            MEMORY_LOGS.appendleft(
                {
                    "created_at": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="seconds"),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": self.format(record),
                }
            )
        except Exception:
            pass


def install_memory_log_handler() -> None:
    """Подключается из app.main после logging.basicConfig(). Идемпотентно."""
    root = logging.getLogger()
    if any(isinstance(handler, MemoryLogHandler) for handler in root.handlers):
        return
    handler = MemoryLogHandler(level=logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.admin_panel_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.admin_panel_password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


AdminOnly = Depends(require_admin)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    username: Optional[str] = Field(default=None, max_length=64)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class ShiftUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None


class DepartmentContextUpdate(BaseModel):
    shift_context: str = ""


class StudentUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    department_id: Optional[int] = None
    position: Optional[int] = None


class QuestionUpdate(BaseModel):
    block_number: Optional[int] = None
    block_title: Optional[str] = None
    question_number: Optional[int] = None
    question_text: Optional[str] = Field(default=None, min_length=1)
    is_active: Optional[bool] = None


class AnswerUpdate(BaseModel):
    answer_text: Optional[str] = None
    raw_audio_transcription: Optional[str] = None


class ReportUpdate(BaseModel):
    generated_text: Optional[str] = None
    is_finalized: Optional[bool] = None


class ModelChoiceUpdate(BaseModel):
    area: str = Field(..., description="Область переключения: generation | context")
    choice: str = Field(..., description="Ключ модели: gemini | haiku")



def dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value if user.role else None,
        "is_active": user.is_active,
        "created_at": dt(user.created_at),
        "created_by": user.created_by,
    }


@router.get("", response_class=HTMLResponse, dependencies=[AdminOnly])
@router.get("/", response_class=HTMLResponse, dependencies=[AdminOnly])
async def admin_page() -> HTMLResponse:
    template_path = Path(__file__).parent / "templates" / "admin.html"
    return HTMLResponse(template_path.read_text(encoding="utf-8"))


@router.get("/api/overview", dependencies=[AdminOnly])
async def overview(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    users_total = await session.scalar(select(func.count()).select_from(User)) or 0
    users_active = await session.scalar(select(func.count()).select_from(User).where(User.is_active == True)) or 0
    shifts_active = await session.scalar(select(func.count()).select_from(Shift).where(Shift.is_active == True)) or 0
    students_total = await session.scalar(select(func.count()).select_from(Student)) or 0
    answers_total = await session.scalar(select(func.count()).select_from(Answer)) or 0
    reports_total = await session.scalar(select(func.count()).select_from(Report)) or 0
    reports_finalized = await session.scalar(select(func.count()).select_from(Report).where(Report.is_finalized == True)) or 0
    revisions_total = await session.scalar(select(func.count()).select_from(RevisionHistory)) or 0

    latest_reports_result = await session.execute(
        select(Report, Student.full_name, Shift.name)
        .join(Student, Student.id == Report.student_id)
        .join(Shift, Shift.id == Report.shift_id)
        .order_by(desc(Report.id))
        .limit(8)
    )
    latest_reports = [
        {
            "id": report.id,
            "student_name": student_name,
            "shift_name": shift_name,
            "is_finalized": report.is_finalized,
            "revision_count": report.revision_count,
            "created_at": dt(report.created_at),
        }
        for report, student_name, shift_name in latest_reports_result.all()
    ]
    return {
        "cards": {
            "users_total": users_total,
            "users_active": users_active,
            "shifts_active": shifts_active,
            "students_total": students_total,
            "answers_total": answers_total,
            "reports_total": reports_total,
            "reports_finalized": reports_finalized,
            "revisions_total": revisions_total,
        },
        "latest_reports": latest_reports,
    }


@router.get("/api/users", dependencies=[AdminOnly])
async def users(q: str = "", session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    stmt = select(User).order_by(User.is_active.desc(), User.role, User.username, User.id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((User.full_name.ilike(like)) | (User.username.ilike(like)))
    result = await session.execute(stmt)
    return [user_to_dict(user) for user in result.scalars().all()]


@router.patch("/api/users/{user_id}", dependencies=[AdminOnly])
async def update_user(user_id: int, payload: UserUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, key, value.lstrip("@") if key == "username" and value else value)
    await session.commit()
    await session.refresh(user)
    return user_to_dict(user)


@router.get("/api/shifts", dependencies=[AdminOnly])
async def shifts(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    result = await session.execute(select(Shift).order_by(Shift.start_date.desc(), Shift.id.desc()))
    return [
        {
            "id": shift.id,
            "name": shift.name,
            "start_date": dt(shift.start_date),
            "end_date": dt(shift.end_date),
            "is_active": shift.is_active,
            "created_at": dt(shift.created_at),
            "created_by": shift.created_by,
        }
        for shift in result.scalars().all()
    ]


@router.patch("/api/shifts/{shift_id}", dependencies=[AdminOnly])
async def update_shift(shift_id: int, payload: ShiftUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    shift = await session.get(Shift, shift_id)
    if shift is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(shift, key, value)
    await session.commit()
    return {"ok": True}


@router.get("/api/departments", dependencies=[AdminOnly])
async def departments(shift_id: int | None = None, session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    stmt = select(Department, Shift.name).join(Shift, Shift.id == Department.shift_id)
    if shift_id:
        stmt = stmt.where(Department.shift_id == shift_id)
    stmt = stmt.order_by(Shift.start_date.desc(), Department.department_number)
    rows = (await session.execute(stmt)).all()
    items: list[dict[str, Any]] = []
    for department, shift_name in rows:
        context = await session.scalar(
            select(TeacherDepartment.shift_context)
            .where(
                TeacherDepartment.department_id == department.id,
                TeacherDepartment.shift_context.isnot(None),
                TeacherDepartment.shift_context != "",
            )
            .limit(1)
        )
        students_count = await session.scalar(
            select(func.count()).select_from(Student).where(Student.department_id == department.id)
        ) or 0
        meta = DEPARTMENTS.get(department.department_number, {})
        items.append(
            {
                "id": department.id,
                "shift_id": department.shift_id,
                "shift_name": shift_name,
                "department_number": department.department_number,
                "name": meta.get("name", department.name),
                "emoji": meta.get("emoji", "🏢"),
                "hex": meta.get("hex", "E84130"),
                "students_count": students_count,
                "shift_context": context or "",
            }
        )
    return items


@router.patch("/api/departments/{department_id}/context", dependencies=[AdminOnly])
async def update_department_context(
    department_id: int,
    payload: DepartmentContextUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    department = await session.get(Department, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    rows = (await session.execute(select(TeacherDepartment).where(TeacherDepartment.department_id == department_id))).scalars().all()
    if not rows:
        admin_user = await session.scalar(select(User).where(User.role == UserRole.admin).order_by(User.id).limit(1))
        if admin_user is None:
            raise HTTPException(status_code=400, detail="No admin user found to attach context")
        row = TeacherDepartment(teacher_id=admin_user.id, department_id=department_id)
        session.add(row)
        rows = [row]
    for row in rows:
        row.shift_context = payload.shift_context
    await session.commit()
    return {"ok": True}


@router.get("/api/students", dependencies=[AdminOnly])
async def students(
    q: str = "",
    shift_id: int | None = None,
    department_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    answered_subq = (
        select(Answer.student_id, func.count(func.distinct(Answer.question_id)).label("answered_count"))
        .where(Answer.answer_text.isnot(None))
        .group_by(Answer.student_id)
        .subquery()
    )
    reports_subq = (
        select(
            Report.student_id,
            func.count(Report.id).label("reports_count"),
            func.count(Report.id).filter(Report.is_finalized == True).label("finalized_count"),
        )
        .group_by(Report.student_id)
        .subquery()
    )
    stmt = (
        select(Student, Shift.name, Department.department_number, answered_subq.c.answered_count, reports_subq.c.reports_count, reports_subq.c.finalized_count)
        .join(Shift, Shift.id == Student.shift_id)
        .outerjoin(Department, Department.id == Student.department_id)
        .outerjoin(answered_subq, answered_subq.c.student_id == Student.id)
        .outerjoin(reports_subq, reports_subq.c.student_id == Student.id)
        .order_by(Shift.start_date.desc(), Department.department_number, Student.position, Student.full_name)
    )
    if q:
        stmt = stmt.where(Student.full_name.ilike(f"%{q.strip()}%"))
    if shift_id:
        stmt = stmt.where(Student.shift_id == shift_id)
    if department_id:
        stmt = stmt.where(Student.department_id == department_id)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": student.id,
            "full_name": student.full_name,
            "shift_id": student.shift_id,
            "shift_name": shift_name,
            "department_id": student.department_id,
            "department_number": department_number,
            "department_name": DEPARTMENTS.get(department_number or 0, {}).get("name") if department_number else None,
            "position": student.position,
            "answered_count": answered_count or 0,
            "reports_count": reports_count or 0,
            "has_finalized_report": bool(finalized_count),
        }
        for student, shift_name, department_number, answered_count, reports_count, finalized_count in rows
    ]


@router.patch("/api/students/{student_id}", dependencies=[AdminOnly])
async def update_student(student_id: int, payload: StudentUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    student = await session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, key, value)
    await session.commit()
    return {"ok": True}


@router.get("/api/questions", dependencies=[AdminOnly])
async def questions(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    result = await session.execute(select(Question).order_by(Question.question_number, Question.id))
    return [
        {
            "id": question.id,
            "block_number": question.block_number,
            "block_title": question.block_title,
            "question_number": question.question_number,
            "question_text": question.question_text,
            "is_active": question.is_active,
        }
        for question in result.scalars().all()
    ]


@router.patch("/api/questions/{question_id}", dependencies=[AdminOnly])
async def update_question(question_id: int, payload: QuestionUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    question = await session.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(question, key, value)
    await session.commit()
    return {"ok": True}


@router.get("/api/answers", dependencies=[AdminOnly])
async def answers(
    student_id: int | None = None,
    q: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(Answer, Student.full_name, Question.question_number, Question.question_text, User.full_name.label("teacher_name"))
        .join(Student, Student.id == Answer.student_id)
        .join(Question, Question.id == Answer.question_id)
        .outerjoin(User, User.id == Answer.teacher_id)
        .order_by(desc(Answer.updated_at), desc(Answer.created_at), desc(Answer.id))
        .limit(limit)
    )
    if student_id:
        stmt = stmt.where(Answer.student_id == student_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((Student.full_name.ilike(like)) | (Answer.answer_text.ilike(like)) | (Question.question_text.ilike(like)))
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": answer.id,
            "student_id": answer.student_id,
            "student_name": student_name,
            "question_id": answer.question_id,
            "question_number": question_number,
            "question_text": question_text,
            "answer_text": answer.answer_text,
            "raw_audio_transcription": answer.raw_audio_transcription,
            "teacher_id": answer.teacher_id,
            "teacher_name": teacher_name,
            "created_at": dt(answer.created_at),
            "updated_at": dt(answer.updated_at),
        }
        for answer, student_name, question_number, question_text, teacher_name in rows
    ]


@router.patch("/api/answers/{answer_id}", dependencies=[AdminOnly])
async def update_answer(answer_id: int, payload: AnswerUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    answer = await session.get(Answer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(answer, key, value)
    answer.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True}


@router.get("/api/reports", dependencies=[AdminOnly])
async def reports(
    q: str = "",
    finalized: Optional[bool] = None,
    shift_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(Report, Student.full_name, Shift.name, User.full_name.label("teacher_name"))
        .join(Student, Student.id == Report.student_id)
        .join(Shift, Shift.id == Report.shift_id)
        .outerjoin(User, User.id == Report.teacher_id)
        .order_by(desc(Report.id))
        .limit(limit)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((Student.full_name.ilike(like)) | (Report.generated_text.ilike(like)))
    if finalized is not None:
        stmt = stmt.where(Report.is_finalized == finalized)
    if shift_id:
        stmt = stmt.where(Report.shift_id == shift_id)
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": report.id,
            "teacher_id": report.teacher_id,
            "teacher_name": teacher_name,
            "student_id": report.student_id,
            "student_name": student_name,
            "shift_id": report.shift_id,
            "shift_name": shift_name,
            "generated_text_preview": (report.generated_text or "")[:220],
            "revision_count": report.revision_count,
            "is_finalized": report.is_finalized,
            "docx_file_path": report.docx_file_path,
            "created_at": dt(report.created_at),
            "finalized_at": dt(report.finalized_at),
        }
        for report, student_name, shift_name, teacher_name in rows
    ]


@router.get("/api/reports/{report_id}", dependencies=[AdminOnly])
async def report_detail(report_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Report, Student.full_name, Shift.name)
            .join(Student, Student.id == Report.student_id)
            .join(Shift, Shift.id == Report.shift_id)
            .where(Report.id == report_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report, student_name, shift_name = row
    history = (
        await session.execute(
            select(RevisionHistory)
            .where(RevisionHistory.report_id == report_id)
            .order_by(RevisionHistory.created_at, RevisionHistory.id)
        )
    ).scalars().all()
    return {
        "id": report.id,
        "student_name": student_name,
        "shift_name": shift_name,
        "generated_text": report.generated_text or "",
        "revision_count": report.revision_count,
        "is_finalized": report.is_finalized,
        "created_at": dt(report.created_at),
        "finalized_at": dt(report.finalized_at),
        "history": [
            {
                "id": item.id,
                "role": item.role.value if isinstance(item.role, DialogRole) else str(item.role),
                "content": item.content,
                "created_at": dt(item.created_at),
            }
            for item in history
        ],
    }


@router.patch("/api/reports/{report_id}", dependencies=[AdminOnly])
async def update_report(report_id: int, payload: ReportUpdate, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    data = payload.model_dump(exclude_unset=True)
    if "generated_text" in data:
        report.generated_text = data["generated_text"]
        report.revision_count += 1
    if "is_finalized" in data:
        report.is_finalized = data["is_finalized"]
        report.finalized_at = datetime.now(timezone.utc) if data["is_finalized"] else None
    await session.commit()
    return {"ok": True}


@router.get("/api/models", dependencies=[AdminOnly])
async def get_models() -> dict[str, Any]:
    """Текущий выбор нейросетей и доступные опции для быстрой смены."""
    return model_settings.snapshot()


@router.patch("/api/models", dependencies=[AdminOnly])
async def update_model(payload: ModelChoiceUpdate) -> dict[str, Any]:
    """Быстрое переключение нейросети для области generation | context."""
    try:
        model_settings.set_choice(payload.area, payload.choice)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return model_settings.snapshot()


@router.get("/api/logs", dependencies=[AdminOnly])
async def logs(level: str = "") -> list[dict[str, Any]]:

    level = level.upper().strip()
    if not level:
        return list(MEMORY_LOGS)
    return [item for item in MEMORY_LOGS if item["level"] == level]
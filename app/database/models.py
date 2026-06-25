"""
SQLAlchemy-модели ReportBot.
Все модели — чистые ORM-декларации, без бизнес-методов.
"""
import enum
from datetime import datetime, date as date_type
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum, ForeignKey,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base


# ─── Enums ────────────────────────────────────────────────────────────────────
class UserRole(str, enum.Enum):
    admin     = "admin"
    moderator = "moderator"
    teacher   = "teacher"


class DialogRole(str, enum.Enum):
    assistant = "assistant"
    user      = "user"


# ─── Справочник департаментов ─────────────────────────────────────────────────
# department_id используется в таблице shifts.
# 1 — Управление          #C0392B  красный
# 2 — Общественные связи  #2980B9  синий
# 3 — Инженерный          #27AE60  зелёный
# 4 — Департамент Икс     #8E44AD  фиолетовый
# 5 — Научный             #D35400  оранжевый
# 6 — IT                  #16A085  бирюзовый
# 7 — Дизайн              #F39C12  янтарный
# 8 — Проект 11           #7F8C8D  серый
# 9 — Летово Джун         #1ABC9C  мятный   ← НОВЫЙ
DEPARTMENTS: dict[int, dict] = {
    1: {"name": "Департамент управления",          "hex": "C0392B"},
    2: {"name": "Департамент общественных связей", "hex": "2980B9"},
    3: {"name": "Инженерный департамент",          "hex": "27AE60"},
    4: {"name": "Департамент Икс",                 "hex": "8E44AD"},
    5: {"name": "Научный департамент",             "hex": "D35400"},
    6: {"name": "IT-департамент",                  "hex": "16A085"},
    7: {"name": "Департамент дизайна",             "hex": "F39C12"},
    8: {"name": "Проект 11",                       "hex": "7F8C8D"},
    9: {"name": "Летово Джун",                     "hex": "1ABC9C"},
}


def get_department_name(department_id: int) -> str:
    return DEPARTMENTS.get(department_id, {}).get("name", f"Департамент {department_id}")


def get_department_hex(department_id: int) -> str:
    return DEPARTMENTS.get(department_id, {}).get("hex", "E84130")


# ─── Таблицы ──────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id:          Mapped[int]           = mapped_column(BigInteger, primary_key=True)
    username:    Mapped[Optional[str]] = mapped_column(String(64),  nullable=True)
    full_name:   Mapped[str]           = mapped_column(String(256), nullable=False)
    role:        Mapped[UserRole]      = mapped_column(Enum(UserRole), nullable=False)
    is_active:   Mapped[bool]          = mapped_column(Boolean, default=True, nullable=False)
    created_at:  Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by:  Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)


class Shift(Base):
    __tablename__ = "shifts"

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:          Mapped[str]           = mapped_column(String(128), nullable=False)
    # ИСПРАВЛЕНО: nullable=False — соответствует миграции 0001 (было nullable=True)
    department_id: Mapped[int]           = mapped_column(Integer, nullable=False)
    # ИСПРАВЛЕНО: nullable=False — соответствует миграции 0001 (было nullable=True)
    start_date:    Mapped[date_type]     = mapped_column(Date, nullable=False)
    # ИСПРАВЛЕНО: nullable=False — соответствует миграции 0001 (было nullable=True)
    end_date:      Mapped[date_type]     = mapped_column(Date, nullable=False)
    is_active:     Mapped[bool]          = mapped_column(Boolean, default=True, nullable=False)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by:    Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

    @property
    def department_name(self) -> str:
        return get_department_name(self.department_id or 0)

    @property
    def department_color(self) -> str:
        return get_department_hex(self.department_id or 0)


class TeacherShift(Base):
    __tablename__ = "teacher_shifts"

    teacher_id:    Mapped[int]           = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    shift_id:      Mapped[int]           = mapped_column(Integer,    ForeignKey("shifts.id"), primary_key=True)
    shift_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Student(Base):
    __tablename__ = "students"

    id:        Mapped[int]           = mapped_column(Integer,     primary_key=True, autoincrement=True)
    full_name: Mapped[str]           = mapped_column(String(256), nullable=False)
    shift_id:  Mapped[int]           = mapped_column(Integer,     ForeignKey("shifts.id"), nullable=False)
    position:  Mapped[Optional[int]] = mapped_column(Integer,     nullable=True)


class Question(Base):
    __tablename__ = "questions"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    block_number:    Mapped[Optional[int]] = mapped_column(Integer,     nullable=True)
    block_title:     Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    question_number: Mapped[int]           = mapped_column(Integer,     nullable=False)
    question_text:   Mapped[str]           = mapped_column(Text,        nullable=False)
    is_active:       Mapped[bool]          = mapped_column(Boolean, default=True, nullable=False)


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("teacher_id", "student_id", "question_id", name="uq_answer"),
    )

    id:                      Mapped[int]           = mapped_column(Integer,    primary_key=True, autoincrement=True)
    teacher_id:              Mapped[int]           = mapped_column(BigInteger, ForeignKey("users.id"),     nullable=False)
    student_id:              Mapped[int]           = mapped_column(Integer,    ForeignKey("students.id"), nullable=False)
    question_id:             Mapped[int]           = mapped_column(Integer,    ForeignKey("questions.id"), nullable=False)
    answer_text:             Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_audio_transcription: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at:              Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:              Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Report(Base):
    __tablename__ = "reports"

    id:             Mapped[int]           = mapped_column(Integer,    primary_key=True, autoincrement=True)
    teacher_id:     Mapped[int]           = mapped_column(BigInteger, ForeignKey("users.id"),    nullable=False)
    student_id:     Mapped[int]           = mapped_column(Integer,    ForeignKey("students.id"), nullable=False)
    shift_id:       Mapped[int]           = mapped_column(Integer,    ForeignKey("shifts.id"),   nullable=False)
    generated_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revision_count: Mapped[int]           = mapped_column(Integer, default=0, nullable=False)
    is_finalized:   Mapped[bool]          = mapped_column(Boolean, default=False, nullable=False)
    docx_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RevisionHistory(Base):
    __tablename__ = "revision_history"

    id:         Mapped[int]        = mapped_column(Integer,    primary_key=True, autoincrement=True)
    report_id:  Mapped[int]        = mapped_column(Integer,    ForeignKey("reports.id"), nullable=False)
    role:       Mapped[DialogRole] = mapped_column(Enum(DialogRole), nullable=False)
    content:    Mapped[str]        = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime]   = mapped_column(DateTime(timezone=True), server_default=func.now())
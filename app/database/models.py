import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    admin = "admin"
    moderator = "moderator"
    teacher = "teacher"


class DialogRole(str, enum.Enum):
    assistant = "assistant"
    user = "user"


# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

DEPARTMENTS: dict[int, str] = {
    1: "Департамент управления",
    2: "Департамент общественных связей",
    3: "Инженерный департамент",
    4: "Департамент Икс",
    5: "Научный департамент",
    6: "IT-департамент",
    7: "Департамент дизайна",
    8: "Проект 11",
}


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(Base):
    """Пользователи бота. id = Telegram user_id."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", create_type=True),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    teacher_shifts: Mapped[list["TeacherShift"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
    )
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="teacher",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Shift
# ---------------------------------------------------------------------------

class Shift(Base):
    """Смены лагеря."""

    __tablename__ = "shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    department_id: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    teacher_shifts: Mapped[list["TeacherShift"]] = relationship(
        back_populates="shift",
        cascade="all, delete-orphan",
    )
    students: Mapped[list["Student"]] = relationship(
        back_populates="shift",
        cascade="all, delete-orphan",
    )
    reports: Mapped[list["Report"]] = relationship(back_populates="shift")

    @property
    def department_name(self) -> str:
        return DEPARTMENTS.get(self.department_id, f"Департамент {self.department_id}")


# ---------------------------------------------------------------------------
# TeacherShift
# ---------------------------------------------------------------------------

class TeacherShift(Base):
    """Привязка педагога к смене + контекст смены."""

    __tablename__ = "teacher_shifts"

    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    shift_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shifts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Контекст вводится педагогом один раз на смену; используется в промте LLM
    shift_context: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    teacher: Mapped["User"] = relationship(back_populates="teacher_shifts")
    shift: Mapped["Shift"] = relationship(back_populates="teacher_shifts")


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------

class Student(Base):
    """Учащиеся (дети) в смене."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    shift_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shifts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Порядковый номер в группе — для сортировки в списке
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    shift: Mapped["Shift"] = relationship(back_populates="students")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Question
# ---------------------------------------------------------------------------

class Question(Base):
    """19 вопросов (одинаковые для всех департаментов)."""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    block_number: Mapped[int] = mapped_column(Integer, nullable=False)
    block_title: Mapped[str] = mapped_column(String(256), nullable=False)
    # question_number — глобальный порядковый номер 1..19
    question_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    answers: Mapped[list["Answer"]] = relationship(back_populates="question")


# ---------------------------------------------------------------------------
# Answer
# ---------------------------------------------------------------------------

class Answer(Base):
    """Ответы педагога на вопросы по конкретному ребёнку."""

    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "student_id", "question_id",
            name="uq_answer",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Финальный текст ответа (после очистки STT или прямой ввод)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Сырая транскрипция до очистки LLM — сохраняем для аудита
    raw_audio_transcription: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    teacher: Mapped["User"] = relationship(back_populates="answers")
    student: Mapped["Student"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship(back_populates="answers")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class Report(Base):
    """Сгенерированные отчёты на детей."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("shifts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Последняя версия текста от LLM
    generated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Счётчик итераций правок
    revision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Путь к сгенерированному DOCX-файлу на диске
    docx_file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    teacher: Mapped["User"] = relationship(back_populates="reports")
    student: Mapped["Student"] = relationship(back_populates="reports")
    shift: Mapped["Shift"] = relationship(back_populates="reports")
    revision_history: Mapped[list["RevisionHistory"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="RevisionHistory.created_at",
    )


# ---------------------------------------------------------------------------
# RevisionHistory
# ---------------------------------------------------------------------------

class RevisionHistory(Base):
    """История диалога правок для контекста LLM."""

    __tablename__ = "revision_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "assistant" = версия от LLM, "user" = запрос педагога на правку
    role: Mapped[DialogRole] = mapped_column(
        Enum(DialogRole, name="dialog_role", create_type=True),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    report: Mapped["Report"] = relationship(back_populates="revision_history")
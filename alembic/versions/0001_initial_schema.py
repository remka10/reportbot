"""Full schema with seed data

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

QUESTIONS = [
    (1, "1. Адаптация — Первый день", 1, "Расскажи, как прошёл твой первый день? Что запомнилось больше всего?"),
    (1, "1. Адаптация — Первый день", 2, "Было ли тебе комфортно в первый день, удалось ли познакомиться с ребятами?"),
    (2, "2. Hard Skills — Профессиональные навыки", 3, "Чему новому ты научился(ась) за смену? Какие навыки приобрёл(а)?"),
    (2, "2. Hard Skills — Профессиональные навыки", 4, "Расскажи о самом интересном проекте или задаче на смене."),
    (2, "2. Hard Skills — Профессиональные навыки", 5, "Что давалось сложнее всего с точки зрения профессиональных задач?"),
    (3, "3. Soft Skills — Личные качества", 6, "Как ты справлялся(ась) с трудностями и нестандартными ситуациями?"),
    (3, "3. Soft Skills — Личные качества", 7, "Расскажи о своей роли в командной работе."),
    (3, "3. Soft Skills — Личные качества", 8, "Что изменилось в тебе за время смены?"),
    (4, "4. Социализация", 9, "Как складывались отношения с другими участниками, появились ли новые друзья?"),
    (4, "4. Социализация", 10, "Участвовал(а) ли ты в мероприятиях за пределами основной программы?"),
    (4, "4. Социализация", 11, "Были ли конфликты в команде, как их решал(а)?"),
    (5, "5. Рефлексия", 12, "Что тебе больше всего понравилось на смене, а что разочаровало?"),
    (5, "5. Рефлексия", 13, "Если бы ты мог(ла) что-то изменить в смене, что бы это было?"),
    (6, "6. Итоги и планы", 14, "Какой главный вывод ты сделал(а) по итогам смены?"),
    (6, "6. Итоги и планы", 15, "Как планируешь применять полученные знания и навыки?"),
    (6, "6. Итоги и планы", 16, "Порекомендовал(а) бы ты эту смену своим друзьям и почему?"),
    (6, "6. Итоги и планы", 17, "Какие цели ставишь перед собой после смены?"),
    (6, "6. Итоги и планы", 18, "Есть ли что-то, о чём хочешь рассказать отдельно?"),
    (6, "6. Итоги и планы", 19, "Оцени смену по 10-балльной шкале и объясни свою оценку."),
]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("role", sa.Enum("admin", "moderator", "teacher", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_table(
        "shifts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("department_id", sa.Integer, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.BigInteger, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("department_id BETWEEN 1 AND 9", name="shifts_department_id_check"),
    )
    op.create_table(
        "teacher_shifts",
        sa.Column("teacher_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("shifts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("shift_context", sa.Text, nullable=True),
    )
    op.create_table(
        "students",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("block_number", sa.Integer, nullable=False),
        sa.Column("block_title", sa.String(256), nullable=False),
        sa.Column("question_number", sa.Integer, nullable=False),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("question_number", name="uq_question_number"),
    )
    op.create_table(
        "answers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("teacher_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("answer_text", sa.Text, nullable=True),
        sa.Column("raw_audio_transcription", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("teacher_id", "student_id", "question_id", name="uq_answer"),
    )
    op.create_index("ix_answers_teacher_student", "answers", ["teacher_id", "student_id"])
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("teacher_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.Integer, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("shifts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("generated_text", sa.Text, nullable=True),
        sa.Column("revision_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("is_finalized", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("docx_file_path", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reports_teacher_shift", "reports", ["teacher_id", "shift_id"])
    op.create_table(
        "revision_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer, sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Enum("assistant", "user", name="dialog_role"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_revision_history_report", "revision_history", ["report_id"])

    questions_table = sa.table(
        "questions",
        sa.column("block_number", sa.Integer),
        sa.column("block_title", sa.String),
        sa.column("question_number", sa.Integer),
        sa.column("question_text", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        questions_table,
        [{"block_number": bn, "block_title": bt, "question_number": qn, "question_text": qt, "is_active": True}
         for bn, bt, qn, qt in QUESTIONS],
    )


def downgrade() -> None:
    op.drop_table("revision_history")
    op.drop_table("reports")
    op.drop_table("answers")
    op.drop_table("questions")
    op.drop_table("students")
    op.drop_table("teacher_shifts")
    op.drop_table("shifts")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role")
    op.execute("DROP TYPE IF EXISTS dialog_role")

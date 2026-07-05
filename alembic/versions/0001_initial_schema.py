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

# Анкета для ПЕДАГОГА (а не для ребёнка): педагог отвечает на вопросы о ребёнке.
# Формат question_text: «<b>Название вопроса</b>\n\nописание и подсказка как отвечать».
QUESTIONS = [
    (1, "Блок 1. Характер и первое впечатление", 1,
     "<b>Какой у ребёнка характер и как он обычно проявлялся в группе?</b>\n\n"
     "Опишите простыми словами, каким был ребёнок в течение смены: спокойным или активным, "
     "самостоятельным или нуждающимся в поддержке, инициативным, наблюдательным, настойчивым, "
     "осторожным, общительным и т.д. Можно привести 1–2 ситуации, где это было заметно."),
    (1, "Блок 1. Характер и первое впечатление", 2,
     "<b>Что самое быстрое и яркое приходит в голову про этого ребёнка?</b>\n\n"
     "Первая ассоциация, образ или эпизод — то, что вспоминается сразу."),
    (2, "Блок 2. Hard Skills — обучение и компетенции", 3,
     "<b>Стартовый уровень vs Итог: с чем ребёнок пришёл на мастер-классы и какой рывок совершил?</b>\n\n"
     "Отражаем образовательную траекторию. Стартовый уровень: например, хороший академический "
     "бэкграунд, развитое проектное мышление, опыт самостоятельной работы. Зона роста (с чем пришёл): "
     "например, отсутствие навыков управления командой, не умел делегировать и выстраивать коммуникацию "
     "«педагог-ребёнок-команда». Итог смены / рывок: например, научился выстраивать коммуникацию с людьми, "
     "начал понимать разницу между давлением и продуктивным взаимодействием."),
    (2, "Блок 2. Hard Skills — обучение и компетенции", 4,
     "<b>Момент инсайта (озарение)</b>\n\n"
     "Опишите конкретную ситуацию или задачу, на которой у ребёнка случился «щелчок» — "
     "он понял тему, которую не понимал раньше."),
    (2, "Блок 2. Hard Skills — обучение и компетенции", 5,
     "<b>Применение знаний</b>\n\n"
     "Как он использовал полученные на лекциях навыки «для спасения мира»? "
     "Приведите конкретный пример его вклада в итоговую миссию департамента."),
    (3, "Блок 3. Soft Skills — команда и кризисы", 6,
     "<b>Тип коммуникации</b>\n\n"
     "Самый важный блок для оценки гибких навыков. Как он встраивался в обсуждение? "
     "Варианты для размышления: предлагал идеи первым, развивал чужие, молча делал свою часть, "
     "спорил ради истины или ради спора."),
    (3, "Блок 3. Soft Skills — команда и кризисы", 7,
     "<b>Поведение в кризисе (провал миссии)</b>\n\n"
     "Опишите момент, когда что-то пошло не по плану (сжатые сроки, ошибка). Какова была реакция ребёнка? "
     "Спрятался, запаниковал, начал искать виноватых или включил режим «решателя проблем»?"),
    (3, "Блок 3. Soft Skills — команда и кризисы", 8,
     "<b>Лидерство и ответственность</b>\n\n"
     "Брал ли он на себя ответственность без просьбы педагога? Хотели ли другие дети идти за ним?"),
    (4, "Блок 4. Клубная жизнь и тусовка", 9,
     "<b>Клубная стратегия</b>\n\n"
     "Про активность вне департамента. Клубы он использовал, чтобы «прокачать скилл для миссии», "
     "просто «потупить/отдохнуть» или «найти другое комьюнити»?"),
    (4, "Блок 4. Клубная жизнь и тусовка", 10,
     "<b>Внутренняя валюта (трата зарплаты)</b>\n\n"
     "Вспомните, куда ребёнок тратил игровую валюту (мерч, кафе, VR). О чём это говорит? "
     "Например: «скупал всю коллекционку» — азарт; «всегда угощал друзей» — щедрость; "
     "«копил до последнего дня на супер-приз» — стратегия."),
    (4, "Блок 4. Клубная жизнь и тусовка", 11,
     "<b>Энергия</b>\n\n"
     "Как он переключался между «работой» (департамент) и «отдыхом»? "
     "Не выгорал ли, успевал ли восстанавливаться?"),
    (5, "Блок 5. Сюжет и реальность", 12,
     "<b>Вера в легенду</b>\n\n"
     "Связываем игру с внутренним миром ребёнка. Насколько ребёнок поверил в игровую реальность? "
     "Пытался ли «взламывать» игру, находить пасхалки (например, тайны закрытой лаборатории)?"),
    (5, "Блок 5. Сюжет и реальность", 13,
     "<b>Неожиданное качество</b>\n\n"
     "Что вы узнали об этом ребёнке такого, чего не ожидали увидеть в первый день? "
     "Скрытый талант, неожиданная эмпатия, жёсткость и т.д."),
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

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
    (1, "Блок 1. Мета-навыки и роль в мире", 1,
     "Игровая роль: Кем этот участник был в нашей корпорации последние 10 дней? "
     "(Например: «Теневой лидер», «Генератор хаоса», «Серый кардинал», «Душа компании», «Перфекционист-одиночка»)."),
    (1, "Блок 1. Мета-навыки и роль в мире", 2,
     "Главное событие: Что самое быстрое и яркое приходит в голову про этого ребёнка?"),
    (2, "Блок 2. Hard Skills: Обучение и компетенции департамента", 3,
     "Стартовый уровень vs Итог: С чем ребёнок пришёл на мастер-классы "
     "(полный ноль, теоретик, практик) и какой рывок совершил?"),
    (2, "Блок 2. Hard Skills: Обучение и компетенции департамента", 4,
     "Момент инсайта (Озарение): Опишите конкретную ситуацию или задачу, на которой у ребёнка "
     "случился «щелчок» — он понял тему, которую не понимал раньше."),
    (2, "Блок 2. Hard Skills: Обучение и компетенции департамента", 5,
     "Применение знаний: Как он использовал полученные на лекциях навыки для спасения мира? "
     "Приведите конкретный пример его вклада в итоговую миссию департамента."),
    (3, "Блок 3. Soft Skills: Работа в команде и кризисы", 6,
     "Тип коммуникации: Как он встраивался в обсуждение? "
     "(предлагал идеи первым, развивал чужие, молча делал свою часть, спорил ради истины или ради спора)."),
    (3, "Блок 3. Soft Skills: Работа в команде и кризисы", 7,
     "Поведение в кризисе (Провал миссии): Опишите момент, когда что-то пошло не по плану "
     "(сжатые сроки, ошибка). Какова была реакция ребёнка?"),
    (3, "Блок 3. Soft Skills: Работа в команде и кризисы", 8,
     "Лидерство и ответственность: Брал ли он на себя ответственность без просьбы педагога? "
     "Хотели ли другие дети идти за ним?"),
    (4, "Блок 4. Клубная жизнь и Тусовка (Социализация и Хобби)", 9,
     "Клубная стратегия: Клубы он использовал для того, чтобы «прокачать скилл для миссии», "
     "просто «потупить/отдохнуть» или «найти другое комьюнити»?"),
    (4, "Блок 4. Клубная жизнь и Тусовка (Социализация и Хобби)", 10,
     "Внутренняя валюта (Трата зарплаты): Вспомните, куда ребёнок тратил игровую валюту "
     "(мерч, кафе, VR). Это о чём-то говорит?"),
    (4, "Блок 4. Клубная жизнь и Тусовка (Социализация и Хобби)", 11,
     "Энергия: Как он переключался между «работой» (департамент) и «отдыхом»? "
     "Не выгорал ли, успевал ли восстанавливаться?"),
    (5, "Блок 5. Сюжет и Реальность (Вовлечённость и Рефлексия)", 12,
     "Вера в легенду: Насколько ребёнок поверил в игровую реальность? "
     "Пытался ли он «взламывать» игру, находить пасхалки?"),
    (5, "Блок 5. Сюжет и Реальность (Вовлечённость и Рефлексия)", 13,
     "Неожиданное качество: Что вы узнали об этом ребёнке такого, чего не ожидали увидеть "
     "в первый день? (Скрытый талант, неожиданная эмпатия, жёсткость и т.д.)."),
    (6, "Блок 6. Стратегические навыки и вклад в общее дело", 14,
     "Управление ресурсами: Чем ребёнок распоряжался в работе: временем, материалами, "
     "оборудованием, вниманием команды? Какое у него ресурсное мышление?"),
    (6, "Блок 6. Стратегические навыки и вклад в общее дело", 15,
     "Столкновение с конкурентами: Как он реагировал на сюжетные «козни конкурентов» "
     "или внешние помехи? Предлагал дипломатию, агрессивный ответ, хитрый манёвр?"),
    (6, "Блок 6. Стратегические навыки и вклад в общее дело", 16,
     "Эмоциональный интеллект в команде: Замечал ли он, что кто-то выпадает, деморализован? "
     "Пытался ли вдохновить команду, когда миссия казалась провальной?"),
    (6, "Блок 6. Стратегические навыки и вклад в общее дело", 17,
     "Принятие трудных решений: Был ли момент, когда ему пришлось отказаться от части идей, "
     "перераспределить роли или выбрать непопулярный путь, чтобы спасти проект?"),
    (6, "Блок 6. Стратегические навыки и вклад в общее дело", 18,
     "Личный вклад в финал: Сформулируйте его след в итоге департамента. "
     "«Без него мы бы…» (не уложились в срок / потеряли важную деталь / разругались...)."),
    (6, "Блок 6. Стратегические навыки и вклад в общее дело", 19,
     "Послание родителям: Что важного о ребёнке вы хотели бы передать его родителям? "
     "Что они должны знать о том, каким он был эти 10 дней?"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ENUMs — безопасное создание без DuplicateObjectError
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE user_role AS ENUM ('admin', 'moderator', 'teacher');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))
    conn.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE dialog_role AS ENUM ('assistant', 'user');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("role", sa.Enum("admin", "moderator", "teacher", name="user_role", create_type=False), nullable=False),
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
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
        sa.Column("role", sa.Enum("assistant", "user", name="dialog_role", create_type=False), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_revision_history_report", "revision_history", ["report_id"])

    # Seed questions
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
        [
            {
                "block_number": bn,
                "block_title": bt,
                "question_number": qn,
                "question_text": qt,
                "is_active": True,
            }
            for bn, bt, qn, qt in QUESTIONS
        ],
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

"""Replace 13-question questionnaire with 2 free-form blocks

Новая логика: педагог/вожатый больше НЕ отвечают на 13 отдельных вопросов.
Вместо этого — два больших свободных ответа-рассуждения:
  • вопрос 1 — «Преподский блок» (как ребёнок работал на занятиях);
  • вопрос 2 — «Вожатский блок» (как ребёнок проводил свободное время).
Каждый вопрос содержит большую подсказку с перечнем наводящих вопросов,
на которые можно ответить или не отвечать.

Стратегия (answers.question_id имеет ondelete=RESTRICT — строки, на которые
могут ссылаться старые ответы, НЕ удаляем):
  • UPDATE вопросов 1 и 2 на новые блоки (block_number / block_title /
    question_text, is_active=true);
  • DEACTIVATE вопросов 3..13 (is_active=false) — они исчезают из UI,
    но исторические ответы остаются валидными.

Revision ID: 0006_two_blocks
Revises: 0005_first_question
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_two_blocks"
down_revision = "0005_first_question"
branch_labels = None
depends_on = None


TEACHER_BLOCK_TITLE = "Блок 2. Преподский"
TUTOR_BLOCK_TITLE = "Блок 3. Вожатский"

TEACHER_QUESTION_TEXT = (
    "<b>Преподский блок. Как работал ребёнок?</b>\n\n"
    "Расскажите свободно, своими словами — как ребёнок проявлял себя на занятиях. "
    "Можно ответить на все вопросы ниже, на часть или просто описать в целом:\n\n"
    "• Включался в занятия сразу или раскачивался?\n"
    "• Понимал материал, переспрашивал?\n"
    "• Работал сам или постоянно требовал помощи?\n"
    "• Доводил задачи до конца или бросал на середине?\n"
    "• Проявлял инициативу, задавал вопросы «сверх»?\n"
    "• Как действовал в команде: тянул, мешал, растворялся?\n"
    "• Реакция на неудачу / сложное задание?\n"
    "• Что получалось лучше всего / в чём рос?\n\n"
    "🎤 Можно надиктовать голосом или написать текстом."
)

TUTOR_QUESTION_TEXT = (
    "<b>Вожатский блок. Как ребёнок проводил свободное время?</b>\n\n"
    "Расскажите свободно, своими словами — каким ребёнок был вне занятий. "
    "Можно ответить на все вопросы ниже, на часть или просто описать в целом:\n\n"
    "• Какие клубы / активности выбирал сам?\n"
    "• С кем общался (один, пара, стабильная компания)?\n"
    "• Как входил в коллектив: легко, осторожно, держался особняком?\n"
    "• Был заметен в тусовке или тихо наблюдал?\n"
    "• Случались ли конфликты, как выходил из них?\n"
    "• Брал на себя роль заводилы, ведомого, оппозиционера?\n"
    "• Общее настроение в неформальной среде (заряжал, гасил, плыл по течению)?\n\n"
    "🎤 Можно надиктовать голосом или написать текстом."
)


def _questions_table():
    return sa.table(
        "questions",
        sa.column("block_number", sa.Integer),
        sa.column("block_title", sa.String),
        sa.column("question_number", sa.Integer),
        sa.column("question_text", sa.Text),
        sa.column("is_active", sa.Boolean),
    )


def upgrade() -> None:
    q = _questions_table()
    conn = op.get_bind()

    # Вопрос 1 → Преподский блок
    conn.execute(
        q.update()
        .where(q.c.question_number == 1)
        .values(
            block_number=2,
            block_title=TEACHER_BLOCK_TITLE,
            question_text=TEACHER_QUESTION_TEXT,
            is_active=True,
        )
    )
    # Вопрос 2 → Вожатский блок
    conn.execute(
        q.update()
        .where(q.c.question_number == 2)
        .values(
            block_number=3,
            block_title=TUTOR_BLOCK_TITLE,
            question_text=TUTOR_QUESTION_TEXT,
            is_active=True,
        )
    )
    # Остальные вопросы (3..13 и любые выше) деактивируем.
    conn.execute(
        q.update()
        .where(q.c.question_number >= 3)
        .values(is_active=False)
    )


def downgrade() -> None:
    # Возврат частичный: активируем прежние 13 вопросов. Тексты вопросов 1 и 2
    # восстановить дословно нельзя без дублирования миграции 0003/0005,
    # поэтому просто снова активируем вопросы 1..13. Актуальные тексты вернёт
    # повторный прогон миграций 0003→0005 при необходимости.
    q = _questions_table()
    conn = op.get_bind()
    conn.execute(
        q.update()
        .where(q.c.question_number.between(1, 13))
        .values(is_active=True)
    )

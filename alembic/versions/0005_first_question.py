"""Update first teacher question wording

Revision ID: 0005_first_question
Revises: 0004_remove_moderator_role
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_first_question"
down_revision = "0004_remove_moderator_role"
branch_labels = None
depends_on = None


NEW_BLOCK_TITLE = "Блок 1. Характер и первое впечатление"
OLD_BLOCK_TITLE = "Блок 1. Игровая роль"

NEW_QUESTION_TEXT = (
    "<b>Какой у ребёнка характер и как он обычно проявлялся в группе?</b>\n\n"
    "Опишите простыми словами, каким был ребёнок в течение смены: спокойным или активным, "
    "самостоятельным или нуждающимся в поддержке, инициативным, наблюдательным, настойчивым, "
    "осторожным, общительным и т.д. Можно привести 1–2 ситуации, где это было заметно."
)

OLD_QUESTION_TEXT = (
    "<b>Кем этот участник был в нашей корпорации последние 10 дней?</b>\n\n"
    "Опишите игровую роль ребёнка. Например: «Конструктор-одиночка» — ребёнок с собственным "
    "видением развития департамента, не совпадающим с мнением большинства; добивается своего "
    "через упорство, а не харизму; теневое влияние."
)


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            UPDATE questions
            SET block_title = :block_title,
                question_text = :question_text
            WHERE question_number = 1
            """
        ),
        {"block_title": NEW_BLOCK_TITLE, "question_text": NEW_QUESTION_TEXT},
    )

    conn.execute(
        sa.text(
            """
            UPDATE questions
            SET block_title = :block_title
            WHERE question_number = 2
            """
        ),
        {"block_title": NEW_BLOCK_TITLE},
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            UPDATE questions
            SET block_title = :block_title,
                question_text = :question_text
            WHERE question_number = 1
            """
        ),
        {"block_title": OLD_BLOCK_TITLE, "question_text": OLD_QUESTION_TEXT},
    )

    conn.execute(
        sa.text(
            """
            UPDATE questions
            SET block_title = :block_title
            WHERE question_number = 2
            """
        ),
        {"block_title": OLD_BLOCK_TITLE},
    )
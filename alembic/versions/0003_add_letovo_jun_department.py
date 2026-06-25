"""Add Летово Джун department (id=9)

Revision ID: 0003_add_letovo_jun
Revises: 0002_seed_questions
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_add_letovo_jun"
down_revision = "0002_seed_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Новый департамент — это просто значение department_id = 9 в таблице shifts.
    Таблица departments не хранится в БД, справочник живёт в models.py и docx_service.py.
    
    Миграция обновляет CHECK-constraint на shifts.department_id (если он был),
    либо просто фиксирует факт добавления в комментарии.
    Если CHECK-constraint не был добавлен в 0001 — ничего делать не нужно.
    """
    # Проверяем, есть ли CHECK constraint на department_id
    # Если нет — миграция просто документирует добавление нового значения
    try:
        op.execute("""
            DO $$
            BEGIN
                -- Снимаем старый CHECK если он был
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'shifts_department_id_check'
                      AND conrelid = 'shifts'::regclass
                ) THEN
                    ALTER TABLE shifts DROP CONSTRAINT shifts_department_id_check;
                END IF;

                -- Добавляем новый CHECK с поддержкой id=9 (Летово Джун)
                ALTER TABLE shifts
                    ADD CONSTRAINT shifts_department_id_check
                    CHECK (department_id BETWEEN 1 AND 9);
            END
            $$;
        """)
    except Exception:
        # Если constraint не существовал — просто пропускаем
        pass


def downgrade() -> None:
    try:
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'shifts_department_id_check'
                      AND conrelid = 'shifts'::regclass
                ) THEN
                    ALTER TABLE shifts DROP CONSTRAINT shifts_department_id_check;
                END IF;
                ALTER TABLE shifts
                    ADD CONSTRAINT shifts_department_id_check
                    CHECK (department_id BETWEEN 1 AND 8);
            END
            $$;
        """)
    except Exception:
        pass

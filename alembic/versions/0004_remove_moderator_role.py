"""Remove moderator role

Роль «moderator» удалена из приложения (2026-07-03). В системе остаются только
две роли: admin и teacher.

Стратегия:
- Переводим всех существующих пользователей с role='moderator' в 'teacher',
  чтобы ORM (в котором значение moderator больше не объявлено) мог их читать.
- Значение 'moderator' в PG-enum user_role НЕ удаляется: удаление значения из
  enum в PostgreSQL небезопасно и требует пересоздания типа. Оставляем его как
  неиспользуемое — на работу приложения это не влияет.

Revision ID: 0004_remove_moderator_role
Revises: 0003_update_questions
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_remove_moderator_role"
down_revision = "0003_update_questions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Переводим бывших модераторов в педагогов.
    conn.execute(
        sa.text("UPDATE users SET role = 'teacher' WHERE role = 'moderator'")
    )


def downgrade() -> None:
    # Откат невозможен: невозможно достоверно восстановить, кто был модератором.
    # Значение 'moderator' по-прежнему присутствует в enum, поэтому ручное
    # восстановление ролей при необходимости остаётся возможным.
    pass

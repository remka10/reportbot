"""Departments inside shifts (Variant B)

- new table `departments` (9 auto-created per shift)
- new table `teacher_departments` (teacher <-> department, with shift_context)
- students.department_id FK -> departments
- backfill existing data from shifts.department_id / teacher_shifts
- shifts.department_id becomes nullable

Revision ID: 0002_departments
Revises: 0001_initial_schema
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_departments"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. departments
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("shifts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_number", sa.Integer, nullable=False),
        sa.UniqueConstraint("shift_id", "department_number", name="uq_department_shift_number"),
        sa.CheckConstraint("department_number BETWEEN 1 AND 9", name="departments_number_check"),
    )
    op.create_index("ix_departments_shift", "departments", ["shift_id"])

    # 2. teacher_departments
    op.create_table(
        "teacher_departments",
        sa.Column("teacher_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("shift_context", sa.Text, nullable=True),
    )

    # 3. students.department_id
    op.add_column(
        "students",
        sa.Column("department_id", sa.Integer, sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_students_department", "students", ["department_id"])

    # 4. shifts.department_id -> nullable (смена теперь охватывает все департаменты)
    op.alter_column("shifts", "department_id", existing_type=sa.Integer(), nullable=True)

    # ─── Data migration ────────────────────────────────────────────────────
    # 4.1 Создаём 9 департаментов для каждой существующей смены
    op.execute(
        """
        INSERT INTO departments (shift_id, department_number)
        SELECT s.id, n.num
        FROM shifts s
        CROSS JOIN (SELECT generate_series(1, 9) AS num) n
        """
    )

    # 4.2 Привязываем существующих студентов к департаменту,
    #     соответствующему старому shifts.department_id (по умолчанию 1).
    op.execute(
        """
        UPDATE students st
        SET department_id = d.id
        FROM shifts s
        JOIN departments d
          ON d.shift_id = s.id
         AND d.department_number = COALESCE(s.department_id, 1)
        WHERE st.shift_id = s.id
        """
    )

    # 4.3 Переносим привязки педагогов (teacher_shifts -> teacher_departments),
    #     контекст копируем в соответствующий департамент.
    op.execute(
        """
        INSERT INTO teacher_departments (teacher_id, department_id, shift_context)
        SELECT ts.teacher_id, d.id, ts.shift_context
        FROM teacher_shifts ts
        JOIN shifts s ON s.id = ts.shift_id
        JOIN departments d
          ON d.shift_id = s.id
         AND d.department_number = COALESCE(s.department_id, 1)
        ON CONFLICT (teacher_id, department_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_students_department", table_name="students")
    op.drop_column("students", "department_id")
    op.drop_table("teacher_departments")
    op.drop_index("ix_departments_shift", table_name="departments")
    op.drop_table("departments")
    op.alter_column("shifts", "department_id", existing_type=sa.Integer(), nullable=True)

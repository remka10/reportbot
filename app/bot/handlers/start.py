import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import teacher_main_menu
from app.bot.keyboards.admin_menu import admin_main_menu
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.student_repo import StudentRepository

logger = logging.getLogger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    await state.clear()

    if user.role == UserRole.teacher:
        await _start_teacher(message, user, session)
    else:
        await _start_admin(message, user)


async def _start_teacher(
    message: Message, user: User, session: AsyncSession
) -> None:
    """Главное меню педагога с краткой статистикой."""
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_for_teacher(user.id))

    if not shifts:
        await message.answer(
            f"👋 Привет, <b>{user.full_name}</b>!\n\n"
            "У вас пока нет привязанных смен.\n"
            "Обратитесь к администратору, чтобы вас добавили в смену."
        )
        return

    # Статистика по активным сменам
    stats_lines = []
    for shift in shifts[:3]:  # Показываем до 3 смен
        report_repo = ReportRepository(session)
        student_repo = StudentRepository(session)
        finalized = await report_repo.get_finalized_student_ids(user.id, shift.id)
        students = await student_repo.get_by_shift(shift.id)
        stats_lines.append(
            f"• {shift.name}: {len(finalized)}/{len(students)} отчётов готово"
        )

    stats_text = "\n".join(stats_lines) if stats_lines else ""
    stats_block = f"\n\n<b>Статус смен:</b>\n{stats_text}" if stats_text else ""

    await message.answer(
        f"👋 Привет, <b>{user.full_name}</b>!{stats_block}\n\n"
        "Выберите действие:",
        reply_markup=teacher_main_menu(),
    )


async def _start_admin(message: Message, user: User) -> None:
    """Главное меню для admin/moderator."""
    role_labels = {
        UserRole.admin: "👑 Администратор",
        UserRole.moderator: "🛡 Модератор",
    }
    role_label = role_labels.get(user.role, user.role.value)
    text = (
        f"👋 Привет, <b>{user.full_name}</b>!\n"
        f"Роль: {role_label}\n\n"
        "Используйте /admin для управления системой."
    )
    kb = admin_main_menu(is_admin=user.role == UserRole.admin)
    await message.answer(
        text,
        reply_markup=kb,
    )

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext

from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import teacher_main_menu
from app.bot.keyboards.admin_menu import admin_main_menu
from app.bot.utils.user_display import user_greeting_name
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.department_repo import DepartmentRepository


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


# Аварийный выход в главное меню. Дублирует поведение /start, но существует как
# отдельная понятная команда: если педагог «застрял» (залипшая кнопка, потерян
# контекст, busy-lock) — /menu всегда чистит FSM (в т.ч. llm_busy) и возвращает
# в главное меню, не заставляя искать старое сообщение с /start вверху чата.
@router.message(Command("menu"))
async def cmd_menu(
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
    """Главное меню педагога с краткой статистикой по департаментам."""
    shift_repo = ShiftRepository(session)
    dep_repo = DepartmentRepository(session)
    departments = list(await dep_repo.get_for_teacher(user.id))

    if not departments:
        await message.answer(
            f"👋 Привет, <b>{user_greeting_name(user)}</b>!\n\n"
            "У вас пока нет привязанных департаментов.\n"
            "Обратитесь к администратору, чтобы вас добавили в департамент."
        )
        return

    # Статистика по департаментам педагога
    report_repo = ReportRepository(session)
    student_repo = StudentRepository(session)
    shift_name_cache: dict[int, str] = {}
    stats_lines = []
    for dep in departments[:3]:  # Показываем до 3 департаментов
        if dep.shift_id not in shift_name_cache:
            shift = await shift_repo.get_by_id(dep.shift_id)
            shift_name_cache[dep.shift_id] = shift.name if shift else f"Смена {dep.shift_id}"
        students = await student_repo.get_by_department(dep.id)
        student_ids = {s.id for s in students}
        finalized = await report_repo.get_finalized_student_ids(user.id, dep.shift_id)
        done = len({sid for sid in finalized if sid in student_ids})
        stats_lines.append(
            f"• {shift_name_cache[dep.shift_id]} / {dep.name}: "
            f"{done}/{len(students)} отчётов готово"
        )

    stats_text = "\n".join(stats_lines) if stats_lines else ""
    stats_block = f"\n\n<b>Статус департаментов:</b>\n{stats_text}" if stats_text else ""


    await message.answer(
        f"👋 Привет, <b>{user_greeting_name(user)}</b>!{stats_block}\n\n"
        "Выберите действие:",
        reply_markup=teacher_main_menu(),
    )


async def _start_admin(message: Message, user: User) -> None:
    """Главное меню для admin."""
    role_labels = {
        UserRole.admin: "👑 Администратор",
    }
    role_label = role_labels.get(user.role, user.role.value)

    text = (
        f"👋 Привет, <b>{user_greeting_name(user)}</b>!\n"
        f"Роль: {role_label}\n\n"
        "Используйте /admin для управления системой."
    )
    kb = admin_main_menu(is_admin=user.role == UserRole.admin)
    await message.answer(
        text,
        reply_markup=kb,
    )

# app/bot/handlers/admin/fill.py
"""
Заполнение отчётов администратором/модератором.

Админ может выбрать ЛЮБУЮ активную смену и ЛЮБОЙ департамент внутри неё,
после чего попадает в тот же пайплайн, что и педагог (контекст → дети →
вопросы → генерация → экспорт).

Технически: при выборе департамента админ идемпотентно привязывается к нему
(создаётся запись TeacherDepartment), что позволяет переиспользовать всю
логику педагога без изменений.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import back_keyboard_admin
from app.bot.states.admin_states import AdminFillStates
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.department_repo import DepartmentRepository

logger = logging.getLogger(__name__)
router = Router(name="admin_fill")


def _is_admin_or_mod(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.moderator)


@router.callback_query(F.data == "admin:fill")
async def cb_fill_start(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Старт заполнения: показываем список всех активных смен."""
    if not _is_admin_or_mod(user):
        await cb.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_all_active())
    if not shifts:
        await cb.message.edit_text(
            "📭 Нет активных смен. Сначала создайте смену.",
            reply_markup=back_keyboard_admin("admin:main"),
        )
        await cb.answer()
        return

    await state.set_state(AdminFillStates.waiting_shift_select)
    builder = InlineKeyboardBuilder()
    for s in shifts:
        builder.button(text=f"[{s.id}] {s.name}", callback_data=f"fill_shift:{s.id}")
    builder.button(text="← Назад", callback_data="admin:main")
    builder.adjust(1)
    await cb.message.edit_text(
        "📝 <b>Заполнение отчётов</b>\n\nВыберите смену:",
        reply_markup=builder.as_markup(),
    )
    await cb.answer()


@router.callback_query(
    AdminFillStates.waiting_shift_select, F.data.startswith("fill_shift:")
)
async def cb_fill_shift_selected(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Выбрана смена — показываем её департаменты."""
    if not _is_admin_or_mod(user):
        await cb.answer("Нет доступа", show_alert=True)
        return

    shift_id = int(cb.data.split(":")[1])
    dep_repo = DepartmentRepository(session)
    departments = list(await dep_repo.get_by_shift(shift_id))
    if not departments:
        await cb.message.edit_text(
            "📭 В этой смене нет департаментов.",
            reply_markup=back_keyboard_admin("admin:fill"),
        )
        await cb.answer()
        return

    await state.update_data(fill_shift_id=shift_id)
    await state.set_state(AdminFillStates.waiting_department_select)
    builder = InlineKeyboardBuilder()
    for d in departments:
        builder.button(text=d.name, callback_data=f"fill_department:{d.id}")
    builder.button(text="← Назад", callback_data="admin:fill")
    builder.adjust(1)
    await cb.message.edit_text(
        "🏢 Выберите департамент для заполнения отчётов:",
        reply_markup=builder.as_markup(),
    )
    await cb.answer()


@router.callback_query(
    AdminFillStates.waiting_department_select, F.data.startswith("fill_department:")
)
async def cb_fill_department_selected(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """
    Выбран департамент — привязываем админа к нему (идемпотентно) и передаём
    управление в общий пайплайн педагога (open_department из teacher/shift.py).
    """
    if not _is_admin_or_mod(user):
        await cb.answer("Нет доступа", show_alert=True)
        return

    department_id = int(cb.data.split(":")[-1])
    dep_repo = DepartmentRepository(session)
    department = await dep_repo.get_by_id(department_id)
    if department is None:
        await cb.answer("❌ Департамент не найден", show_alert=True)
        return

    # Привязываем администратора к департаменту, чтобы переиспользовать
    # логику педагога (контекст хранится per-user в TeacherDepartment).
    await dep_repo.assign_teacher(department_id=department_id, teacher_id=user.id)

    # Передаём управление в общий обработчик департамента
    from app.bot.handlers.teacher.shift import open_department
    await open_department(cb, user, session, state, department_id)

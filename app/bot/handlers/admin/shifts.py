# app/bot/handlers/admin/shifts.py
"""
Хендлер управления сменами (admin/moderator).

Новая модель: при создании смены автоматически создаются ВСЕ 9 департаментов.
Студенты и педагоги привязываются к департаменту внутри смены.
"""
import logging
import re
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import (
    back_keyboard_admin, shifts_menu, departments_list_keyboard,
)
from app.bot.states.admin_states import (
    CreateShiftStates, ArchiveShiftStates, AssignTeacherStates,
)
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.department_repo import DepartmentRepository

logger = logging.getLogger(__name__)
router = Router(name="admin_shifts")


@router.callback_query(F.data == "admin:shifts")
async def cb_shifts_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text(
        "🏕 <b>Управление сменами</b>\n\nВыберите действие:",
        reply_markup=shifts_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:shifts:list")
async def cb_shifts_list(cb: CallbackQuery, session: AsyncSession) -> None:
    shift_repo = ShiftRepository(session)
    dep_repo = DepartmentRepository(session)
    shifts = list(await shift_repo.get_all_active())
    if not shifts:
        await cb.message.edit_text(
            "Смен пока нет.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    lines = ["<b>Активные смены:</b>"]
    for s in shifts:
        deps = list(await dep_repo.get_by_shift(s.id))
        lines.append(f"• [ID {s.id}] {s.name} — департаментов: {len(deps)}")
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_keyboard_admin("admin:shifts"),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Создание смены (без выбора департамента — создаются все 9)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:shifts:create")
async def cb_create_shift_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateShiftStates.waiting_name)
    await cb.message.edit_text(
        "Введите название смены (например: <i>Смена 1, Лето 2026</i>):",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin("admin:shifts"),
    )


@router.message(CreateShiftStates.waiting_name)
async def create_shift_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 3:
        await message.answer("Название слишком короткое. Попробуй ещё раз.")
        return
    await state.update_data(shift_name=name)
    await state.set_state(CreateShiftStates.waiting_dates)
    await message.answer(
        f"Смена: <b>{name}</b>\n\n"
        "Введите даты смены в формате <code>ДД.ММ.ГГГГ-ДД.ММ.ГГГГ</code>\n"
        "Например: <code>27.06.2026-06.07.2026</code>",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin("admin:shifts"),
    )


@router.message(CreateShiftStates.waiting_dates)
async def create_shift_dates(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    text = (message.text or "").strip()
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})-(\d{2})\.(\d{2})\.(\d{4})", text)
    if not match:
        await message.answer(
            "Неверный формат. Введите даты как <code>27.06.2026-06.07.2026</code>",
            parse_mode="HTML",
        )
        return
    d1, m1, y1, d2, m2, y2 = match.groups()
    try:
        start = date(int(y1), int(m1), int(d1))
        end   = date(int(y2), int(m2), int(d2))
    except ValueError:
        await message.answer("Некорректная дата. Проверь числа и попробуй ещё раз.")
        return

    data = await state.get_data()
    shift_repo = ShiftRepository(session)
    dep_repo = DepartmentRepository(session)

    shift = await shift_repo.create(
        name=data["shift_name"],
        department_id=None,
        start_date=start,
        end_date=end,
        created_by=user.id,
    )
    # Автоматически создаём все 9 департаментов, привязанных к этой смене
    departments = await dep_repo.create_for_shift(shift.id)

    await state.clear()
    dep_lines = "\n".join(f"  • {d.emoji} {d.name}" for d in departments)
    await message.answer(
        f"✅ Смена создана!\n"
        f"<b>{shift.name}</b>\n"
        f"Даты: {start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}\n\n"
        f"Автоматически создано департаментов: <b>{len(departments)}</b>\n"
        f"{dep_lines}\n\n"
        "Теперь можно добавлять учащихся и педагогов в департаменты.",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin("admin:shifts"),
    )


# ---------------------------------------------------------------------------
# Привязка педагога: смена → департамент → педагог
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:shifts:assign")
async def cb_assign_teacher_start(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_all_active())
    if not shifts:
        await cb.message.edit_text(
            "Нет активных смен.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    await state.set_state(AssignTeacherStates.waiting_shift_select)
    builder = InlineKeyboardBuilder()
    for s in shifts:
        builder.button(text=f"[{s.id}] {s.name}", callback_data=f"assign_shift:{s.id}")
    builder.button(text="← Назад", callback_data="admin:shifts")
    builder.adjust(1)
    await cb.message.edit_text(
        "Выберите смену:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(
    AssignTeacherStates.waiting_shift_select, F.data.startswith("assign_shift:")
)
async def cb_assign_shift_selected(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(assign_shift_id=shift_id)
    dep_repo = DepartmentRepository(session)
    departments = list(await dep_repo.get_by_shift(shift_id))
    if not departments:
        await cb.message.edit_text(
            "В этой смене нет департаментов.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    await state.set_state(AssignTeacherStates.waiting_department_select)
    await cb.message.edit_text(
        "Выберите департамент для привязки педагога:",
        reply_markup=departments_list_keyboard(departments, back_to="admin:shifts:assign"),
    )


@router.callback_query(
    AssignTeacherStates.waiting_department_select, F.data.startswith("select_department:")
)
async def cb_assign_department_selected(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    from app.repositories.user_repo import UserRepository
    department_id = int(cb.data.split(":")[1])
    await state.update_data(assign_department_id=department_id)

    user_repo = UserRepository(session)
    all_teachers = list(await user_repo.get_by_role(UserRole.teacher))
    teachers = [t for t in all_teachers if t.is_active]
    if not teachers:
        await cb.message.edit_text(
            "Нет активных педагогов.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    await state.set_state(AssignTeacherStates.waiting_teacher_select)
    builder = InlineKeyboardBuilder()
    for t in teachers:
        builder.button(text=t.full_name, callback_data=f"assign_teacher:{t.id}")
    builder.button(text="← Назад", callback_data="admin:shifts:assign")
    builder.adjust(1)
    await cb.message.edit_text(
        "Выберите педагога:", reply_markup=builder.as_markup()
    )


@router.callback_query(
    AssignTeacherStates.waiting_teacher_select, F.data.startswith("assign_teacher:")
)
async def cb_assign_teacher_confirm(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    teacher_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    department_id = data.get("assign_department_id")
    if not department_id:
        await cb.answer("Ошибка: департамент не выбран.", show_alert=True)
        return
    dep_repo = DepartmentRepository(session)
    department = await dep_repo.get_by_id(department_id)
    await dep_repo.assign_teacher(department_id=department_id, teacher_id=teacher_id)
    await state.clear()
    await cb.message.edit_text(
        f"✅ Педагог привязан к департаменту "
        f"<b>{department.emoji + ' ' + department.name if department else department_id}</b>.",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin("admin:shifts"),
    )


# ---------------------------------------------------------------------------
# Архивирование смены
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:shifts:archive")
async def cb_archive_shift_start(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_all_active())
    if not shifts:
        await cb.message.edit_text(
            "Нет активных смен.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    await state.set_state(ArchiveShiftStates.waiting_shift_select)
    builder = InlineKeyboardBuilder()
    for s in shifts:
        builder.button(text=f"[{s.id}] {s.name}", callback_data=f"archive_shift:{s.id}")
    builder.button(text="← Назад", callback_data="admin:shifts")
    builder.adjust(1)
    await cb.message.edit_text(
        "⚠️ Выберите смену для архивирования:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(
    ArchiveShiftStates.waiting_shift_select, F.data.startswith("archive_shift:")
)
async def cb_archive_shift_selected(
    cb: CallbackQuery, state: FSMContext
) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(archive_shift_id=shift_id)
    await state.set_state(ArchiveShiftStates.confirm)
    from app.bot.keyboards.admin_menu import confirm_keyboard
    await cb.message.edit_text(
        f"Архивировать смену ID {shift_id}? Педагоги потеряют к ней доступ.",
        reply_markup=confirm_keyboard(
            yes_data=f"archive_confirm:{shift_id}",
            no_data="admin:shifts",
        ),
    )


@router.callback_query(
    ArchiveShiftStates.confirm, F.data.startswith("archive_confirm:")
)
async def cb_archive_shift_confirm(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    shift_repo = ShiftRepository(session)
    ok = await shift_repo.archive(shift_id)
    await state.clear()
    text = "✅ Смена архивирована." if ok else "❌ Смена не найдена."
    await cb.message.edit_text(text, reply_markup=back_keyboard_admin("admin:shifts"))

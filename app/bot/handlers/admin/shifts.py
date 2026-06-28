# app/bot/handlers/admin/shifts.py
"""
Хендлер управления сменами (admin/moderator).
"""
import logging
import re
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import back_keyboard_admin, shifts_menu
from app.bot.states.admin_states import CreateShiftStates, ArchiveShiftStates
from app.database.models import DEPARTMENTS, User, UserRole
from app.repositories.shift_repo import ShiftRepository

logger = logging.getLogger(__name__)
router = Router(name="admin_shifts")


def _departments_keyboard():
    builder = InlineKeyboardBuilder()
    for dep_id, info in DEPARTMENTS.items():
        builder.button(text=info["name"], callback_data=f"dep_{dep_id}")
    builder.button(text="← Назад", callback_data="admin:shifts")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(F.data == "admin:shifts")
async def cb_shifts_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "🏕 <b>Управление сменами</b>\n\nВыберите действие:",
        reply_markup=shifts_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:shifts:list")
async def cb_shifts_list(cb: CallbackQuery, session: AsyncSession) -> None:
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_all_active())
    if not shifts:
        await cb.message.edit_text(
            "Смен пока нет.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    lines = ["<b>Активные смены:</b>"]
    for s in shifts:
        lines.append(f"• [ID {s.id}] {s.name} — {s.department_name}")
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_keyboard_admin("admin:shifts"),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:shifts:create")
async def cb_create_shift_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateShiftStates.waiting_name)
    await cb.message.edit_text(
        "Введите название смены (например: <i>Смена 3, Лето 2026</i>):",
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
    await state.set_state(CreateShiftStates.waiting_department)
    await message.answer(
        f"Выбери департамент для смены <b>{name}</b>:",
        parse_mode="HTML",
        reply_markup=_departments_keyboard(),
    )


@router.callback_query(CreateShiftStates.waiting_department, F.data.startswith("dep_"))
async def create_shift_department(cb: CallbackQuery, state: FSMContext) -> None:
    dep_id = int(cb.data.split("_")[1])
    if dep_id not in DEPARTMENTS:
        await cb.answer("Неизвестный департамент.", show_alert=True)
        return
    await state.update_data(department_id=dep_id)
    await state.set_state(CreateShiftStates.waiting_dates)
    dep_name = DEPARTMENTS[dep_id]["name"]
    await cb.message.edit_text(
        f"Департамент: <b>{dep_name}</b>\n\n"
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
    shift = await shift_repo.create(
        name=data["shift_name"],
        department_id=data["department_id"],
        start_date=start,
        end_date=end,
        created_by=user.id,
    )
    await state.clear()
    await message.answer(
        f"✅ Смена создана!\n"
        f"<b>{shift.name}</b>\n"
        f"Департамент: {shift.department_name}\n"
        f"Даты: {start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin("admin:shifts"),
    )


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
    builder = InlineKeyboardBuilder()
    for s in shifts:
        builder.button(text=f"[{s.id}] {s.name}", callback_data=f"assign_shift:{s.id}")
    builder.button(text="← Назад", callback_data="admin:shifts")
    builder.adjust(1)
    await cb.message.edit_text(
        "Выберите смену для привязки педагога:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("assign_shift:"))
async def cb_assign_shift_selected(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    from app.repositories.user_repo import UserRepository
    shift_id = int(cb.data.split(":")[1])
    user_repo = UserRepository(session)
    # ИСПРАВЛЕНО: get_by_role вместо несуществующего get_by_role_active
    all_teachers = list(await user_repo.get_by_role(UserRole.teacher))
    teachers = [t for t in all_teachers if t.is_active]
    if not teachers:
        await cb.message.edit_text(
            "Нет активных педагогов.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    await state.update_data(assign_shift_id=shift_id)
    builder = InlineKeyboardBuilder()
    for t in teachers:
        builder.button(text=t.full_name, callback_data=f"assign_teacher:{t.id}")
    builder.button(text="← Назад", callback_data="admin:shifts:assign")
    builder.adjust(1)
    await cb.message.edit_text(
        "Выберите педагога:", reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("assign_teacher:"))
async def cb_assign_teacher_confirm(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    teacher_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    shift_id = data.get("assign_shift_id")
    if not shift_id:
        await cb.answer("Ошибка: смена не выбрана.", show_alert=True)
        return
    shift_repo = ShiftRepository(session)
    await shift_repo.assign_teacher(shift_id=shift_id, teacher_id=teacher_id)
    await state.clear()
    await cb.message.edit_text(
        "✅ Педагог привязан к смене.",
        reply_markup=back_keyboard_admin("admin:shifts"),
    )


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
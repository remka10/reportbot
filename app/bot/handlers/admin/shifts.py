import logging
from datetime import date

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import (
    shifts_menu, departments_keyboard, shifts_list_keyboard,
    users_list_keyboard, confirm_keyboard, back_keyboard,
)
from app.bot.states.admin_states import CreateShiftStates, AssignTeacherStates
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)
router = Router(name="admin_shifts")


@router.callback_query(F.data == "admin:shifts")
async def cb_shifts_menu(cb: CallbackQuery, user: User) -> None:
    if user.role not in (UserRole.admin, UserRole.moderator):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await cb.message.edit_text("🏕 <b>Управление сменами</b>", reply_markup=shifts_menu())


# ---------------------------------------------------------------------------
# Создать смену
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:shifts:create")
async def cb_create_shift_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateShiftStates.waiting_name)
    await cb.message.edit_text(
        "➕ <b>Создание смены</b>Введите название смены:"
        "<i>Например: «Смена 3, Лето 2026»</i>",
        reply_markup=back_keyboard("admin:shifts"),
    )


@router.message(CreateShiftStates.waiting_name)
async def create_shift_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 3:
        await message.answer("⚠️ Слишком короткое название. Введите ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(CreateShiftStates.waiting_department)
    await message.answer("Выберите департамент:", reply_markup=departments_keyboard())


@router.callback_query(CreateShiftStates.waiting_department, F.data.startswith("dept:"))
async def create_shift_dept(cb: CallbackQuery, state: FSMContext) -> None:
    dept_id = int(cb.data.split(":")[1])
    await state.update_data(department_id=dept_id)
    await state.set_state(CreateShiftStates.waiting_start_date)
    await cb.message.edit_text(
        "Введите дату <b>начала</b> смены в формате <code>ДД.ММ.ГГГГ</code>:"
    )


@router.message(CreateShiftStates.waiting_start_date)
async def create_shift_start(message: Message, state: FSMContext) -> None:
    try:
        start = date(*reversed([int(x) for x in (message.text or "").strip().split(".")]))
    except Exception:
        await message.answer("⚠️ Неверный формат. Введите дату в формате <code>ДД.ММ.ГГГГ</code>:")
        return
    await state.update_data(start_date=start.isoformat())
    await state.set_state(CreateShiftStates.waiting_end_date)
    await message.answer("Введите дату <b>окончания</b> смены (<code>ДД.ММ.ГГГГ</code>):")


@router.message(CreateShiftStates.waiting_end_date)
async def create_shift_end(message: Message, state: FSMContext) -> None:
    try:
        end = date(*reversed([int(x) for x in (message.text or "").strip().split(".")]))
    except Exception:
        await message.answer("⚠️ Неверный формат. Введите дату в формате <code>ДД.ММ.ГГГГ</code>:")
        return
    data = await state.get_data()
    start = date.fromisoformat(data["start_date"])
    if end <= start:
        await message.answer("⚠️ Дата окончания должна быть позже даты начала.")
        return
    await state.update_data(end_date=end.isoformat())
    await state.set_state(CreateShiftStates.confirm)

    from app.database.models import DEPARTMENTS
    dept_name = DEPARTMENTS.get(data["department_id"], "—")
    await message.answer(
        f"Подтвердите создание смены:"
        f"• Название: <b>{data['name']}</b>"
        f"• Департамент: <b>{dept_name}</b>"
        f"• Начало: <b>{start.strftime('%d.%m.%Y')}</b>"
        f"• Конец: <b>{end.strftime('%d.%m.%Y')}</b>",
        reply_markup=confirm_keyboard(yes_data="admin:shifts:create:confirm"),
    )


@router.callback_query(CreateShiftStates.confirm, F.data == "admin:shifts:create:confirm")
async def create_shift_confirm(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    repo = ShiftRepository(session)
    shift = await repo.create(
        name=data["name"],
        department_id=data["department_id"],
        start_date=date.fromisoformat(data["start_date"]),
        end_date=date.fromisoformat(data["end_date"]),
        created_by=user.id,
    )
    await state.clear()
    await cb.message.edit_text(
        f"✅ Смена <b>{shift.name}</b> создана (ID: {shift.id}).",
        reply_markup=back_keyboard("admin:shifts"),
    )


# ---------------------------------------------------------------------------
# Список смен
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:shifts:list")
async def cb_shifts_list(cb: CallbackQuery, session: AsyncSession) -> None:
    repo = ShiftRepository(session)
    shifts = await repo.get_all_active()
    if not shifts:
        await cb.message.edit_text("Активных смен нет.", reply_markup=back_keyboard("admin:shifts"))
        return
    lines = [f"🏕 <b>Активные смены ({len(shifts)}):</b>"]
    for s in shifts:
        lines.append(
            f"• [{s.id}] <b>{s.name}</b> | {s.department_name} | "
            f"{s.start_date.strftime('%d.%m.%Y')}–{s.end_date.strftime('%d.%m.%Y')}"
        )
    await cb.message.edit_text("".join(lines), reply_markup=back_keyboard("admin:shifts"))


# ---------------------------------------------------------------------------
# Привязать педагога к смене
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:shifts:assign")
async def cb_assign_start(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    repo = ShiftRepository(session)
    shifts = list(await repo.get_all_active())
    if not shifts:
        await cb.message.edit_text("Нет активных смен.", reply_markup=back_keyboard("admin:shifts"))
        return
    await state.set_state(AssignTeacherStates.waiting_shift_select)
    await cb.message.edit_text(
        "Выберите смену для привязки педагога:",
        reply_markup=shifts_list_keyboard(shifts),
    )


@router.callback_query(AssignTeacherStates.waiting_shift_select, F.data.startswith("select_shift:"))
async def assign_shift_selected(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(shift_id=shift_id)
    repo = UserRepository(session)
    teachers = list(await repo.get_by_role(UserRole.teacher))
    if not teachers:
        await cb.message.edit_text("Нет педагогов в системе.", reply_markup=back_keyboard("admin:shifts"))
        return
    await state.set_state(AssignTeacherStates.waiting_teacher_select)
    await cb.message.edit_text(
        "Выберите педагога:",
        reply_markup=users_list_keyboard(teachers),
    )


@router.callback_query(AssignTeacherStates.waiting_teacher_select, F.data.startswith("select_user:"))
async def assign_teacher_confirm(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    teacher_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    repo = ShiftRepository(session)
    await repo.assign_teacher(teacher_id=teacher_id, shift_id=data["shift_id"])
    await state.clear()
    await cb.message.edit_text(
        "✅ Педагог привязан к смене.",
        reply_markup=back_keyboard("admin:shifts"),
    )


# ---------------------------------------------------------------------------
# Архивировать смену
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:shifts:archive")
async def cb_archive_start(cb: CallbackQuery, session: AsyncSession) -> None:
    repo = ShiftRepository(session)
    shifts = list(await repo.get_all_active())
    if not shifts:
        await cb.message.edit_text("Нет активных смен.", reply_markup=back_keyboard("admin:shifts"))
        return
    await cb.message.edit_text(
        "Выберите смену для архивирования:",
        reply_markup=shifts_list_keyboard(shifts),
    )


@router.callback_query(F.data.startswith("select_shift:"))
async def archive_shift_selected(cb: CallbackQuery, session: AsyncSession) -> None:
    shift_id = int(cb.data.split(":")[1])
    repo = ShiftRepository(session)
    shift = await repo.get_by_id(shift_id)
    if not shift:
        await cb.answer("Смена не найдена", show_alert=True)
        return
    await repo.archive(shift_id)
    await cb.message.edit_text(
        f"✅ Смена <b>{shift.name}</b> архивирована.",
        reply_markup=back_keyboard("admin:shifts"),
    )
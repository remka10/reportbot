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
    shifts_manage_keyboard, shift_card_keyboard,
    shift_context_departments_keyboard, shift_context_actions_keyboard,
    confirm_keyboard,
)
from app.bot.utils.user_display import user_button_label, telegram_username

from app.bot.states.admin_states import (
    CreateShiftStates, ArchiveShiftStates, AssignTeacherStates,
    EditShiftStates, ShiftContextStates,
)
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.department_repo import DepartmentRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.report_repo import ReportRepository


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
async def cb_shifts_list(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    """Список активных смен — каждая кнопка открывает карточку управления."""
    await state.clear()
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_all_active())
    if not shifts:
        await cb.message.edit_text(
            "Смен пока нет. Создайте новую в меню «Смены».",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    await cb.message.edit_text(
        "🗂 <b>Список активных смен</b>\n\nВыберите смену для управления:",
        reply_markup=shifts_manage_keyboard(shifts, back_to="admin:shifts"),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Карточка смены: статистика + действия
# ---------------------------------------------------------------------------

async def _render_shift_card(
    cb: CallbackQuery, session: AsyncSession, shift_id: int
) -> None:
    """Рисует карточку смены со статистикой и клавиатурой действий."""
    shift_repo = ShiftRepository(session)
    dep_repo = DepartmentRepository(session)
    student_repo = StudentRepository(session)
    report_repo = ReportRepository(session)

    shift = await shift_repo.get_by_id(shift_id)
    if shift is None:
        await cb.message.edit_text(
            "❌ Смена не найдена (возможно, удалена).",
            reply_markup=back_keyboard_admin("admin:shifts:list"),
        )
        return

    departments = list(await dep_repo.get_by_shift(shift_id))
    students_total = await student_repo.count_by_shift(shift_id)
    finalized = await report_repo.get_finalized_student_ids(0, shift_id)
    teachers = await dep_repo.get_teachers_for_shift(shift_id)
    unique_teachers = {t.id for t, _ in teachers}
    deps_with_ctx = await dep_repo.count_departments_with_context(shift_id)

    ready = len(finalized)
    remaining = max(0, students_total - ready)
    status = "🟢 активна" if shift.is_active else "📦 в архиве"

    text = (
        f"🏕 <b>{shift.name}</b>\n"
        f"Статус: {status}\n"
        f"📅 {shift.start_date.strftime('%d.%m.%Y')} – "
        f"{shift.end_date.strftime('%d.%m.%Y')}\n\n"
        f"🏢 Департаментов: <b>{len(departments)}</b>\n"
        f"📖 С контекстом: <b>{deps_with_ctx}</b> из {len(departments)}\n"
        f"👨‍🏫 Педагогов привязано: <b>{len(unique_teachers)}</b>\n"
        f"👦 Учащихся: <b>{students_total}</b>\n"
        f"✅ Отчётов готово: <b>{ready}</b> · ⏳ осталось: <b>{remaining}</b>"
    )
    await cb.message.edit_text(
        text,
        reply_markup=shift_card_keyboard(shift_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("shift_card:"))
async def cb_shift_card(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    shift_id = int(cb.data.split(":")[1])
    await _render_shift_card(cb, session, shift_id)


# ---------------------------------------------------------------------------
# Переименование смены
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("shift_rename:"))
async def cb_shift_rename_start(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    shift = await ShiftRepository(session).get_by_id(shift_id)
    if shift is None:
        await cb.answer("Смена не найдена.", show_alert=True)
        return
    await state.set_state(EditShiftStates.waiting_new_name)
    await state.update_data(edit_shift_id=shift_id)
    await cb.message.edit_text(
        f"✏️ Текущее название: <b>{shift.name}</b>\n\n"
        "Отправьте новое название смены сообщением:",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin(f"shift_card:{shift_id}"),
    )


@router.message(EditShiftStates.waiting_new_name)
async def msg_shift_rename(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = (message.text or "").strip()
    data = await state.get_data()
    shift_id = data.get("edit_shift_id")
    if len(name) < 3:
        await message.answer("Название слишком короткое. Попробуйте ещё раз.")
        return
    ok = await ShiftRepository(session).rename(shift_id, name)
    await state.clear()
    if not ok:
        await message.answer(
            "❌ Смена не найдена.",
            reply_markup=back_keyboard_admin("admin:shifts:list"),
        )
        return
    await message.answer(
        f"✅ Название смены изменено на <b>{name}</b>.",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin(f"shift_card:{shift_id}"),
    )


# ---------------------------------------------------------------------------
# Изменение дат смены
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("shift_dates:"))
async def cb_shift_dates_start(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    shift = await ShiftRepository(session).get_by_id(shift_id)
    if shift is None:
        await cb.answer("Смена не найдена.", show_alert=True)
        return
    await state.set_state(EditShiftStates.waiting_new_dates)
    await state.update_data(edit_shift_id=shift_id)
    await cb.message.edit_text(
        f"📅 Текущие даты: "
        f"{shift.start_date.strftime('%d.%m.%Y')} – "
        f"{shift.end_date.strftime('%d.%m.%Y')}\n\n"
        "Отправьте новые даты в формате "
        "<code>ДД.ММ.ГГГГ-ДД.ММ.ГГГГ</code>\n"
        "Например: <code>27.06.2026-06.07.2026</code>",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin(f"shift_card:{shift_id}"),
    )


@router.message(EditShiftStates.waiting_new_dates)
async def msg_shift_dates(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    shift_id = data.get("edit_shift_id")
    match = re.match(r"(\d{2})\.(\d{2})\.(\d{4})-(\d{2})\.(\d{2})\.(\d{4})", text)
    if not match:
        await message.answer(
            "Неверный формат. Введите как <code>27.06.2026-06.07.2026</code>",
            parse_mode="HTML",
        )
        return
    d1, m1, y1, d2, m2, y2 = match.groups()
    try:
        start = date(int(y1), int(m1), int(d1))
        end   = date(int(y2), int(m2), int(d2))
    except ValueError:
        await message.answer("Некорректная дата. Проверьте числа и попробуйте ещё раз.")
        return
    if end < start:
        await message.answer("Дата окончания раньше даты начала. Проверьте порядок дат.")
        return
    ok = await ShiftRepository(session).update_dates(shift_id, start, end)
    await state.clear()
    if not ok:
        await message.answer(
            "❌ Смена не найдена.",
            reply_markup=back_keyboard_admin("admin:shifts:list"),
        )
        return
    await message.answer(
        f"✅ Даты смены обновлены: "
        f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}.",
        reply_markup=back_keyboard_admin(f"shift_card:{shift_id}"),
    )


# ---------------------------------------------------------------------------
# Контекст (легенда) смены — по департаментам
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("shift_context:"))
async def cb_shift_context(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Список департаментов смены для управления контекстом (легендой)."""
    await state.clear()
    shift_id = int(cb.data.split(":")[1])
    dep_repo = DepartmentRepository(session)
    departments = list(await dep_repo.get_by_shift(shift_id))
    if not departments:
        await cb.message.edit_text(
            "В этой смене нет департаментов.",
            reply_markup=back_keyboard_admin(f"shift_card:{shift_id}"),
        )
        return
    context_flags: dict[int, bool] = {}
    for d in departments:
        ctx = await dep_repo.get_any_context(d.id)
        context_flags[d.id] = bool(ctx)
    await cb.message.edit_text(
        "📖 <b>Контекст смены (легенда)</b>\n\n"
        "Контекст — это общее описание смены/сюжета, которое ИИ учитывает при "
        "генерации отчётов. Он общий для всех педагогов департамента.\n\n"
        "📝 — контекст заполнен, ⬜ — пусто. Выберите департамент:",
        reply_markup=shift_context_departments_keyboard(
            departments, shift_id, context_flags
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("shift_ctx_dep:"))
async def cb_shift_ctx_dep(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Просмотр контекста конкретного департамента + кнопки изменить/удалить."""
    await state.clear()
    department_id = int(cb.data.split(":")[1])
    dep_repo = DepartmentRepository(session)
    department = await dep_repo.get_by_id(department_id)
    if department is None:
        await cb.answer("Департамент не найден.", show_alert=True)
        return
    ctx = await dep_repo.get_any_context(department_id)
    if ctx:
        # Ограничим предпросмотр, чтобы не упереться в лимит сообщения.
        preview = ctx if len(ctx) <= 2000 else ctx[:2000] + "…"
        body = f"<b>Текущий контекст:</b>\n\n{preview}"
    else:
        body = "<i>Контекст пока не задан.</i>"
    await cb.message.edit_text(
        f"📖 <b>{department.emoji} {department.name}</b>\n\n{body}",
        reply_markup=shift_context_actions_keyboard(
            department_id, department.shift_id, has_context=bool(ctx)
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("shift_ctx_edit:"))
async def cb_shift_ctx_edit(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    department_id = int(cb.data.split(":")[1])
    dep_repo = DepartmentRepository(session)
    department = await dep_repo.get_by_id(department_id)
    if department is None:
        await cb.answer("Департамент не найден.", show_alert=True)
        return
    await state.set_state(ShiftContextStates.waiting_context_text)
    await state.update_data(ctx_department_id=department_id)
    await cb.message.edit_text(
        f"✏️ <b>{department.emoji} {department.name}</b>\n\n"
        "Отправьте новый текст контекста (легенды) сообщением. "
        "Он заменит текущий и станет общим для всех педагогов департамента.",
        parse_mode="HTML",
        reply_markup=back_keyboard_admin(f"shift_ctx_dep:{department_id}"),
    )


@router.message(ShiftContextStates.waiting_context_text)
async def msg_shift_ctx_text(
    message: Message, state: FSMContext, session: AsyncSession, user: User
) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    department_id = data.get("ctx_department_id")
    if len(text) < 3:
        await message.answer("Слишком короткий текст. Попробуйте ещё раз.")
        return
    dep_repo = DepartmentRepository(session)
    await dep_repo.update_context(
        teacher_id=user.id, department_id=department_id, context=text
    )
    await state.clear()
    await message.answer(
        "✅ Контекст сохранён.",
        reply_markup=back_keyboard_admin(f"shift_ctx_dep:{department_id}"),
    )


@router.callback_query(F.data.startswith("shift_ctx_clear:"))
async def cb_shift_ctx_clear(
    cb: CallbackQuery, session: AsyncSession
) -> None:
    department_id = int(cb.data.split(":")[1])
    await cb.message.edit_text(
        "🗑 Удалить контекст этого департамента? Действие необратимо.",
        reply_markup=confirm_keyboard(
            yes_data=f"shift_ctx_clear_ok:{department_id}",
            no_data=f"shift_ctx_dep:{department_id}",
        ),
    )


@router.callback_query(F.data.startswith("shift_ctx_clear_ok:"))
async def cb_shift_ctx_clear_ok(
    cb: CallbackQuery, session: AsyncSession
) -> None:
    department_id = int(cb.data.split(":")[1])
    dep_repo = DepartmentRepository(session)
    await dep_repo.clear_context(department_id)
    await cb.answer("Контекст удалён.")
    # Возвращаемся к экрану департамента (уже без контекста).
    department = await dep_repo.get_by_id(department_id)
    await cb.message.edit_text(
        f"📖 <b>{department.emoji} {department.name}</b>\n\n"
        "<i>Контекст пока не задан.</i>",
        reply_markup=shift_context_actions_keyboard(
            department_id, department.shift_id, has_context=False
        ),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Педагоги смены + отвязка
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("shift_teachers:"))
async def cb_shift_teachers(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    shift_id = int(cb.data.split(":")[1])
    dep_repo = DepartmentRepository(session)
    pairs = await dep_repo.get_teachers_for_shift(shift_id)
    builder = InlineKeyboardBuilder()
    if not pairs:
        text = (
            "👨‍🏫 <b>Педагоги смены</b>\n\n"
            "К этой смене пока не привязан ни один педагог.\n"
            "Привяжите через «Привязать педагога» в меню смен."
        )
    else:
        lines = ["👨‍🏫 <b>Педагоги смены</b>\n"]
        for t, dep in pairs:
            lines.append(f"• {telegram_username(t)} — {dep.emoji} {dep.name}")
            builder.button(
                text=f"❌ {telegram_username(t)} · {dep.emoji}",
                callback_data=f"shift_unassign:{dep.id}:{t.id}",
            )
        lines.append("\nНажмите на педагога, чтобы отвязать его от департамента.")
        text = "\n".join(lines)
    builder.button(text="← Назад к смене", callback_data=f"shift_card:{shift_id}")
    builder.adjust(1)
    await cb.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("shift_unassign:"))
async def cb_shift_unassign(
    cb: CallbackQuery, session: AsyncSession
) -> None:
    _, dep_id_str, teacher_id_str = cb.data.split(":")
    department_id = int(dep_id_str)
    teacher_id = int(teacher_id_str)
    dep_repo = DepartmentRepository(session)
    department = await dep_repo.get_by_id(department_id)
    shift_id = department.shift_id if department else None
    await dep_repo.unassign_teacher(department_id, teacher_id)
    await cb.answer("Педагог отвязан.")
    # Перерисовываем список педагогов смены.
    pairs = await dep_repo.get_teachers_for_shift(shift_id) if shift_id else []

    builder = InlineKeyboardBuilder()
    if not pairs:
        text = "👨‍🏫 <b>Педагоги смены</b>\n\nПривязанных педагогов больше нет."
    else:
        lines = ["👨‍🏫 <b>Педагоги смены</b>\n"]
        for t, dep in pairs:
            lines.append(f"• {telegram_username(t)} — {dep.emoji} {dep.name}")
            builder.button(
                text=f"❌ {telegram_username(t)} · {dep.emoji}",
                callback_data=f"shift_unassign:{dep.id}:{t.id}",
            )
        lines.append("\nНажмите на педагога, чтобы отвязать его от департамента.")
        text = "\n".join(lines)
    builder.button(text="← Назад к смене", callback_data=f"shift_card:{shift_id}")
    builder.adjust(1)
    await cb.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Учащиеся смены (сводка по департаментам)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("shift_students:"))
async def cb_shift_students(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    shift_id = int(cb.data.split(":")[1])
    dep_repo = DepartmentRepository(session)
    student_repo = StudentRepository(session)
    departments = list(await dep_repo.get_by_shift(shift_id))
    lines = ["👦 <b>Учащиеся смены по департаментам</b>\n"]
    total = 0
    for d in departments:
        cnt = await student_repo.count_by_department(d.id)
        total += cnt
        lines.append(f"{d.emoji} {d.name}: <b>{cnt}</b>")
    lines.append(f"\nВсего учащихся: <b>{total}</b>")
    lines.append(
        "\nДобавлять/редактировать учащихся можно в разделе «👦 Учащиеся»."
    )
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_keyboard_admin(f"shift_card:{shift_id}"),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Архивирование прямо из карточки + архив смен и восстановление
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("shift_card_archive:"))
async def cb_shift_card_archive(
    cb: CallbackQuery, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    shift = await ShiftRepository(session).get_by_id(shift_id)
    shift_name = shift.name if shift else f"#{shift_id}"
    await cb.message.edit_text(
        f"Архивировать смену «{shift_name}»? Педагоги потеряют к ней доступ.\n"
        "Смену можно будет восстановить из «📦 Архив смен».",
        reply_markup=confirm_keyboard(
            yes_data=f"archive_confirm:{shift_id}",
            no_data=f"shift_card:{shift_id}",
        ),
    )


# archive_confirm:* уже обрабатывается ниже (общий обработатчик подтверждения),
# но тот требует state ArchiveShiftStates.confirm. Здесь пользователь мог прийти
# из карточки без state — поэтому добавляем state-agnostic обработчик.
@router.callback_query(F.data.startswith("archive_confirm:"))
async def cb_archive_confirm_any(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    ok = await ShiftRepository(session).archive(shift_id)
    await state.clear()
    text = "✅ Смена архивирована." if ok else "❌ Смена не найдена."
    await cb.message.edit_text(text, reply_markup=back_keyboard_admin("admin:shifts:list"))


@router.callback_query(F.data == "admin:shifts:archived")
async def cb_shifts_archived(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await state.clear()
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_all_archived())
    if not shifts:
        await cb.message.edit_text(
            "📦 Архив пуст — архивированных смен нет.",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return
    builder = InlineKeyboardBuilder()
    for s in shifts:
        builder.button(
            text=f"♻️ {s.name}",
            callback_data=f"shift_restore:{s.id}",
        )
    builder.button(text="← Назад", callback_data="admin:shifts")
    builder.adjust(1)
    await cb.message.edit_text(
        "📦 <b>Архив смен</b>\n\nНажмите на смену, чтобы вернуть её в активные:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("shift_restore:"))
async def cb_shift_restore(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    ok = await ShiftRepository(session).restore(shift_id)
    await cb.answer("Смена восстановлена." if ok else "Смена не найдена.")
    await cb_shifts_archived(cb, state, session)



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
    # Педагог ещё не известен — выбираем его на последнем шаге.
    await state.update_data(assign_teacher_id=None)
    await _start_shift_selection(cb, state, session)


@router.callback_query(F.data == "admin:users:add:assign")
async def cb_assign_new_teacher_start(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """
    Запуск привязки сразу после добавления педагога.
    ID нового педагога уже лежит в state (assign_teacher_id) — на шаге
    выбора департамента привязка выполнится без повторного выбора педагога.
    """
    data = await state.get_data()
    teacher_id = data.get("assign_teacher_id")
    if not teacher_id:
        await cb.answer("Педагог не найден, начните заново.", show_alert=True)
        return
    await state.set_state(None)
    await state.update_data(assign_teacher_id=teacher_id)
    await _start_shift_selection(cb, state, session)


async def _start_shift_selection(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Показывает список активных смен для привязки педагога."""
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
        builder.button(text=f"{s.name}", callback_data=f"assign_shift:{s.id}")
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

    # Если педагог уже известен (сценарий «сразу после добавления»),
    # привязываем его без повторного выбора из списка.
    data = await state.get_data()
    known_teacher_id = data.get("assign_teacher_id")
    if known_teacher_id:
        dep_repo = DepartmentRepository(session)
        department = await dep_repo.get_by_id(department_id)
        await dep_repo.assign_teacher(department_id=department_id, teacher_id=known_teacher_id)
        await state.clear()
        await cb.message.edit_text(
            f"✅ Педагог привязан к департаменту "
            f"<b>{department.emoji + ' ' + department.name if department else department_id}</b>.",
            parse_mode="HTML",
            reply_markup=back_keyboard_admin("admin:shifts"),
        )
        return

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
        builder.button(text=user_button_label(t), callback_data=f"assign_teacher:{t.id}")
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
        builder.button(text=f"{s.name}", callback_data=f"archive_shift:{s.id}")
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
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(archive_shift_id=shift_id)
    await state.set_state(ArchiveShiftStates.confirm)
    shift = await ShiftRepository(session).get_by_id(shift_id)
    shift_name = shift.name if shift else f"#{shift_id}"
    from app.bot.keyboards.admin_menu import confirm_keyboard
    await cb.message.edit_text(
        f"Архивировать смену «{shift_name}»? Педагоги потеряют к ней доступ.",
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

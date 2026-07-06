import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import (
    admin_main_menu, users_menu, roles_keyboard, users_list_keyboard,
    back_keyboard, confirm_keyboard, request_user_keyboard, remove_reply_keyboard,
    assign_new_teacher_keyboard,
)

from app.bot.states.admin_states import (
    AddUserStates, ChangeRoleStates, DeactivateUserStates,
)
from app.bot.utils.user_display import user_greeting_name, user_stats_label
from app.database.models import User, UserRole
from app.repositories.user_repo import UserRepository
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = Router(name="admin_roles")


# ---------------------------------------------------------------------------
# Фильтр: только admin (роль moderator удалена 2026-07-03)
# ---------------------------------------------------------------------------

def admin_or_mod(user: User) -> bool:
    return user.role == UserRole.admin


def _shared_user_display_name(shared_user: object) -> str | None:
    """Имя из Telegram SharedUser, если username недоступен."""
    first_name = getattr(shared_user, "first_name", None)
    last_name = getattr(shared_user, "last_name", None)
    display_name = " ".join(part for part in [first_name, last_name] if part).strip()
    return display_name or None


async def _ask_role(
    message: Message,
    state: FSMContext,
    user_id: int,
    username: str | None = None,
    display_name: str | None = None,
) -> None:
    """Сохраняет Telegram ID/username/name и сразу переводит к выбору роли без ввода ФИО."""
    await state.update_data(
        new_user_id=user_id,
        new_username=username,
        new_display_name=display_name,
    )
    await state.set_state(AddUserStates.waiting_role)
    display = f"@{username}" if username else (display_name or f"@{user_id}")
    await message.answer(
        f"✅ Пользователь выбран: <b>{display}</b>\n"
        f"ID: <code>@{user_id}</code>\n\n"
        "Выберите роль:",
        reply_markup=roles_keyboard(),
    )



# ---------------------------------------------------------------------------
# /admin — главное меню
# ---------------------------------------------------------------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message, user: User) -> None:
    if not admin_or_mod(user):
        await message.answer("У вас нет доступа к этому разделу.")
        return
    await message.answer(
        "🔧 <b>Панель администратора</b>\nВыберите раздел:",
        reply_markup=admin_main_menu(is_admin=user.role == UserRole.admin),
    )


@router.callback_query(F.data == "admin:main")
async def cb_admin_main(cb: CallbackQuery, user: User) -> None:
    if not admin_or_mod(user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await cb.message.edit_text(
        "🔧 <b>Панель администратора</b>\nВыберите раздел:",
        reply_markup=admin_main_menu(is_admin=user.role == UserRole.admin),
    )


@router.callback_query(F.data == "admin:users")
async def cb_users_menu(cb: CallbackQuery, user: User) -> None:
    if not admin_or_mod(user):
        await cb.answer("Нет доступа", show_alert=True)
        return
    await cb.message.edit_text(
        "👥 <b>Управление пользователями</b>",
        reply_markup=users_menu(is_admin=user.role == UserRole.admin),
    )


@router.callback_query(F.data == "admin:cancel")
async def cb_cancel(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    await state.clear()
    await cb.message.edit_text(
        "🔧 <b>Панель администратора</b>",
        reply_markup=admin_main_menu(is_admin=user.role == UserRole.admin),
    )


# ---------------------------------------------------------------------------
# Добавить пользователя
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:users:add")
async def cb_add_user_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddUserStates.waiting_user_id)
    await cb.message.edit_text(
        "➕ <b>Добавить пользователя</b>\n\n"
        "Отправьте одно из следующего:\n"
        "• Числовой <b>Telegram ID</b> — подойдёт <u>любой</u> ID, даже если "
        "пользователь ещё ни разу не писал боту (узнать ID можно через @userinfobot)\n"
        "• Ник в формате <b>@username</b>\n"
        "• Нажмите кнопку <b>«👤 Выбрать пользователя»</b> ниже — откроется список "
        "контактов Telegram, выберите нужного человека.",
    )
    # Reply-клавиатуру нельзя прикрепить к inline-сообщению (edit_text),
    # поэтому отправляем её отдельным сообщением.
    await cb.message.answer(
        "👇 Выберите пользователя кнопкой или отправьте ID/@username сообщением:",
        reply_markup=request_user_keyboard(),
    )


@router.message(AddUserStates.waiting_user_id, F.users_shared)
async def add_user_shared(message: Message, state: FSMContext) -> None:
    """
    Обработка нативного выбора пользователя через кнопку request_users.
    Возвращает реальный Telegram ID даже для тех, кто не писал боту.
    """
    shared = message.users_shared
    # Bot API 7.2 переименовал user_ids → users (list[SharedUser]).
    # Поддерживаем оба варианта, чтобы не зависеть от точной версии Bot API.
    tg_id = None
    if shared:
        users = getattr(shared, "users", None)
        if users:
            tg_id = users[0].user_id
        else:
            user_ids = getattr(shared, "user_ids", None)
            if user_ids:
                tg_id = user_ids[0]
    if not tg_id:
        await message.answer(
            "⚠️ Не удалось получить пользователя. Попробуйте ещё раз или введите ID.",
            reply_markup=remove_reply_keyboard(),
        )
        return

    username = None
    display_name = None
    if shared and getattr(shared, "users", None):
        shared_user = shared.users[0]
        username = getattr(shared_user, "username", None)
        display_name = _shared_user_display_name(shared_user)

    await message.answer("Клавиатура выбора пользователя убрана.", reply_markup=remove_reply_keyboard())
    await _ask_role(message, state, user_id=tg_id, username=username, display_name=display_name)


@router.message(AddUserStates.waiting_user_id)
async def add_user_id(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Принимает:
    - числовой ID (любой, даже если юзер не писал боту)
    - @username или @<числовой id>
    - пересланный контакт (message.contact)
    - «Отмена» с reply-клавиатуры
    """
    text = (message.text or "").strip()

    # Отмена с reply-клавиатуры
    if text == "❌ Отмена":
        await state.clear()
        await message.answer(
            "Добавление пользователя отменено.",
            reply_markup=remove_reply_keyboard(),
        )
        await message.answer(
            "👥 <b>Управление пользователями</b>",
            reply_markup=users_menu(),
        )
        return

    # Вариант 1: пересланный контакт
    if message.contact:
        tg_id = message.contact.user_id
        if not tg_id:
            await message.answer(
                "⚠️ Не удалось получить Telegram ID из контакта.\n"
                "Попросите пользователя переслать контакт самостоятельно, "
                "или воспользуйтесь кнопкой «👤 Выбрать пользователя»."
            )
            return
        contact_name = " ".join(
            filter(None, [message.contact.first_name, message.contact.last_name])
        ).strip() or None
        await message.answer("Клавиатура выбора пользователя убрана.", reply_markup=remove_reply_keyboard())
        await _ask_role(message, state, user_id=tg_id, display_name=contact_name)
        return

    # Нормализуем: убираем ведущий @ — поддерживаем и @123456, и @username
    normalized = text.lstrip("@").strip()

    # Вариант 2: числовой ID (в т.ч. вида @123456).
    # Принимаем ЛЮБОЙ числовой ID, даже если пользователь не писал боту.
    if normalized.isdigit():
        await message.answer("Клавиатура выбора пользователя убрана.", reply_markup=remove_reply_keyboard())
        await _ask_role(message, state, user_id=int(normalized))
        return

    # Вариант 3: @username (текстовый ник)
    if normalized:
        repo = UserRepository(session)
        found_user = await repo.get_by_username(normalized)
        if found_user:
            await message.answer("Клавиатура выбора пользователя убрана.", reply_markup=remove_reply_keyboard())
            await _ask_role(message, state, user_id=found_user.id, username=found_user.username or normalized)
        else:
            # По username бот не может узнать ID, если человек не писал боту —
            # это ограничение Telegram. Предлагаем нативный выбор / числовой ID.
            await message.answer(
                f"⚠️ Не удалось определить ID по нику <b>@{normalized}</b>.\n\n"
                "Telegram не позволяет узнать ID по нику, если пользователь ещё "
                "не писал боту.\n\n"
                "Что можно сделать:\n"
                "• нажмите кнопку <b>«👤 Выбрать пользователя»</b> ниже — сработает "
                "для любого контакта;\n"
                "• или отправьте числовой <b>Telegram ID</b> (узнать через @userinfobot).",
                reply_markup=request_user_keyboard(),
            )
        return

    await message.answer(
        "⚠️ Неверный формат. Отправьте числовой Telegram ID, @username, "
        "перешлите контакт или воспользуйтесь кнопкой «👤 Выбрать пользователя».",
        reply_markup=request_user_keyboard(),
    )
@router.callback_query(AddUserStates.waiting_role, F.data.startswith("role:"))
async def add_user_role(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    role_value = cb.data.split(":")[1]
    try:
        role = UserRole(role_value)
    except ValueError:
        await cb.answer("Неверная роль", show_alert=True)
        return

    data = await state.get_data()
    await state.update_data(role=role_value)
    await state.set_state(AddUserStates.confirm)
    display = (
        f"@{data['new_username']}"
        if data.get("new_username")
        else data.get("new_display_name") or "—"
    )

    await cb.message.edit_text(
        f"Подтвердите добавление пользователя:\n"
        f"• Ник/имя Telegram: <b>{display}</b>\n"
        f"• ID: <code>@{data['new_user_id']}</code>\n"
        f"• Роль: <b>{role.value}</b>",
        reply_markup=confirm_keyboard(yes_data="admin:users:add:confirm"),
    )


@router.callback_query(AddUserStates.confirm, F.data == "admin:users:add:confirm")
async def add_user_confirm(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    try:
        data = await state.get_data()
        service = UserService(session)
        role = UserRole(data["role"])
        result = await service.add_user(
            actor=user,
            new_user_id=data["new_user_id"],
            role=role,
            username=data.get("new_username"),
            display_name=data.get("new_display_name"),
        )
        if role == UserRole.teacher:
            # Педагога сразу предлагаем назначить на смену/департамент.
            # В state оставляем только ID нового педагога для следующего шага.
            new_teacher_id = data["new_user_id"]
            await state.clear()
            await state.update_data(assign_teacher_id=new_teacher_id)
            await cb.message.edit_text(
                result.message
                + "\n\nХотите сразу назначить педагога на смену и департамент?",
                reply_markup=assign_new_teacher_keyboard(),
            )
        else:
            await state.clear()
            await cb.message.edit_text(
                result.message,
                reply_markup=back_keyboard("admin:users"),
            )
        await cb.answer()
    except Exception as e:
        logger.exception(f"Error in add_user_confirm: {e}")
        await cb.answer("⚠️ Произошла ошибка. Попробуйте снова.", show_alert=True)


@router.callback_query(F.data == "admin:users:add:skip")
async def cb_add_user_skip(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    """Пропустить назначение только что добавленного педагога на смену/департамент."""
    await state.clear()
    await cb.message.edit_text(
        "👥 <b>Управление пользователями</b>",
        reply_markup=users_menu(is_admin=user.role == UserRole.admin),
    )
    await cb.answer()



# ---------------------------------------------------------------------------
# Список педагогов
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:users:list")
async def cb_users_list(cb: CallbackQuery, session: AsyncSession) -> None:
    repo = UserRepository(session)
    teachers = await repo.get_by_role(UserRole.teacher)
    if not teachers:
        await cb.message.edit_text(
            "Педагоги не найдены.",
            reply_markup=back_keyboard("admin:users"),
        )
        return
    lines = [f"👨‍🏫 <b>Педагоги ({len(teachers)}):</b>"]
    for t in teachers:
        status = "✅" if t.is_active else "🚫"
        lines.append(f"{status} {user_stats_label(t)}")
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=back_keyboard("admin:users"),
    )


# ---------------------------------------------------------------------------
# Изменить роль (только admin)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:users:change_role")
async def cb_change_role_start(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    if user.role != UserRole.admin:
        await cb.answer("Только администратор может менять роли.", show_alert=True)
        return
    repo = UserRepository(session)
    users = list(await repo.get_all_active())
    users = [u for u in users if u.id != user.id]
    if not users:
        await cb.message.edit_text("Нет других пользователей.", reply_markup=back_keyboard("admin:users"))
        return
    await state.set_state(ChangeRoleStates.waiting_user_select)
    await cb.message.edit_text(
        "Выберите пользователя для изменения роли:",
        reply_markup=users_list_keyboard(users),
    )


@router.callback_query(ChangeRoleStates.waiting_user_select, F.data.startswith("select_user:"))
async def change_role_user_selected(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    target_id = int(cb.data.split(":")[1])
    repo = UserRepository(session)
    target = await repo.get_by_id(target_id)
    if not target:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    await state.update_data(target_user_id=target_id)
    await state.set_state(ChangeRoleStates.waiting_new_role)
    await cb.message.edit_text(
        f"Текущая роль <b>{user_greeting_name(target)}</b>: {target.role.value}\n"
        f"ID: <code>@{target.id}</code>\n\n"
        "Выберите новую роль:",
        reply_markup=roles_keyboard(exclude_role=target.role),
    )


@router.callback_query(ChangeRoleStates.waiting_new_role, F.data.startswith("role:"))
async def change_role_confirm(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    try:
        new_role = UserRole(cb.data.split(":")[1])
        data = await state.get_data()
        service = UserService(session)
        result = await service.change_role(
            actor=user,
            target_user_id=data["target_user_id"],
            new_role=new_role,
        )
        await state.clear()
        await cb.message.edit_text(result.message, reply_markup=back_keyboard("admin:users"))
        await cb.answer()
    except Exception as e:
        logger.exception(f"Error in change_role_confirm: {e}")
        await cb.answer("⚠️ Произошла ошибка. Попробуйте снова.", show_alert=True)



# ---------------------------------------------------------------------------
# Деактивировать пользователя
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:users:deactivate")
async def cb_deactivate_start(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    repo = UserRepository(session)
    users = [u for u in await repo.get_all_active() if u.id != user.id]
    if not users:
        await cb.message.edit_text("Нет пользователей для деактивации.", reply_markup=back_keyboard("admin:users"))
        return
    await state.set_state(DeactivateUserStates.waiting_user_select)
    await cb.message.edit_text(
        "Выберите пользователя для деактивации:",
        reply_markup=users_list_keyboard(users),
    )


@router.callback_query(DeactivateUserStates.waiting_user_select, F.data.startswith("select_user:"))
async def deactivate_user_selected(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    target_id = int(cb.data.split(":")[1])
    repo = UserRepository(session)
    target = await repo.get_by_id(target_id)
    if not target:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    await state.update_data(target_user_id=target_id)
    await state.set_state(DeactivateUserStates.confirm)
    await cb.message.edit_text(
        f"Деактивировать <b>{user_greeting_name(target)}</b> "
        f"(<code>@{target.id}</code>)? Пользователь потеряет доступ к боту.",
        reply_markup=confirm_keyboard(yes_data="admin:users:deactivate:confirm"),
    )


@router.callback_query(DeactivateUserStates.confirm, F.data == "admin:users:deactivate:confirm")
async def deactivate_confirm(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    try:
        data = await state.get_data()
        service = UserService(session)
        result = await service.deactivate(actor=user, target_user_id=data["target_user_id"])
        await state.clear()
        await cb.message.edit_text(result.message, reply_markup=back_keyboard("admin:users"))
        await cb.answer()
    except Exception as e:
        logger.exception(f"Error in deactivate_confirm: {e}")
        await cb.answer("⚠️ Произошла ошибка. Попробуйте снова.", show_alert=True)

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import (
    admin_main_menu, users_menu, roles_keyboard, users_list_keyboard,
    back_keyboard, confirm_keyboard,
)
from app.bot.states.admin_states import (
    AddUserStates, ChangeRoleStates, DeactivateUserStates,
)
from app.database.models import User, UserRole
from app.repositories.user_repo import UserRepository
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = Router(name="admin_roles")


# ---------------------------------------------------------------------------
# Фильтр: только admin и moderator
# ---------------------------------------------------------------------------

def admin_or_mod(user: User) -> bool:
    return user.role in (UserRole.admin, UserRole.moderator)


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
        "• Числовой <b>Telegram ID</b> (узнать через @userinfobot)\n"
        "• Ник в формате <b>@username</b>\n"
        "• Перешлите <b>контакт</b> пользователя (через скрепку → Контакт)",
        reply_markup=back_keyboard("admin:users"),
    )


@router.message(AddUserStates.waiting_user_id)
async def add_user_id(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """
    Принимает:
    - числовой ID
    - @username
    - пересланный контакт (message.contact)
    """
    # Вариант 1: пересланный контакт
    if message.contact:
        tg_id = message.contact.user_id
        if not tg_id:
            await message.answer(
                "⚠️ Не удалось получить Telegram ID из контакта.\n"
                "Попросите пользователя переслать контакт самостоятельно."
            )
            return
        await state.update_data(new_user_id=tg_id)
        await state.set_state(AddUserStates.waiting_full_name)
        # Предзаполняем имя из контакта
        contact_name = " ".join(
            filter(None, [message.contact.first_name, message.contact.last_name])
        ).strip()
        if contact_name:
            await state.update_data(prefilled_name=contact_name)
            await message.answer(
                f"✅ Контакт получен. ID: <code>{tg_id}</code>\n\n"
                f"Введите <b>полное имя</b> пользователя (Фамилия Имя Отчество)\n"
                f"или отправьте <b>.</b> чтобы использовать имя из контакта: <b>{contact_name}</b>"
            )
        else:
            await message.answer(
                f"✅ Контакт получен. ID: <code>{tg_id}</code>\n\n"
                "Введите <b>полное имя</b> пользователя (Фамилия Имя Отчество):"
            )
        return

    text = (message.text or "").strip()

    # Вариант 2: числовой ID
    if text.isdigit():
        await state.update_data(new_user_id=int(text))
        await state.set_state(AddUserStates.waiting_full_name)
        await message.answer("Введите <b>полное имя</b> пользователя (Фамилия Имя Отчество):")
        return

    # Вариант 3: @username
    if text.startswith("@") or (text and not text.isdigit()):
        username = text.lstrip("@")
        repo = UserRepository(session)
        found_user = await repo.get_by_username(username)
        if found_user:
            await state.update_data(new_user_id=found_user.id)
            await state.set_state(AddUserStates.waiting_full_name)
            await message.answer(
                f"✅ Найден пользователь <b>@{username}</b> (ID: <code>{found_user.id}</code>)\n\n"
                "Введите <b>полное имя</b> (или отправьте <b>.</b> чтобы оставить текущее: "
                f"<b>{found_user.full_name}</b>):"
            )
            await state.update_data(prefilled_name=found_user.full_name)
        else:
            await message.answer(
                f"⚠️ Пользователь <b>@{username}</b> не найден в системе.\n\n"
                "Пользователь должен сначала написать боту хотя бы раз, "
                "чтобы попасть в базу.\n\n"
                "Введите числовой <b>Telegram ID</b> или перешлите контакт:"
            )
        return

    await message.answer(
        "⚠️ Неверный формат. Введите числовой Telegram ID, @username или перешлите контакт."
    )


@router.message(AddUserStates.waiting_full_name)
async def add_user_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prefilled_name = data.get("prefilled_name", "")

    raw = (message.text or "").strip()
    # Точка = использовать предзаполненное имя
    if raw == "." and prefilled_name:
        full_name = prefilled_name
    else:
        full_name = raw

    if len(full_name) < 2:
        await message.answer("⚠️ Имя слишком короткое. Введите ещё раз:")
        return

    await state.update_data(full_name=full_name)
    await state.set_state(AddUserStates.waiting_role)
    await message.answer(
        f"Выберите роль для <b>{full_name}</b>:",
        reply_markup=roles_keyboard(),
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

    await cb.message.edit_text(
        f"Подтвердите добавление пользователя:\n"
        f"• ID: <code>{data['new_user_id']}</code>\n"
        f"• Имя: <b>{data['full_name']}</b>\n"
        f"• Роль: <b>{role.value}</b>",
        reply_markup=confirm_keyboard(yes_data="admin:users:add:confirm"),
    )


@router.callback_query(AddUserStates.confirm, F.data == "admin:users:add:confirm")
async def add_user_confirm(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    service = UserService(session)
    result = await service.add_user(
        actor=user,
        new_user_id=data["new_user_id"],
        full_name=data["full_name"],
        role=UserRole(data["role"]),
    )
    await state.clear()
    await cb.message.edit_text(
        result.message,
        reply_markup=back_keyboard("admin:users"),
    )


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
        uname = f"@{t.username}" if t.username else "—"
        status = "✅" if t.is_active else "🚫"
        lines.append(f"{status} {t.full_name} | {uname} | <code>{t.id}</code>")
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
        f"Текущая роль <b>{target.full_name}</b>: {target.role.value}\nВыберите новую роль:",
        reply_markup=roles_keyboard(exclude_role=target.role),
    )


@router.callback_query(ChangeRoleStates.waiting_new_role, F.data.startswith("role:"))
async def change_role_confirm(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
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
        f"Деактивировать <b>{target.full_name}</b>? Пользователь потеряет доступ к боту.",
        reply_markup=confirm_keyboard(yes_data="admin:users:deactivate:confirm"),
    )


@router.callback_query(DeactivateUserStates.confirm, F.data == "admin:users:deactivate:confirm")
async def deactivate_confirm(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    service = UserService(session)
    result = await service.deactivate(actor=user, target_user_id=data["target_user_id"])
    await state.clear()
    await cb.message.edit_text(result.message, reply_markup=back_keyboard("admin:users"))
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.bot.utils.user_display import user_button_label
from app.database.models import Shift, User, UserRole, DEPARTMENTS, Department


# request_id для кнопки выбора пользователя (KeyboardButtonRequestUsers).
# Значение произвольное, используется Telegram для сопоставления запрос/ответ.
REQUEST_USER_ID = 1


def request_user_keyboard() -> ReplyKeyboardMarkup:
    """
    Reply-клавиатура с нативной кнопкой выбора пользователя Telegram.

    В отличие от «пересылки контакта через скрепку» (которой в клиенте нет),
    кнопка request_users открывает системный список пользователей Telegram и
    возвращает НАСТОЯЩИЙ Telegram ID выбранного человека — даже если он ни разу
    не писал боту. Ответ приходит в message.users_shared.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="👤 Выбрать пользователя",
                    request_users=KeyboardButtonRequestUsers(
                        request_id=REQUEST_USER_ID,
                        user_is_bot=False,
                        max_quantity=1,
                        request_name=True,
                        request_username=True,
                    ),
                )
            ],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="ID / @username или выберите пользователя кнопкой ниже",
    )


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    """Убрать reply-клавиатуру."""
    return ReplyKeyboardRemove()




def admin_main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню администратора/модератора."""
    rows = [
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")],
        [InlineKeyboardButton(text="🏕 Смены",        callback_data="admin:shifts")],
        [InlineKeyboardButton(text="👦 Учащиеся",     callback_data="admin:students")],
        [InlineKeyboardButton(text="📝 Заполнить отчёты", callback_data="admin:fill")],
        [InlineKeyboardButton(text="📥 Скачать отчёты", callback_data="export:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)



def users_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Меню управления пользователями."""
    rows = [
        [InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="admin:users:add")],

        [InlineKeyboardButton(text="👁 Список педагогов",             callback_data="admin:users:list")],
        [InlineKeyboardButton(text="👑 Список админов",              callback_data="admin:users:admins")],
    ]
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="🔄 Изменить роль", callback_data="admin:users:change_role")]
        )
    rows.append([InlineKeyboardButton(text="Удалить пользователя", callback_data="admin:users:deactivate")])
    rows.append([InlineKeyboardButton(text="← Назад",           callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def shifts_menu() -> InlineKeyboardMarkup:
    """Меню управления сменами."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать смену",       callback_data="admin:shifts:create")],
            [InlineKeyboardButton(text="👁 Список смен",         callback_data="admin:shifts:list")],
            [InlineKeyboardButton(text="👨‍🏫 Привязать педагога", callback_data="admin:shifts:assign")],
            [InlineKeyboardButton(text="🗑 Архивировать смену",  callback_data="admin:shifts:archive")],
            [InlineKeyboardButton(text="← Назад",               callback_data="admin:main")],
        ]
    )


def students_menu() -> InlineKeyboardMarkup:
    """Меню управления учащимися."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить учащегося",  callback_data="admin:students:add")],
            [InlineKeyboardButton(text="📋 Список учащихся",     callback_data="admin:students:list")],
            [InlineKeyboardButton(text="✏️ Редактировать имя",   callback_data="admin:students:edit")],
            [InlineKeyboardButton(text="🗑 Удалить учащегося",   callback_data="admin:students:delete")],
            [InlineKeyboardButton(text="← Назад",               callback_data="admin:main")],
        ]
    )


def departments_keyboard() -> InlineKeyboardMarkup:
    """Список департаментов для выбора при создании смены."""
    builder = InlineKeyboardBuilder()
    # DEPARTMENTS — dict[int, dict], итерируем .items()
    for dept_id, dept_info in DEPARTMENTS.items():
        builder.button(
            text=f"{dept_info.get('emoji', '🏢')} {dept_info['name']}",
            callback_data=f"dept:{dept_id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def shifts_list_keyboard(shifts: list[Shift]) -> InlineKeyboardMarkup:
    """Список смен в виде inline-кнопок."""
    builder = InlineKeyboardBuilder()
    for shift in shifts:
        builder.button(
            text=f"[{shift.id}] {shift.name}",
            callback_data=f"select_shift:{shift.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def departments_list_keyboard(
    departments: list[Department], back_to: str = "admin:shifts"
) -> InlineKeyboardMarkup:
    """Список департаментов смены в виде inline-кнопок."""
    builder = InlineKeyboardBuilder()
    for d in departments:
        builder.button(
            text=f"{d.emoji} {d.name}",
            callback_data=f"select_department:{d.id}",
        )
    builder.button(text="← Назад", callback_data=back_to)
    builder.adjust(1)
    return builder.as_markup()


def users_list_keyboard(users: list[User]) -> InlineKeyboardMarkup:

    """Список пользователей в виде inline-кнопок."""
    builder = InlineKeyboardBuilder()
    for u in users:
        label = user_button_label(u)
        builder.button(text=label, callback_data=f"select_user:{u.id}")
    builder.adjust(1)
    return builder.as_markup()


def students_list_keyboard(students: list) -> InlineKeyboardMarkup:
    """Список учащихся в виде inline-кнопок."""
    builder = InlineKeyboardBuilder()
    for s in students:
        builder.button(
            text=f"{s.position}. {s.full_name}",
            callback_data=f"select_student:{s.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def roles_keyboard(exclude_role: UserRole | None = None) -> InlineKeyboardMarkup:
    """Клавиатура выбора роли."""
    builder = InlineKeyboardBuilder()
    for role in UserRole:
        if role == exclude_role:
            continue
        labels = {
            UserRole.admin:     "👑 Администратор",
            UserRole.teacher:   "👨‍🏫 Педагог",
        }
        builder.button(text=labels[role], callback_data=f"role:{role.value}")

    builder.adjust(1)
    return builder.as_markup()


def assign_new_teacher_keyboard() -> InlineKeyboardMarkup:
    """Предложение назначить только что добавленного педагога на смену/департамент."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🏕 Назначить на смену и департамент",
                callback_data="admin:users:add:assign",
            )],
            [InlineKeyboardButton(
                text="⏭ Пропустить",
                callback_data="admin:users:add:skip",
            )],
        ]
    )


def confirm_keyboard(yes_data: str, no_data: str = "admin:cancel") -> InlineKeyboardMarkup:
    """Клавиатура подтверждения действия."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, подтвердить", callback_data=yes_data),
                InlineKeyboardButton(text="❌ Отмена",          callback_data=no_data),
            ]
        ]
    )


def back_keyboard(back_to: str) -> InlineKeyboardMarkup:
    """Кнопка «Назад» к указанному разделу."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data=back_to)]
        ]
    )


def back_keyboard_admin(back_to: str) -> InlineKeyboardMarkup:
    """Алиас back_keyboard для admin-хендлеров (импортируется в shifts.py)."""
    return back_keyboard(back_to)

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database.models import Shift, User, UserRole, DEPARTMENTS, Department



def admin_main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню администратора/модератора."""
    rows = [
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")],
        [InlineKeyboardButton(text="🏕 Смены",        callback_data="admin:shifts")],
        [InlineKeyboardButton(text="👦 Учащиеся",     callback_data="admin:students")],
        [InlineKeyboardButton(text="📝 Заполнить отчёты", callback_data="admin:fill")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)



def users_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Меню управления пользователями."""
    rows = [
        [InlineKeyboardButton(text="➕ Добавить педагога/модератора", callback_data="admin:users:add")],
        [InlineKeyboardButton(text="👁 Список педагогов",             callback_data="admin:users:list")],
    ]
    if is_admin:
        rows.append(
            [InlineKeyboardButton(text="🔄 Изменить роль", callback_data="admin:users:change_role")]
        )
    rows.append([InlineKeyboardButton(text="🚫 Деактивировать", callback_data="admin:users:deactivate")])
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
        builder.button(text=dept_info["name"], callback_data=f"dept:{dept_id}")
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
            text=d.name,
            callback_data=f"select_department:{d.id}",
        )
    builder.button(text="← Назад", callback_data=back_to)
    builder.adjust(1)
    return builder.as_markup()


def users_list_keyboard(users: list[User]) -> InlineKeyboardMarkup:

    """Список пользователей в виде inline-кнопок."""
    builder = InlineKeyboardBuilder()
    for u in users:
        label = f"{u.full_name} ({u.role.value})"
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
            UserRole.moderator: "🛡 Модератор",
            UserRole.teacher:   "👨‍🏫 Педагог",
        }
        builder.button(text=labels[role], callback_data=f"role:{role.value}")
    builder.adjust(1)
    return builder.as_markup()


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
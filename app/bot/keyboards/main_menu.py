from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.child_menu import CHILDREN_PAGE_SIZE, paginate



def teacher_main_menu() -> InlineKeyboardMarkup:
    """Главное меню педагога."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📂 Мои смены",
                    callback_data="teacher:shifts",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Скачать отчёты",
                    callback_data="export:menu",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Все отчёты смены",
                    callback_data="export:all",
                )
            ],
        ]
    )


def after_finalize_menu(done: int, total: int) -> InlineKeyboardMarkup:
    """Меню после финализации отчёта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➡️ Следующий ребёнок",
                    callback_data="teacher:next_child",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Список детей",
                    callback_data="teacher:child_list",
                ),
                InlineKeyboardButton(
                    text="📥 Скачать отчёты",
                    callback_data="export:menu",
                ),
                InlineKeyboardButton(
                    text="📦 Все отчёты",
                    callback_data="export:all",
                ),
            ],
        ]
    )


def export_menu(back_callback: str | None = None) -> InlineKeyboardMarkup:
    """Актуальное меню экспорта с тремя отдельными сценариями."""
    return export_mode_menu(back_callback=back_callback)


def export_mode_menu(back_callback: str | None = None) -> InlineKeyboardMarkup:
    """Первый шаг скачивания: выбрать один из трёх сценариев."""
    rows = [
        [
            InlineKeyboardButton(
                text="👤 Отчёт одного ребёнка",
                callback_data="export:mode:child",
            )
        ],
        [
            InlineKeyboardButton(
                text="🏢 Отчёты департамента",
                callback_data="export:mode:department",
            )
        ],
        [
            InlineKeyboardButton(
                text="🏕 Скачать все отчёты смены",
                callback_data="export:mode:all",
            )
        ],
    ]
    if back_callback:
        rows.append([InlineKeyboardButton(text="← Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def export_shifts_keyboard(
    shifts: list,
    back_callback: str = "export:menu",
) -> InlineKeyboardMarkup:
    """Выбор смены для экспорта."""
    builder = InlineKeyboardBuilder()
    for shift in shifts:
        builder.button(
            text=f"🏕 {shift.name}",
            callback_data=f"export:shift:{shift.id}",
        )
    builder.button(text="← Назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def export_departments_keyboard(
    departments: list,
    back_callback: str = "export:menu",
) -> InlineKeyboardMarkup:
    """Выбор департамента для экспорта внутри выбранной смены."""
    builder = InlineKeyboardBuilder()
    for d in departments:
        builder.button(
            text=f"{d.emoji} {d.name}",
            callback_data=f"export:dep:{d.id}",
        )
    builder.button(text="← Назад", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()


def export_format_keyboard(scope: str, back_callback: str = "export:menu") -> InlineKeyboardMarkup:
    """Выбор формата файла для текущего сценария экспорта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 PPTX", callback_data=f"export:{scope}_fmt:pptx"
                ),
                InlineKeyboardButton(
                    text="📕 PDF", callback_data=f"export:{scope}_fmt:pdf"
                ),
            ],
            [InlineKeyboardButton(text="← Назад", callback_data=back_callback)],
        ]
    )


def export_children_keyboard(
    students: list,
    page: int = 0,
    page_size: int = CHILDREN_PAGE_SIZE,
    back_callback: str = "export:menu",
) -> InlineKeyboardMarkup:
    """Постраничный список детей с готовыми (финализированными) отчётами."""
    builder = InlineKeyboardBuilder()
    page, total_pages, start = paginate(len(students), page, page_size)
    for s in students[start:start + page_size]:
        builder.button(
            text=f"✅ {s.full_name}",
            callback_data=f"export:child:{s.id}",
        )
    builder.adjust(1)

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    text="⬅️", callback_data=f"export:child_page:{page - 1}"
                )
            )
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}", callback_data="export:child_page:noop"
            )
        )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    text="➡️", callback_data=f"export:child_page:{page + 1}"
                )
            )
        builder.row(*nav)

    builder.row(InlineKeyboardButton(text="← Назад", callback_data=back_callback))
    return builder.as_markup()










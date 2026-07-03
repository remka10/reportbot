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
                    text="📦 Скачать все отчёты",
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


def export_menu() -> InlineKeyboardMarkup:
    """LEGACY-меню экспорта (быстрые кнопки для «текущего» ребёнка/смены из state).

    Оставлено для обратной совместимости — используется в некоторых
    промежуточных сообщениях. Новый пошаговый флоу — см. export_mode_menu().
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 PPTX (текущий)",
                    callback_data="export:single",
                ),
                InlineKeyboardButton(
                    text="📕 PDF (текущий)",
                    callback_data="export:single_pdf",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 Все PPTX (ZIP)",
                    callback_data="export:zip",
                ),
                InlineKeyboardButton(
                    text="📦 Все PDF (ZIP)",
                    callback_data="export:zip_pdf",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="← Назад",
                    callback_data="teacher:child_list",
                )
            ],
        ]
    )


def export_mode_menu() -> InlineKeyboardMarkup:
    """Первый шаг скачивания: выбрать что скачать — всю смену или одного ребёнка."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 Отчёты всей смены",
                    callback_data="export:mode:shift",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Отчёт одного ребёнка",
                    callback_data="export:mode:child",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Скачать все отчёты сразу",
                    callback_data="export:all",
                )
            ],
        ]
    )


def export_all_mode_menu() -> InlineKeyboardMarkup:
    """Быстрый вход в массовую выгрузку: сразу выбираем департамент для ZIP."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 ZIP PPTX по смене",
                    callback_data="export:mode:shift",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 ZIP PDF по смене",
                    callback_data="export:mode:shift_pdf",
                )
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="export:menu")],
        ]
    )


def export_departments_keyboard(
    departments: list, shift_name_map: dict[int, str]
) -> InlineKeyboardMarkup:
    """Выбор департамента/смены для экспорта."""
    builder = InlineKeyboardBuilder()
    for d in departments:
        shift_name = shift_name_map.get(d.shift_id, f"Смена {d.shift_id}")
        builder.button(
            text=f"📂 {shift_name} — {d.name}",
            callback_data=f"export:dep:{d.id}",
        )
    builder.button(text="← Назад", callback_data="export:menu")
    builder.adjust(1)
    return builder.as_markup()


def export_format_keyboard(scope: str, back_callback: str = "export:menu") -> InlineKeyboardMarkup:
    """Выбор формата файла. scope: 'shift' (ZIP всей смены) или 'child' (один ребёнок)."""
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
    students: list, page: int = 0, page_size: int = CHILDREN_PAGE_SIZE
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

    builder.row(InlineKeyboardButton(text="← Назад", callback_data="export:menu"))
    return builder.as_markup()





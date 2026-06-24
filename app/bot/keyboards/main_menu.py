from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


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
            ],
        ]
    )


def export_menu() -> InlineKeyboardMarkup:
    """Меню экспорта отчётов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 Скачать DOCX (текущий ребёнок)",
                    callback_data="export:single",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 Скачать все ZIP",
                    callback_data="export:zip",
                )
            ],
            [
                InlineKeyboardButton(
                    text="← Назад",
                    callback_data="teacher:child_list",
                )
            ],
        ]
    )
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Shift


def shifts_keyboard(shifts: list[Shift]) -> InlineKeyboardMarkup:
    """Список смен педагога."""
    builder = InlineKeyboardBuilder()
    for shift in shifts:
        builder.button(
            text=f"📂 {shift.name}",
            callback_data=f"teacher:shift:{shift.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def context_exists_keyboard() -> InlineKeyboardMarkup:
    """Кнопки при наличии существующего контекста смены."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Использовать",
                    callback_data="teacher:context:use",
                ),
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data="teacher:context:change",
                ),
            ]
        ]
    )
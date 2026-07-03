from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Shift, Department


def shifts_keyboard(shifts: list[Shift]) -> InlineKeyboardMarkup:
    """Список смен педагога (LEGACY — оставлено для совместимости)."""
    builder = InlineKeyboardBuilder()
    for shift in shifts:
        builder.button(
            text=f"📂 {shift.name}",
            callback_data=f"teacher:shift:{shift.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def departments_keyboard(
    departments: list[Department],
    shift_name_map: dict[int, str],
) -> InlineKeyboardMarkup:
    """
    Список департаментов педагога с указанием смены:
    «📂 Смена 1 2026 — Департамент управления».
    """
    builder = InlineKeyboardBuilder()
    for d in departments:
        shift_name = shift_name_map.get(d.shift_id, f"Смена {d.shift_id}")
        builder.button(
            text=f"📂 {shift_name} — {d.name}",
            callback_data=f"teacher:department:{d.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def context_exists_keyboard() -> InlineKeyboardMarkup:
    """Кнопки при наличии существующего контекста департамента.

    По требованию: если контекст смены уже введён, кнопка его изменения
    отображается ОТДЕЛЬНОЙ строкой (а не в одном ряду с «Использовать»).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Использовать сохранённый контекст",
                    callback_data="teacher:context:use",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить контекст смены",
                    callback_data="teacher:context:change",
                ),
            ],
        ]
    )



def context_preview_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки после того как ИИ оформил надиктованный контекст смены.
    Педагог может сохранить оформленный вариант, переформулировать (ИИ ещё раз)
    или ввести контекст заново.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сохранить",
                    callback_data="teacher:context:accept",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 Исправить с комментарием",
                    callback_data="teacher:context:revise",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Переформулировать",
                    callback_data="teacher:context:regenerate",
                ),
                InlineKeyboardButton(
                    text="✏️ Ввести заново",
                    callback_data="teacher:context:redo",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⌨️ Ручной ввод (без ИИ)",
                    callback_data="teacher:context:manual",
                ),
            ],
        ]
    )



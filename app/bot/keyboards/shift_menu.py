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
    shift_name_map: dict[int, str] | None = None,
) -> InlineKeyboardMarkup:
    """
    Список департаментов педагога.

    Если передан ``shift_name_map`` (педагог работает в нескольких сменах),
    в подписи кнопки указывается смена: «📂 Смена 1 2026 — Департамент
    управления». Если ``shift_name_map`` == None (все департаменты в одной
    смене), показываем только название департамента без префикса смены.
    """
    builder = InlineKeyboardBuilder()
    for d in departments:
        if shift_name_map is not None:
            shift_name = shift_name_map.get(d.shift_id, f"Смена {d.shift_id}")
            text = f"{d.emoji} {shift_name} — {d.name}"
        else:
            text = f"{d.emoji} {d.name}"
        builder.button(
            text=text,
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
            [
                InlineKeyboardButton(
                    text="🗑 Удалить контекст смены",
                    callback_data="teacher:context:delete",
                ),
            ],
        ]
    )



def edit_context_keyboard(has_context: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура экрана изменения контекста смены.

    Кнопка удаления контекста живёт ИМЕННО здесь (внутри «Изменить контекст»),
    а не в списке детей. Показываем её только если контекст вообще есть.
    """
    rows: list[list[InlineKeyboardButton]] = []
    if has_context:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Удалить контекст смены",
                    callback_data="teacher:context:delete",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад к списку детей",
                callback_data="teacher:child_list",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_context_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение удаления контекста смены."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Да, удалить",
                    callback_data="teacher:context:delete:confirm",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Отмена",
                    callback_data="teacher:child_list",
                ),
            ],
        ]
    )


def context_input_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Назад» для экранов ввода/правки контекста смены.

    Ведёт строго назад — к списку детей департамента (именно оттуда открывается
    работа с контекстом кнопкой «✏️ Изменить контекст смены»). Нужна, чтобы
    педагог мог отказаться от ввода контекста и не «застрять» в состоянии
    ожидания текста/голоса без единой кнопки на экране.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="← Назад к списку детей",
                    callback_data="teacher:child_list",
                )
            ]
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

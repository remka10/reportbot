from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Student


def children_keyboard(
    students: list[Student],
    progress_map: dict[int, int],   # student_id -> кол-во отвеченных вопросов
    finalized_ids: set[int],         # student_id финализированных отчётов
    total_questions: int = 19,
) -> InlineKeyboardMarkup:
    """
    Список детей с прогресс-индикатором.
    ✅ = отчёт финализирован
    ⏳ = есть ответы, но не финализирован
    ⬜ = не начат
    """
    builder = InlineKeyboardBuilder()
    for student in students:
        answered = progress_map.get(student.id, 0)
        if student.id in finalized_ids:
            icon = "✅"
        elif answered > 0:
            icon = "⏳"
        else:
            icon = "⬜"

        builder.button(
            text=f"{icon} {student.full_name}",
            callback_data=f"teacher:child:{student.id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def question_keyboard(
    current_num: int,
    total: int,
    has_prev: bool = True,
) -> InlineKeyboardMarkup:
    """Навигация по вопросам. Ответ принимается голосом или текстом
    прямо в чат (без отдельной кнопки)."""
    # Навигация
    nav_row = []
    if has_prev and current_num > 1:
        nav_row.append(
            InlineKeyboardButton(text="← Назад", callback_data=f"q:prev:{current_num - 1}")
        )
    nav_row.append(
        InlineKeyboardButton(text="📋 Список", callback_data="q:list")
    )
    if current_num < total:
        nav_row.append(
            InlineKeyboardButton(text="→ Вперёд", callback_data=f"q:next:{current_num + 1}")
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏭ Пропустить", callback_data="q:skip"),
            ],
            nav_row,
        ]
    )



def questions_list_keyboard(
    questions: list,
    answered_ids: set[int],
) -> InlineKeyboardMarkup:
    """Список всех вопросов с отметкой об ответе."""
    builder = InlineKeyboardBuilder()
    for q in questions:
        icon = "✅" if q.id in answered_ids else "⬜"
        short_text = q.question_text[:40].replace("\n", " ")
        builder.button(
            text=f"{icon} {q.question_number}. {short_text}...",
            callback_data=f"q:goto:{q.question_number}",
        )
    builder.button(text="← Назад", callback_data="q:back")
    builder.adjust(1)
    return builder.as_markup()


def generate_report_keyboard() -> InlineKeyboardMarkup:
    """Кнопка генерации отчёта + навигация."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Сгенерировать отчёт",
                    callback_data="teacher:generate",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Список вопросов",
                    callback_data="q:list",
                ),
                InlineKeyboardButton(
                    text="👦 К списку детей",
                    callback_data="teacher:child_list",
                ),
            ],
        ]
    )


def finalized_report_keyboard() -> InlineKeyboardMarkup:
    """Меню для уже финализированного отчёта: посмотреть / скачать / перегенерировать."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👀 Посмотреть отчёт",
                    callback_data="report:view",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📄 Скачать PPTX",
                    callback_data="export:single",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сгенерировать заново",
                    callback_data="teacher:generate",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👦 К списку детей",
                    callback_data="teacher:child_list",
                ),
            ],
        ]
    )


def report_review_keyboard() -> InlineKeyboardMarkup:
    """Кнопки после получения сгенерированного отчёта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Готово — сохранить",
                    callback_data="report:finalize",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Исправить текст",
                    callback_data="report:revise",
                ),
            ],
        ]
    )
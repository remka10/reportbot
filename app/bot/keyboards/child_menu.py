from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Student


# Кол-во детей на одной странице списка (постраничная навигация).
CHILDREN_PAGE_SIZE = 8


def paginate(total: int, page: int, page_size: int = CHILDREN_PAGE_SIZE) -> tuple[int, int, int]:
    """Возвращает (page, total_pages, start_index) с нормализацией номера страницы."""
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    return page, total_pages, page * page_size


def children_keyboard(
    students: list[Student],
    progress_map: dict[int, int],   # student_id -> кол-во отвеченных вопросов
    finalized_ids: set[int],         # student_id финализированных отчётов
    total_questions: int = 13,
    page: int = 0,
    page_size: int = CHILDREN_PAGE_SIZE,
    show_context_button: bool = True,
    show_back_to_departments: bool = False,
    back_to_departments_cb: str = "teacher:shifts",
) -> InlineKeyboardMarkup:

    """
    Список детей с прогресс-индикатором и ПОСТРАНИЧНОЙ навигацией.
    ✅ = отчёт финализирован
    ⏳ = есть ответы, но не финализирован
    ⬜ = не начат

    На кнопке ребёнка показывается счётчик заполненных вопросов «(N/13)»
    (для финализированных отчётов вместо счётчика — «готово»).

    При большом количестве детей показывается только срез (page_size детей на
    страницу) + строка навигации «⬅️ / N/M / ➡️».

    show_back_to_departments — показывать кнопку «Назад к департаментам».
    Показываем её только когда департаментов больше одного: если департамент
    единственный, возвращаться некуда (нажатие открыло бы тот же список детей и
    вызвало бы ошибку «message is not modified» / зависание спиннера).
    """
    builder = InlineKeyboardBuilder()

    page, total_pages, start = paginate(len(students), page, page_size)
    page_students = students[start:start + page_size]

    for student in page_students:
        answered = progress_map.get(student.id, 0)
        if student.id in finalized_ids:
            # Отчёт финализирован. Показываем «готово», но если при этом были
            # заполнены НЕ все вопросы — предупреждаем счётчиком «(готово, N/13)»,
            # чтобы педагог видел, что отчёт сохранён на неполной анкете.
            icon = "✅"
            if answered < total_questions:
                counter = f"готово ⚠️ {answered}/{total_questions}"
            else:
                counter = "готово"
        elif answered > 0:
            icon = "⏳"
            counter = f"{answered}/{total_questions}"
        else:
            icon = "⬜"
            counter = f"0/{total_questions}"

        builder.button(
            text=f"{icon} {student.full_name} ({counter})",
            callback_data=f"teacher:child:{student.id}",
        )

    builder.adjust(1)

    # Строка постраничной навигации (только если страниц больше одной).
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️", callback_data=f"teacher:child_page:{page - 1}"
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}", callback_data="teacher:child_page:noop"
            )
        )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️", callback_data=f"teacher:child_page:{page + 1}"
                )
            )
        builder.row(*nav_row)

    # Отдельная кнопка изменения контекста смены (по требованию — отдельно).
    # Удаление контекста вынесено ВНУТРЬ экрана изменения контекста (с
    # подтверждением), поэтому отдельной кнопки удаления здесь больше нет.
    if show_context_button:
        builder.row(
            InlineKeyboardButton(
                text="✏️ Изменить контекст смены",
                callback_data="teacher:context:edit",
            )
        )

    # Кнопка возврата к выбору департамента — только если департаментов больше
    # одного (иначе возвращаться некуда, и кнопка бы зависала).
    if show_back_to_departments:
        builder.row(
            InlineKeyboardButton(
                text="← Назад к департаментам",
                callback_data=back_to_departments_cb,
            )
        )


    return builder.as_markup()



def question_keyboard(
    current_num: int,
    total: int,
    has_prev: bool = True,
) -> InlineKeyboardMarkup:
    """Навигация по вопросам. Ответ принимается голосом или текстом
    прямо в чат (без отдельной кнопки)."""
    # Навигация между вопросами
    nav_row = []
    if has_prev and current_num > 1:
        nav_row.append(
            InlineKeyboardButton(text="← Пред. вопрос", callback_data=f"q:prev:{current_num - 1}")
        )
    nav_row.append(
        InlineKeyboardButton(text="📋 Список", callback_data="q:list")
    )
    if current_num < total:
        nav_row.append(
            InlineKeyboardButton(text="→ След. вопрос", callback_data=f"q:next:{current_num + 1}")
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏭ Пропустить", callback_data="q:skip"),
            ],
            nav_row,
            [
                InlineKeyboardButton(
                    text="✅ Завершить и сформировать отчёт",
                    callback_data="teacher:generate_check",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="← Назад к списку детей",
                    callback_data="teacher:child_list",
                ),
            ],
        ]
    )


def confirm_generate_keyboard(answered: int, total: int) -> InlineKeyboardMarkup:
    """Подтверждение генерации отчёта, когда заполнены не все вопросы."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Да, сгенерировать",
                    callback_data="teacher:generate",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Продолжить заполнение",
                    callback_data="q:back",
                ),
            ],
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
    builder.button(text="← Назад к вопросу", callback_data="q:back")
    builder.button(text="👦 К списку детей", callback_data="teacher:child_list")
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
    """Меню для уже финализированного отчёта: посмотреть / скачать / исправить."""
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
                    text="📄 Скачать Word",
                    callback_data="export:single",
                ),

                InlineKeyboardButton(
                    text="📕 Скачать PDF",
                    callback_data="export:single_pdf",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать вручную",
                    callback_data="report:manual_edit",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🤖 Редактировать с помощью ИИ",
                    callback_data="report:ai_edit",
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
                    text="📝 Вернуться к заполнению анкеты",
                    callback_data="report:reopen",
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


def confirm_reopen_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение возврата к анкете финализированного отчёта.

    Предупреждаем, что при повторной генерации текущий сохранённый отчёт будет
    заменён (старый текст удалён). «Подтвердить» → report:reopen_confirm,
    «Назад» → report:back (вернуться к меню отчёта без изменений).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data="report:reopen_confirm",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="← Назад",
                    callback_data="report:back",
                ),
            ],
        ]
    )


def back_to_report_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата к меню отчёта из экранов просмотра/правки.

    Ведёт на report:back — обработчик восстанавливает меню текущего отчёта
    (финализированный/черновик) для выбранного ребёнка, а если отчёта нет —
    возвращает к списку детей. Кнопка списка детей продублирована как надёжный
    фолбэк на случай, если сессия по отчёту потерялась.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="← Назад к меню отчёта",
                    callback_data="report:back",
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
                    text="🤖 Исправить текст с помощью ИИ",
                    callback_data="report:ai_edit",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⌨️ Редактировать вручную",
                    callback_data="report:manual_edit",
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

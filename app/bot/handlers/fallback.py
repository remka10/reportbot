"""Глобальный fallback-роутер: ловит необработанные апдейты.

Этот роутер регистрируется ПОСЛЕДНИМ, чтобы перехватывать любые апдейты
(особенно callback_query), которые не обработал ни один предыдущий хендлер.

Цель: снять «часики» на кнопке (answer() у callback) и записать в лог, что
именно не обработалось. Без этого пользователь видит зависшую кнопку и
непонятно, сработало ли нажатие.
"""

import logging
from aiogram import Router
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)
router = Router(name="fallback")


@router.callback_query()
async def fallback_callback(cb: CallbackQuery) -> None:
    """Перехватывает необработанные callback_query.

    Если callback не поймал ни один хендлер выше (из-за несовпадения state,
    отсутствия нужного data и т.п.), этот хендлер снимет «часики» на кнопке
    и предупредит пользователя.
    """
    try:
        logger.warning(
            f"Unhandled callback_query: data={cb.data!r}, "
            f"user_id={cb.from_user.id}, "
            f"message_id={cb.message.message_id if cb.message else None}"
        )
        await cb.answer(
            "⚠️ Эта кнопка сейчас недоступна. Попробуйте /start",
            show_alert=True,
        )
    except Exception as e:
        # Даже сам fallback не должен падать — иначе апдейт снова «не обработан».
        logger.error(f"fallback_callback failed: {e}", exc_info=True)



@router.message()
async def fallback_message(message: Message) -> None:
    """Перехватывает необработанные сообщения (текст/голос/фото и т.п.).

    Логируем факт необработки, но ничего не отвечаем — пользователь сам
    поймёт, что бот не отреагировал. Иначе лишний шум в чате.
    """
    try:
        logger.info(
            f"Unhandled message: type={message.content_type}, "
            f"user_id={message.from_user.id}, "
            f"text={message.text[:50] if message.text else None!r}"
        )
    except Exception as e:
        logger.error(f"fallback_message failed: {e}", exc_info=True)



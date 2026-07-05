from app.database.models import User


def telegram_username(user: User) -> str:
    """Telegram username с @ или Telegram-имя, если username недоступен."""
    if user.username:
        return f"@{user.username}"
    if user.full_name and user.full_name != f"@{user.id}":
        return user.full_name
    return "—"


def telegram_id(user: User) -> str:
    """Telegram ID в формате, который используют админы при вводе: @<id>."""
    return f"@{user.id}"


def user_button_label(user: User) -> str:
    """Короткая подпись пользователя для inline-кнопок."""
    primary = telegram_username(user)
    if primary == "—":
        primary = telegram_id(user)
    return f"{primary} ({user.role.value})"


def user_stats_label(user: User) -> str:
    """Единый формат отображения пользователя в списках/статистике."""
    return f"{telegram_username(user)} | ID: <code>{telegram_id(user)}</code>"


def user_greeting_name(user: User) -> str:
    """Имя в приветствии: приоритетно Telegram username, затем @id."""
    primary = telegram_username(user)
    return primary if primary != "—" else telegram_id(user)
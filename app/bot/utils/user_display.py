from app.database.models import User


def telegram_username(user: User) -> str:
    """Telegram username с @ или прочерк, если ник неизвестен."""
    return f"@{user.username}" if user.username else "—"


def telegram_id(user: User) -> str:
    """Telegram ID в формате, который используют админы при вводе: @<id>."""
    return f"@{user.id}"


def user_button_label(user: User) -> str:
    """Короткая подпись пользователя для inline-кнопок."""
    primary = f"@{user.username}" if user.username else telegram_id(user)
    return f"{primary} ({user.role.value})"


def user_stats_label(user: User) -> str:
    """Единый формат отображения пользователя в списках/статистике."""
    return f"{telegram_username(user)} | ID: <code>{telegram_id(user)}</code>"


def user_greeting_name(user: User) -> str:
    """Имя в приветствии: приоритетно Telegram username, затем @id."""
    return f"@{user.username}" if user.username else telegram_id(user)
# ReportBot

Telegram-бот для генерации педагогических отчётов в ролевом лагере.
Педагог отвечает на 19 вопросов голосом или текстом — бот генерирует
профессиональный отчёт через Gemini AI и экспортирует его в DOCX.

---

## Быстрый старт

### 1. Клонировать репозиторий

```bash
git clone https://github.com/yourorg/reportbot.git
cd reportbot
```

### 2. Настроить окружение

```bash
cp .env.example .env
```

Заполнить `.env`:

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather |
| `WEBHOOK_URL` | Публичный URL сервера (https) |
| `ADMIN_TELEGRAM_ID` | Telegram ID первого администратора |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@db:5432/reportbot` |
| `DB_USER` | Пользователь PostgreSQL |
| `DB_PASSWORD` | Пароль PostgreSQL |
| `GEMINI_API_KEY` | Ключ Google AI Studio |
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `OPENAI_API_KEY` | Ключ OpenAI (только для Whisper STT) |

### 3. Добавить шаблон отчёта

Поместить файл `report_template.docx` в директорию `app/templates/`.

Шаблон использует Jinja2-переменные (docxtpl):

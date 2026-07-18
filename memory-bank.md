# memory-bank.md — ReportBot (сжатая версия)

## 1. Проект

Telegram-бот для педагогов летнего лагеря. Роли: admin, moderator, teacher.

Флоу педагога: выбор департамента (в активной смене) → ввод контекста департамента (текст/голос, STT Whisper) → анкета по каждому ребёнку (текст/голос) → генерация отчёта LLM (Gemini) → правки в диалоге → финализация → экспорт DOCX/PPTX/PDF, пачкой в ZIP.

Админ: управление пользователями/сменами/учащимися + сами могут заполнять отчёты по любой смене/департаменту (`app/bot/handlers/admin/fill.py`, переиспользует пайплайн педагога через `open_department()`).

Данные (ответы, отчёты, контекст смены) — ОБЩИЕ между аккаунтами по ребёнку/департаменту, не привязаны к конкретному teacher_id (кроме аудит-поля «кто последний менял»).

## 2. Стек

FastAPI (только lifespan + `/health`, апдейты НЕ через FastAPI) · aiogram 3.7.0 **long-polling** (webhook не используется, исторически был нестабилен на 443) · SQLAlchemy 2.0 async · Alembic · PostgreSQL 15 · LLM: переключаемо Gemini 2.5 Flash / Claude Haiku 4.5 через AiTunnel (OpenAI-совместимый API, base_url `https://api.aitunnel.ru/v1`) · STT: Whisper (`whisper-1`) через AiTunnel · docxtpl / python-pptx/docx для документов · Docker Compose (bot/db/nginx/certbot) · nginx reverse proxy · Let's Encrypt SSL.


Python 3.11, весь код async/await.

## 3. Структура файлов

```
app/
├── main.py                 # FastAPI, lifespan, long-polling, /health
├── config.py                # pydantic-settings: settings / get_settings()
├── database/
│   ├── base.py               # Base, engine, AsyncSessionLocal
│   └── models.py             # ORM-модели + DEPARTMENTS справочник
├── repositories/             # доступ к БД, без бизнес-логики
│   ├── user_repo.py, shift_repo.py, department_repo.py
│   ├── student_repo.py, answer_repo.py, question_repo.py, report_repo.py
├── services/
│   ├── app_service.py         # агрегатор репозиториев
│   ├── llm_service.py         # generate_report/revise_report/clean_stt/beautify_shift_context/revise_shift_context
│   ├── stt_service.py         # transcribe_voice (Whisper)
│   ├── docx_service.py        # DocxService + PptxService, цвета департаментов
│   ├── zip_service.py         # упаковка отчётов в ZIP
│   └── user_service.py        # add/change_role/deactivate
├── templates/report_template.pptx (+docx при необходимости)
└── bot/
    ├── router.py              # register_all_routers(dp), порядок важен
    ├── middlewares/db_session.py, auth.py
    ├── states/admin_states.py, teacher_states.py
    ├── keyboards/main_menu.py, admin_menu.py, child_menu.py, shift_menu.py
    └── handlers/
        ├── start.py
        ├── admin/roles.py, shifts.py, students.py, fill.py
        └── teacher/shift.py, child.py, questions.py, generation.py, export.py
```
Прочее в корне: alembic/, nginx/, certbot/, scripts/prepare_pptx_template.py, check.py (проверка синтаксиса/импортов), docker-compose.yml, Dockerfile, requirements.txt, .env.

Имена файлов — с подчёркиваниями (`db_session.py`, `user_repo.py`).

## 4. Модель данных

Enum: UserRole(admin|moderator|teacher), DialogRole(assistant|user).

| Таблица | Ключевые поля |
|---|---|
| users | id (BigInteger=Telegram ID, PK), full_name, username, role, is_active |
| shifts | id, name, department_id(legacy,nullable), start_date, end_date, is_active |
| departments | id, shift_id(FK), department_number(1..9), UNIQUE(shift_id, department_number) |
| teacher_departments | PK(teacher_id, department_id), shift_context(Text) |
| teacher_shifts | LEGACY, не используется новым кодом |
| students | id, full_name, shift_id(FK), department_id(FK nullable), position |
| questions | id, block_number, block_title, question_number, question_text, is_active |
| answers | UNIQUE(teacher_id, student_id, question_id), answer_text, raw_audio_transcription. Чтения фильтруются по student_id БЕЗ teacher_id (общие данные) |
| reports | teacher_id, student_id, shift_id, generated_text, revision_count, is_finalized, docx_file_path. Общие по (student, shift) |
| revision_history | report_id(FK), role, content |

Департаменты (1..9), захардкожены в models.py DEPARTMENTS dict (name+hex), хелперы get_department_name/get_department_hex:
1 Департамент управления F9423A, 2 Департамент общественных связей FF672D, 3 Инженерный департамент EDC731, 4 Департамент Икс 242424, 5 Научный департамент 50C787, 6 IT-департамент 5A88FF, 7 Департамент дизайна C061F3, 8 Проект 11 91D744, 9 Летово Джун FB4724.
Цвета продублированы в docx_service.py.

## 5. Ключевая логика

- Смена → авто-создание 9 департаментов при создании смены (department_repo.create_for_shift, идемпотентно).
- Педагоги/учащиеся привязаны к департаменту, не к смене. Контекст смены — per-department (не per-teacher): department_repo.update_context() пишет во ВСЕ строки teacher_departments этого департамента; get_any_context() отдаёт любой непустой контекст для фолбэка на другом аккаунте.
- Админ как педагог: fill.py идемпотентно привязывает админа к департаменту (assign_teacher), затем переиспользует open_department() из teacher/shift.py.

## 6. Жизненный цикл апдейта

```
Telegram → dp.start_polling() (фон, main.py::_run_polling)
  → dp.feed_update
    → DbSessionMiddleware (session, commit/rollback)
      → AuthMiddleware (проверка доступа, data["user"])
        → Router → Handler(cb/msg, session, user, state)
          → Repository/Service → БД/LLM/STT
```
FastAPI не участвует в обработке апдейтов, только /health и lifespan. Webhook-эндпоинта в коде нет.

Middleware порядок КРИТИЧЕН: DbSessionMiddleware → AuthMiddleware.

**DbSessionMiddleware**: session на каждый апдейт; commit при успехе, rollback при исключении; ГЛУШИТ исключения (лог "=== HANDLER EXCEPTION ===" + traceback, возврат None) — поэтому в каждом хендлере обязателен свой try/except с сообщением пользователю.

**AuthMiddleware**: достаёт tg_user из любого типа апдейта; ищет по Telegram ID; если tg_id==admin_telegram_id и юзера нет — авто-создаёт админа; обновляет username при входе; если юзер не найден/is_active=False — "нет доступа", обрывает цепочку; кладёт data["user"].

## 7. Роутинг

register_all_routers(dp) порядок: start → admin(roles, shifts, students, fill) → teacher(shift, child, questions, generation, export). Специфичные (с FSM-фильтром) роутеры/хендлеры регистрируются раньше общих.

## 8. FSM состояния

teacher_states.py: ShiftSelectStates(choosing_shift, confirm_context, entering_context, preview_context, revising_context, manual_context), ChildSelectStates(choosing_child), QuestionStates(answering, waiting_voice), GenerationStates(generating, reviewing, waiting_revision, finalized).

admin_states.py: AddUserStates, ChangeRoleStates, DeactivateUserStates, CreateShiftStates, ArchiveShiftStates, AssignTeacherStates, AddStudentStates, EditStudentStates, DeleteStudentStates, ViewStudentsStates, AdminFillStates(waiting_shift_select, waiting_department_select).

Storage = MemoryStorage → FSM теряется при рестарте контейнера. Фикс краткосрочный: /start. Долгосрочный: RedisStorage.from_url + сервис redis в docker-compose.

## 9. Конвенции callback_data (через `:`)

admin:main / admin:users* / admin:shifts* / admin:students* / admin:fill — админ-меню.
fill_shift:<id> / fill_department:<id> — выбор в admin/fill.py.
assign_shift:<id> / select_department:<id> / assign_teacher:<id> / role:<value> / select_user:<id> — привязка педагога, роли.
teacher:shifts / teacher:department:<id> — список/выбор департамента.
teacher:context:use|change|accept|regenerate|redo|revise|manual — работа с контекстом смены.
teacher:child:<id> / teacher:child_list — выбор ребёнка.
q:next:<n> / q:prev:<n> / q:goto:<n> / q:skip / q:list / q:back — навигация вопросов.
teacher:generate / report:finalize / report:revise / teacher:next_child / teacher:export — генерация/экспорт.
export:menu / export:single / export:single_pdf / export:zip / export:zip_pdf — экспорт.
`<id>`/`<n>` — числовой аргумент последним сегментом (`int(cb.data.split(":")[-1])`).

## 10. Паттерн хендлера (эталон)

```python
@router.callback_query(SomeState.some_state, F.data == "action")
async def handler_name(cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession) -> None:
    try:
        repo = SomeRepository(session)
        ...
        await cb.message.edit_text("...", reply_markup=some_keyboard())
        await cb.answer()
    except Exception as e:
        logger.exception(f"Error in handler_name: {e}")
        await cb.answer("⚠️ Произошла ошибка. Попробуйте снова.", show_alert=True)
```
Правила: session/user/state — параметры хендлера, не глобальные. logger = logging.getLogger(__name__) в каждом файле. Commit/rollback — только в middleware, не вручную. БД — только через репозитории, SQL в хендлерах не писать. Репозитории получают session в __init__, не хранят состояние. При любой ошибке — всегда сообщение пользователю (не глотать).

Никогда: новые глобальные переменные в main.py; менять порядок middleware; синхронный код в хендлерах.

## 11. Сервисы (детали)

LLMService: AsyncOpenAI c base_url AiTunnel. Модель выбирается динамически через `app/services/model_settings.py` (get_model): область "generation" → generate_report/revise_report, область "context" → beautify_shift_context/revise_shift_context. clean_stt_transcription (правки расшифровок Whisper) ВСЕГДА на settings.gemini_model, не переключается. generate_report(qa_pairs, shift_context, student_name), revise_report(revision_request, history), clean_stt, beautify_shift_context(raw_context) (оформляет контекст в стиле "Летово Игра"), revise_shift_context(previous_context, comment).

**model_settings.py**: лёгкое персистентное хранилище выбора LLM (без alembic-миграции). Кэш в модуле + дублирование в JSON `REPORTS_DIR/model_settings.json` (переживает рестарт). Опции: "gemini" (Gemini 2.5 Flash) / "haiku" (Claude Haiku 4.5). Две области: generation, context (дефолт обеих — gemini). API: get_choice(kind), get_model(kind), set_choice(kind, choice), snapshot(). Реальные id моделей берутся из settings (gemini_model / haiku_model). Переключение — из веб-панели /admin (раздел «Нейросети», GET/PATCH `/admin/api/models`).


STTService: AiTunnel, модель settings.whisper_model. transcribe_voice(voice, bot). Лимит settings.max_audio_size_mb=20 → ValueError при превышении.

DocxService/PptxService: шаблоны в app/templates/ (report_template.docx/pptx), путь Path(__file__).parent.parent/"templates". DEPARTMENT_COLORS локально + транслитерация имён файлов. PptxService.generate_pdf()/_to_pdf() через headless LibreOffice (soffice --convert-to pdf; в Dockerfile нужны libreoffice-impress libreoffice-core fonts-dejavu fonts-liberation).

ZipService: пакует отчёты в ZIP, create_zip(as_pdf=bool).

## 12. Конфигурация (app/config.py)

pydantic-settings, читает .env. Доступ: `from app.config import settings` или `get_settings()` (lru_cache). Поля: telegram_bot_token, webhook_url (не используется, historical), admin_telegram_id, database_url, aitunnel_api_key, aitunnel_base_url, gemini_model, haiku_model (Claude Haiku 4.5, id через .env HAIKU_MODEL), whisper_model, debug, log_level, max_audio_size_mb, reports_dir (default /app/reports), admin_panel_username, admin_panel_password.


## 13. Работа с БД

Все запросы только через app/repositories/. Не писать SQL в хендлерах. Новые методы репозитория — через select()/update() SQLAlchemy. Commit/rollback — автоматически в DbSessionMiddleware.

## 14. FSM правила

При добавлении нового состояния — добавить в teacher_states.py/admin_states.py. Хендлер с FSM-фильтром регистрировать ДО общих хендлеров в router.py. /start и /cancel — во всех состояниях через Command фильтр.

## 15. AiTunnel API

Base URL `https://api.aitunnel.ru/v1` (OpenAI-совместимый). LLM: переключаемо gemini-2.5-flash / claude-haiku-4.5 (см. model_settings). STT: whisper-1. Таймаут httpx: 120с LLM, 60с STT. При ошибке — всегда уведомлять пользователя, не зависать.


## 16. Что не трогать

certbot/ (SSL) — никогда. alembic/versions/ — только новые миграции через `alembic revision`. nginx/conf.d/reportbot.conf — только с пониманием конфига. .env — не коммитить, не логировать значения.

## 17. Инфраструктура

Домен: teachergen.ru (бот @teachergenbot). Health: `GET https://teachergen.ru/health` → `{"status":"ok","bot":"..."}`. Сервер: root@185.207.64.66, проект в /home/reportbot. Контейнеры: bot(uvicorn:8000), db(postgres:15), nginx(80/443), certbot.

### docker-compose.yml (сервисы)
bot: build ., env_file .env, command `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`, depends_on db(healthy), extra_hosts api.telegram.org→149.154.167.220 (обход блокировок), dns 8.8.8.8/8.8.4.4, volumes .:/app + reportsdata:/app/reports.
db: postgres:15-alpine, POSTGRES_DB=reportbot, healthcheck pg_isready.
nginx: nginx:alpine, порты 80/443, конфиги ./nginx/conf.d, certbot conf/www.
certbot: certbot/certbot.

### .env (переменные)
```
TELEGRAM_BOT_TOKEN=
WEBHOOK_URL=https://teachergen.ru   # без trailing slash, не используется (polling)
ADMIN_TELEGRAM_ID=
DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@db:5432/reportbot
DB_USER=
DB_PASSWORD=
AITUNNEL_API_KEY=sk-aitunnel-...
AITUNNEL_BASE_URL=https://api.aitunnel.ru/v1
GEMINI_MODEL=gemini-2.5-flash
HAIKU_MODEL=claude-haiku-4.5
WHISPER_MODEL=whisper-1

DEBUG=false
LOG_LEVEL=INFO
MAX_AUDIO_SIZE_MB=20
REPORTS_DIR=app/reports
```

### nginx (nginx/conf.d/reportbot.conf)
80 → редирект на 443 (+ /.well-known/acme-challenge/ для certbot). 443 ssl: server_name teachergen.ru www.teachergen.ru, ssl_certificate из letsencrypt live/teachergen.ru, client_max_body_size 25M, proxy_pass http://bot:8000, proxy_read_timeout 120s, proxy_connect_timeout 10s.

### Dockerfile
`mirror.gcr.io/library/python:3.11-slim`, apt gcc libpq-dev, pip install -r requirements.txt, CMD uvicorn app.main:app --host 0.0.0.0 --port 8000.

### SSL/Certbot
Сертификат teachergen.ru через Let's Encrypt, путь ./certbot/conf/live/teachergen.ru/, продление `docker compose run --rm certbot renew`, срок 90 дней (создан 2026-06-24, истекает 2026-09-22).

### SSH
`ssh root@185.207.64.66` (или VS Code Remote SSH, Host teachergen.ru, User root/deploy-user). В системе настроен алиас `login` для этого SSH-подключения.

### Диагностические команды (ручной запуск при отладке)
```bash
docker compose ps
docker compose logs bot --tail=200 | grep -E "ERROR|EXCEPTION|Traceback"
docker compose logs bot --tail=50 | grep -i "polling|Run polling"   # норма: "Run polling for bot @teachergenbot"
curl https://teachergen.ru/health
curl "https://api.telegram.org/bot{TOKEN}/getWebhookInfo" | python3 -m json.tool   # url, last_error_message, last_error_date, pending_update_count
docker compose exec bot python check.py       # синтаксис/импорты
docker compose exec db psql -U ${DB_USER} -d reportbot -c "SELECT id, full_name, role, is_active FROM users;"
docker compose exec bot curl -s "https://api.aitunnel.ru/v1/models" -H "Authorization: Bearer ${AITUNNEL_API_KEY}"
docker compose exec bot ls -la /app/app/templates/
```
FSM зависла у пользователя → /start сбрасывает.

Ручной деплой (шаги делает сам пользователь, не агент):
```
git add . ; git commit -m "..." ; git push
# на сервере:
git pull ; docker compose down bot ; docker compose up bot -d --build
docker compose exec bot alembic upgrade head   # если были миграции
```

## 18. Прочее

Memory-bank для контекста задач: держать этот единственный файл вместо отдельных projectContext/systemPatterns/rules/serverConfig/knownBugs/activeTask — избегает дублирования и экономит токены.

Важно, все команды с питоном выполняются не через python а через py

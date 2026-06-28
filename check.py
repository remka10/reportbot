import sys, ast, os
print("=" * 50)
print("SYNTAX CHECK")
print("=" * 50)
errors = 0
for root, dirs, files in os.walk('/app'):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
    for fname in files:
        if not fname.endswith('.py'):
            continue
        path = os.path.join(root, fname)
        try:
            ast.parse(open(path).read())
        except SyntaxError as e:
            print(f"  SYNTAX  {path}:{e.lineno} — {e.msg}")
            errors += 1
if errors == 0:
    print("  OK — no syntax errors")
print()
print("=" * 50)
print("IMPORT CHECK")
print("=" * 50)
sys.path.insert(0, '/app')
modules = [
    'app.config','app.database.base','app.database.models',
    'app.bot.states.admin_states','app.bot.states.teacher_states',
    'app.repositories.user_repo','app.repositories.shift_repo',
    'app.repositories.student_repo','app.repositories.answer_repo',
    'app.repositories.question_repo','app.repositories.report_repo',
    'app.services.llm_service','app.services.stt_service',
    'app.services.docx_service','app.services.zip_service',
    'app.services.app_service','app.services.user_service',
    'app.bot.middlewares.auth','app.bot.middlewares.db_session',
    'app.bot.keyboards.main_menu','app.bot.keyboards.admin_menu',
    'app.bot.keyboards.child_menu','app.bot.keyboards.shift_menu',
    'app.bot.handlers.start','app.bot.handlers.admin.roles',
    'app.bot.handlers.admin.shifts','app.bot.handlers.admin.students',
    'app.bot.handlers.teacher.child','app.bot.handlers.teacher.export',
    'app.bot.handlers.teacher.generation','app.bot.handlers.teacher.questions',
    'app.bot.handlers.teacher.shift','app.bot.router','app.main',
]
ok = fail = 0
for m in modules:
    try:
        __import__(m)
        print(f"  OK    {m}")
        ok += 1
    except Exception as e:
        print(f"  FAIL  {m}")
        print(f"        {type(e).__name__}: {e}")
        fail += 1
print()
print(f"Result: {ok} OK / {fail} FAILED out of {len(modules)} modules")

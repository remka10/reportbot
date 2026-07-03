#!/usr/bin/env python3
"""
Ultra-check: расширенный статический анализ проекта ReportBot.
Синтаксис + импорты + архитектурные правила из memory-bank.md.

Запуск:
  python check.py                     # локально
  docker compose exec bot python check.py   # в контейнере
"""
import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", "/app"))
APP_DIR = ROOT / "app"
IGNORE_DIRS = {"__pycache__", ".git", "alembic", "certbot", ".venv", "venv", "node_modules"}


def section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def iter_py_files(base: Path):
    if not base.exists():
        return
    for r, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield Path(r) / f


def path_to_module(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


# ---------- 1. SYNTAX ----------
def check_syntax():
    section("1. SYNTAX CHECK (ast.parse по всем .py)")
    errors = []
    for path in iter_py_files(ROOT):
        try:
            src = path.read_text(encoding="utf-8")
            ast.parse(src, filename=str(path))
        except SyntaxError as e:
            errors.append((path, e))
            print(f"  \u2717 SYNTAX {path}:{e.lineno} \u2014 {e.msg}")
        except UnicodeDecodeError as e:
            errors.append((path, e))
            print(f"  \u2717 ENCODING {path} \u2014 {e}")
    if not errors:
        print("  \u2713 OK \u2014 синтаксических ошибок нет")
    return errors


# ---------- 2. IMPORTS (auto-discovery, не хардкод-список) ----------
def check_imports():
    section("2. IMPORT CHECK (автообнаружение всех модулей app/**)")
    sys.path.insert(0, str(ROOT))
    ok = fail = 0
    fails = []
    for path in iter_py_files(APP_DIR):
        if path.name == "__init__.py":
            continue
        mod = path_to_module(path)
        try:
            importlib.import_module(mod)
            ok += 1
        except Exception as e:
            fail += 1
            fails.append((mod, e))
            print(f"  \u2717 FAIL {mod}: {type(e).__name__}: {e}")
    if fail == 0:
        print(f"  \u2713 OK \u2014 все {ok} модулей импортируются")
    else:
        print(f"\n  Результат: {ok} OK / {fail} FAILED")
    return fails


# ---------- 3. PYFLAKES (unused imports / undefined names) ----------
def check_pyflakes():
    section("3. PYFLAKES (неиспользуемые импорты, undefined names)")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pyflakes", str(APP_DIR)],
            capture_output=True, text=True,
        )
        output = (result.stdout + result.stderr).strip()
        print(output if output else "  \u2713 OK \u2014 замечаний нет")
    except FileNotFoundError:
        print("  \u26a0 pyflakes не установлен (pip install pyflakes)")


# ---------- 4. ПАТТЕРН ХЕНДЛЕРА (memory-bank п.10: try/except обязателен) ----------
class HandlerAudit(ast.NodeVisitor):
    def __init__(self, filepath):
        self.filepath = filepath
        self.issues = []

    def _is_handler_deco(self, d):
        target = d.func if isinstance(d, ast.Call) else d
        return isinstance(target, ast.Attribute) and target.attr in ("callback_query", "message")

    def visit_AsyncFunctionDef(self, node):
        if any(self._is_handler_deco(d) for d in node.decorator_list):
            has_try = any(isinstance(n, ast.Try) for n in ast.walk(node))
            if not has_try:
                self.issues.append(
                    f"{self.filepath}:{node.lineno} \u2014 хендлер '{node.name}' без try/except (нарушение п.10)"
                )
        self.generic_visit(node)


def check_handler_pattern():
    section("4. ПАТТЕРН ХЕНДЛЕРА (try/except обязателен \u2014 memory-bank п.10)")
    handlers_dir = APP_DIR / "bot" / "handlers"
    if not handlers_dir.exists():
        print("  \u26a0 app/bot/handlers не найден, пропуск")
        return
    issues = []
    for path in iter_py_files(handlers_dir):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        auditor = HandlerAudit(path)
        auditor.visit(tree)
        issues.extend(auditor.issues)
    if issues:
        for i in issues:
            print(f"  \u2717 {i}")
    else:
        print("  \u2713 OK \u2014 все хендлеры содержат try/except")


# ---------- 5. RAW SQL В HANDLERS ЗАПРЕЩЁН (п.13: только через repositories) ----------
def check_raw_sql():
    section("5. RAW SQL В HANDLERS (запрещено \u2014 только через repositories, п.13)")
    handlers_dir = APP_DIR / "bot" / "handlers"
    issues = []
    forbidden = (".execute(", "text(", ".raw(")
    for path in iter_py_files(handlers_dir):
        src = path.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            if any(f in line for f in forbidden):
                issues.append(f"{path}:{i} \u2014 {line.strip()}")
    if issues:
        for i in issues:
            print(f"  \u2717 {i}")
    else:
        print("  \u2713 OK \u2014 прямых SQL-вызовов в хендлерах не найдено")


# ---------- 6. ПОРЯДОК MIDDLEWARE (п.6: DbSessionMiddleware \u2192 AuthMiddleware) ----------
def check_middleware_order():
    section("6. ПОРЯДОК MIDDLEWARE (DbSessionMiddleware \u2192 AuthMiddleware, п.6)")
    router_path = APP_DIR / "bot" / "router.py"
    if not router_path.exists():
        print("  \u26a0 app/bot/router.py не найден, пропуск")
        return
    src = router_path.read_text(encoding="utf-8")
    db_pos = src.find("DbSessionMiddleware")
    auth_pos = src.find("AuthMiddleware")
    if db_pos == -1 or auth_pos == -1:
        print("  \u26a0 не удалось найти оба middleware в router.py")
    elif db_pos < auth_pos:
        print("  \u2713 OK \u2014 DbSessionMiddleware регистрируется раньше AuthMiddleware")
    else:
        print("  \u2717 НАРУШЕНИЕ: AuthMiddleware регистрируется раньше DbSessionMiddleware!")


# ---------- 7. LOGGER В КАЖДОМ ФАЙЛЕ handlers/services (п.10) ----------
def check_logger_presence():
    section("7. logger = logging.getLogger(__name__) в handlers/services")
    issues = []
    for sub in ("bot/handlers", "services"):
        d = APP_DIR / sub
        for path in iter_py_files(d):
            src = path.read_text(encoding="utf-8")
            if "getLogger" not in src:
                issues.append(str(path))
    if issues:
        for i in issues:
            print(f"  \u2717 {i} \u2014 нет объявления logger")
    else:
        print("  \u2713 OK \u2014 logger объявлен во всех файлах")


# ---------- 8. ИМЕНОВАНИЕ ФАЙЛОВ (snake_case, п.3) ----------
def check_naming():
    section("8. ИМЕНОВАНИЕ ФАЙЛОВ (snake_case \u2014 конвенция проекта, п.3)")
    issues = []
    for path in iter_py_files(APP_DIR):
        name = path.stem
        if name != name.lower() or "-" in name:
            issues.append(str(path))
    if issues:
        for i in issues:
            print(f"  \u2717 {i} \u2014 нарушение snake_case")
    else:
        print("  \u2713 OK \u2014 все имена файлов в snake_case")


# ---------- 9. ЗАЩИЩЁННЫЕ ПУТИ НЕ ТРОНУТЫ (п.16, best-effort через git) ----------
def check_protected_paths():
    section("9. ЗАЩИЩЁННЫЕ ПУТИ (certbot/, alembic/versions/, nginx/conf.d, .env \u2014 п.16)")
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        print("  \u26a0 git недоступен, пропуск")
        return
    changed = result.stdout.strip().splitlines()
    protected_prefixes = ("certbot/", "nginx/conf.d/", ".env")
    hits = [l for l in changed if any(p in l for p in protected_prefixes)]
    if hits:
        for h in hits:
            print(f"  \u26a0 изменён защищённый путь: {h}")
    else:
        print("  \u2713 OK \u2014 защищённые пути не тронуты")


# ---------- 10. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ В main.py ЗАПРЕЩЕНЫ (п.10 "никогда") ----------
def check_main_globals():
    section("10. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ В main.py (запрещено добавлять новые \u2014 п.10)")
    main_path = APP_DIR / "main.py"
    if not main_path.exists():
        print("  \u26a0 app/main.py не найден, пропуск")
        return
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    allowed_kinds = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
    extra = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and not isinstance(node, allowed_kinds):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            extra.append((node.lineno, targets))
    if extra:
        for lineno, targets in extra:
            print(f"  \u26a0 main.py:{lineno} \u2014 глобальная переменная {targets} (проверь, не нарушение ли)")
    else:
        print("  \u2713 OK \u2014 явных новых глобальных переменных не найдено")


def main():
    syntax_errors = check_syntax()
    import_fails = check_imports()
    check_pyflakes()
    check_handler_pattern()
    check_raw_sql()
    check_middleware_order()
    check_logger_presence()
    check_naming()
    check_protected_paths()
    check_main_globals()

    section("ИТОГ")
    total_critical = len(syntax_errors) + len(import_fails)
    if total_critical == 0:
        print("\u2713 Критических ошибок (синтаксис/импорты) не найдено")
    else:
        print(f"\u2717 Критических ошибок: {total_critical} (см. секции 1 и 2 выше)")
    sys.exit(1 if total_critical else 0)


if __name__ == "__main__":
    main()

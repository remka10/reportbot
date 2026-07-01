"""Быстрый смоук-тест сборки PPTX без БД: мокаем report/student/shift/teacher."""
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.pptx_service import PptxService  # noqa: E402

report = SimpleNamespace(
    generated_text=(
        "1. Конструктор-одиночка, тянет департамент за собой.\n"
        "2. Спокойный, но за спокойствием — стальной стержень.\n"
        "3. Пришёл со слабой командной коммуникацией — научился слышать других.\n"
        "4. Инсайт на сборке прототипа: понял, зачем делегировать.\n"
        "5. Его модуль спас финальную миссию департамента.\n"
        "6. Развивал чужие идеи, редко спорил ради спора.\n"
        "7. В кризисе включал режим «решателя», не паниковал.\n"
        "8. Брал ответственность без просьбы; за ним шли.\n"
        "9. Клубы — чтобы прокачать скилл под миссию.\n"
        "10. Копил валюту до последнего дня — стратег.\n"
        "11. Умел переключаться, не выгорал.\n"
        "12. Верил в легенду, искал пасхалки в лаборатории.\n"
        "13. Неожиданная эмпатия к младшим участникам.\n"
        "=== ИТОГОВЫЙ ОТЧЁТ ===\n"
        "За смену ребёнок раскрылся как вдумчивый конструктор с внутренним "
        "стержнем: он превратил слабую сторону — командную коммуникацию — в "
        "опору, научившись слышать других и делегировать. В кризисные моменты "
        "оставался «решателем», а не паникёром, и естественно брал на себя "
        "ответственность, за которой тянулась команда. Игровой мир Корпорации "
        "стал для него полем настоящих открытий, а неожиданная эмпатия к "
        "младшим показала глубину, которую не разглядеть в первый день."
    ),
    revision_count=0,
)
student = SimpleNamespace(full_name="Иванов Иван")
shift = SimpleNamespace(name="Смена 3 · IT", department_id=6,
                        start_date=None, end_date=None, dates="10.06 – 20.06.2026")
teacher = SimpleNamespace(full_name="Петрова Мария")

svc = PptxService()
path = svc.generate(report=report, student=student, shift=shift, teacher=teacher,
                    shift_context="Департамент строил цифровую крепость Корпорации.")
print("OK:", path)
import zipfile
from pptx import Presentation as _P
_p = _P(str(path))
print("page(in):", round(_p.slide_width / 914400, 2), "x",
      round(_p.slide_height / 914400, 2))
with zipfile.ZipFile(path) as z:
    names = z.namelist()
print("slides:", sum(1 for n in names if n.startswith("ppt/slides/slide")))
print("fonts embedded:", any(n.startswith("ppt/fonts/") for n in names))



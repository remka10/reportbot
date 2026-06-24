import logging
import re
from datetime import date
from pathlib import Path

from docxtpl import DocxTemplate

from app.config import settings
from app.database.models import Report, Student, Shift, User

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(settings.reports_dir).parent / "app" / "templates" / "report_template.docx"


def _transliterate(text: str) -> str:
    """
    Транслитерация кириллицы для имён файлов.
    Иванов Иван -> Ivanov_Ivan
    """
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d",
        "е": "e", "ё": "yo", "ж": "zh", "з": "z", "и": "i",
        "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
        "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
        "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
        "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
    }
    result = []
    for ch in text.lower():
        result.append(table.get(ch, ch))
    clean = "".join(result)
    # Заменяем всё кроме букв/цифр на подчёркивание
    clean = re.sub(r"[^a-z0-9]+", "_", clean)
    return clean.strip("_")


def _safe_filename(student_name: str) -> str:
    """report_Ivanov_Ivan.docx"""
    return f"report_{_transliterate(student_name)}.docx"


def _safe_archive_name(shift_name: str) -> str:
    """reports_Smena1_IT_2026.zip"""
    return f"reports_{_transliterate(shift_name)}_{date.today().strftime('%Y%m%d')}.zip"


def _parse_blocks(report_text: str) -> list[dict]:
    """
    Парсит текст отчёта на блоки для структурированного вывода в шаблоне.
    Ожидаемый формат: строки начинающиеся с "Блок N." или "=== Блок N."
    """
    blocks = []
    current_title = ""
    current_lines: list[str] = []

    for line in report_text.splitlines():
        # Детектируем заголовок блока
        if re.match(r"^(===\s*)?Блок\s+\d+", line, re.IGNORECASE):
            if current_lines:
                blocks.append({
                    "block_title": current_title,
                    "content": "\n".join(current_lines).strip(),
                })
                current_lines = []
            current_title = line.strip("= ").strip()
        else:
            current_lines.append(line)

    # Последний блок
    if current_lines:
        blocks.append({
            "block_title": current_title or "Отчёт",
            "content": "\n".join(current_lines).strip(),
        })

    return blocks if blocks else [{"block_title": "Отчёт", "content": report_text}]


class DocxService:

    def __init__(self) -> None:
        self._reports_dir = Path(settings.reports_dir)
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def _get_template(self) -> DocxTemplate:
        if not TEMPLATE_PATH.exists():
            raise FileNotFoundError(
                f"Шаблон отчёта не найден: {TEMPLATE_PATH}\n"
                "Поместите файл report_template.docx в app/templates/"
            )
        return DocxTemplate(str(TEMPLATE_PATH))

    def generate(
        self,
        report: Report,
        student: Student,
        shift: Shift,
        teacher: User,
    ) -> Path:
        """
        Генерирует DOCX по шаблону docxtpl.

        Args:
            report: финализированный Report с generated_text
            student: Student объект
            shift: Shift объект
            teacher: User (педагог)

        Returns:
            Path к сгенерированному файлу
        """
        tpl = self._get_template()

        blocks = _parse_blocks(report.generated_text)

        context = {
            "student_name": student.full_name,
            "shift_name": shift.name,
            "department_name": shift.department_name,
            "teacher_name": teacher.full_name,
            "report_date": date.today().strftime("%d.%m.%Y"),
            "report_text": report.generated_text,
            "blocks": blocks,
            "revision_count": report.revision_count,
        }

        tpl.render(context)

        output_path = self._reports_dir / _safe_filename(student.full_name)
        tpl.save(str(output_path))

        logger.info(f"DOCX generated: {output_path} for student={student.full_name}")
        return output_path
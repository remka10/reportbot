import logging
import re
from datetime import date
from pathlib import Path
from typing import Union

from docxtpl import DocxTemplate
from pptx import Presentation
from pptx.util import Pt
from pptx.dml.color import RGBColor

from app.config import settings
from app.database.models import Report, Student, Shift, User

logger = logging.getLogger(__name__)

# ─── Пути к шаблонам ──────────────────────────────────────────────────────────
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
DOCX_TEMPLATE_PATH = TEMPLATE_DIR / "report_template.docx"
PPTX_TEMPLATE_PATH = TEMPLATE_DIR / "report_template.pptx"

# ─── Цвета департаментов (hex без #) ──────────────────────────────────────────
DEPARTMENT_COLORS: dict[int, str] = {
    1: "C0392B",  # Департамент управления        — насыщенный красный
    2: "2980B9",  # Департамент общественных связей — синий
    3: "27AE60",  # Инженерный департамент          — зелёный
    4: "8E44AD",  # Департамент Икс                 — фиолетовый
    5: "D35400",  # Научный департамент             — оранжевый
    6: "16A085",  # IT-департамент                  — бирюзовый
    7: "F39C12",  # Департамент дизайна             — янтарный
    8: "7F8C8D",  # Проект 11                       — серый
    9: "1ABC9C",  # Летово Джун                     — мятный
}

DEPARTMENT_NAMES: dict[int, str] = {
    1: "Департамент управления",
    2: "Департамент общественных связей",
    3: "Инженерный департамент",
    4: "Департамент Икс",
    5: "Научный департамент",
    6: "IT-департамент",
    7: "Департамент дизайна",
    8: "Проект 11",
    9: "Летово Джун",
}

DEFAULT_COLOR = "E84130"  # fallback — фирменный красный «Летово»


def get_department_color(department_id: int) -> str:
    """Возвращает HEX-цвет (без #) для департамента."""
    return DEPARTMENT_COLORS.get(department_id, DEFAULT_COLOR)


def get_department_name(department_id: int) -> str:
    """Возвращает название департамента по ID."""
    return DEPARTMENT_NAMES.get(department_id, f"Департамент {department_id}")


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def transliterate(text: str) -> str:
    table = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
        'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
        'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '',
        'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    result = []
    for ch in text.lower():
        result.append(table.get(ch, ch))
    clean = ''.join(result)
    clean = re.sub(r'[^a-z0-9_]', '_', clean)
    return clean.strip('_')


def safe_filename(student_name: str) -> Path:
    """report_IvanovIvan.docx"""
    return Path(f"report_{transliterate(student_name)}.docx")


def safe_pptx_filename(student_name: str) -> Path:
    """report_IvanovIvan.pptx"""
    return Path(f"report_{transliterate(student_name)}.pptx")


def safe_archive_name(shift_name: str) -> str:
    """reports_Smena1IT_20260621.zip"""
    return f"reports_{transliterate(shift_name)}_{date.today().strftime('%Y%m%d')}.zip"


def parse_blocks(report_text: str) -> list[dict]:
    """Парсит текст отчёта на блоки вида {block_title, content}."""
    blocks = []
    current_title = ""
    current_lines: list[str] = []

    for line in report_text.splitlines():
        stripped = line.strip()
        # Заголовок блока: «Блок N.» или «## ...»
        block_match = re.match(r'^(?:#{1,3}\s*|Блок\s+\d+[\.\:]\s*)(.*)', stripped)
        if block_match:
            if current_lines:
                blocks.append({
                    "block_title": current_title or "",
                    "content": "\n".join(current_lines).strip(),
                })
            current_title = block_match.group(1).strip()
            current_lines = []
        else:
            if stripped:
                current_lines.append(stripped)

    if current_lines:
        blocks.append({
            "block_title": current_title or "",
            "content": "\n".join(current_lines).strip(),
        })

    return blocks if blocks else [{"block_title": "", "content": report_text}]


# ─── Jinja2-контекст (общий для DOCX и PPTX) ──────────────────────────────────

def _build_context(report: Report, student: Student, shift: Shift, teacher: User) -> dict:
    dep_id = shift.department_id or 0
    return {
        # Основные поля
        "student_name":     student.full_name,
        "shift_name":       shift.name,
        "department_name":  get_department_name(dep_id),
        "department_id":    dep_id,
        "department_color": get_department_color(dep_id),   # HEX без #, напр. "C0392B"
        "teacher_name":     teacher.full_name,
        "report_date":      date.today().strftime("%d.%m.%Y"),
        "report_text":      report.generated_text,
        "revision_count":   report.revision_count,
        # Структурированные блоки для форматирования
        "blocks": parse_blocks(report.generated_text or ""),
    }


# ─── DOCX ─────────────────────────────────────────────────────────────────────

class DocxService:
    def __init__(self) -> None:
        self.reports_dir = Path(settings.reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _get_template(self) -> DocxTemplate:
        if not DOCX_TEMPLATE_PATH.exists():
            raise FileNotFoundError(
                f"DOCX-шаблон не найден: {DOCX_TEMPLATE_PATH}. "
                "Положите report_template.docx в app/templates/"
            )
        return DocxTemplate(str(DOCX_TEMPLATE_PATH))

    def generate(
        self,
        report: Report,
        student: Student,
        shift: Shift,
        teacher: User,
    ) -> Path:
        """Генерирует DOCX и возвращает Path к файлу."""
        tpl = self._get_template()
        context = _build_context(report, student, shift, teacher)
        tpl.render(context)
        output_path = self.reports_dir / safe_filename(student.full_name)
        tpl.save(str(output_path))
        logger.info(f"DOCX generated: {output_path} for student={student.full_name!r}")
        return output_path


# ─── PPTX ─────────────────────────────────────────────────────────────────────

# Имена плейсхолдеров в PPTX-шаблоне (текстовые фреймы ищутся по этим меткам)
PPTX_PLACEHOLDERS = {
    "{{student_name}}":     "student_name",
    "{{shift_name}}":       "shift_name",
    "{{department_name}}":  "department_name",
    "{{teacher_name}}":     "teacher_name",
    "{{report_date}}":      "report_date",
    "{{report_text}}":      "report_text",
}

# Фреймы с этим тегом получат цвет фона/текста департамента
PPTX_COLOR_TAG = "{{department_color}}"


def _hex_to_rgb(hex_color: str) -> RGBColor:
    """'C0392B' → RGBColor(192, 57, 43)"""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return RGBColor(r, g, b)


def _replace_text_in_shape(shape, replacements: dict[str, str]) -> None:
    """Заменяет плейсхолдеры в текстовом фрейме, сохраняя форматирование."""
    if not shape.has_text_frame:
        return
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            for placeholder, value in replacements.items():
                if placeholder in run.text:
                    run.text = run.text.replace(placeholder, value)


def _apply_department_color_to_shape(shape, rgb: RGBColor) -> None:
    """Перекрашивает текст внутри фрейма с тегом {{department_color}}."""
    if not shape.has_text_frame:
        return
    for para in shape.text_frame.paragraphs:
        for run in para.runs:
            if PPTX_COLOR_TAG in run.text:
                # Убираем тег, ставим цвет
                run.text = run.text.replace(PPTX_COLOR_TAG, "")
                run.font.color.rgb = rgb
            else:
                # Красим весь текст фрейма цветом департамента
                run.font.color.rgb = rgb


def _fill_blocks_slide(prs: Presentation, context: dict) -> None:
    """
    Если в шаблоне есть слайды с плейсхолдером {{blocks}},
    дублирует слайд-шаблон для каждого блока и заполняет поля.
    Слайд-шаблон должен содержать фреймы с:
      {{block_title}}  — название блока
      {{block_content}} — текст блока
    """
    template_slide_idx = None
    for idx, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if shape.has_text_frame:
                full_text = shape.text_frame.text
                if "{{block_title}}" in full_text or "{{block_content}}" in full_text:
                    template_slide_idx = idx
                    break
        if template_slide_idx is not None:
            break

    if template_slide_idx is None:
        return  # Нет шаблона блоков — пропускаем

    blocks = context.get("blocks", [])
    rgb = _hex_to_rgb(context["department_color"])

    # Удаляем слайд-шаблон в конце (после дублирования)
    from pptx.oxml.ns import qn
    import copy

    slide_layout = prs.slides[template_slide_idx].slide_layout
    template_xml = copy.deepcopy(prs.slides[template_slide_idx]._element)

    # Вставляем новые слайды для каждого блока
    insert_position = template_slide_idx
    for block in blocks:
        new_slide = prs.slides.add_slide(slide_layout)
        # Копируем элементы из шаблона в новый слайд
        sp_tree = new_slide.shapes._spTree
        for child in list(sp_tree):
            sp_tree.remove(child)
        template_sp_tree = template_xml.find(qn('p:cSld')).find(qn('p:spTree'))
        for child in template_sp_tree:
            sp_tree.append(copy.deepcopy(child))

        block_replacements = {
            "{{block_title}}":   block.get("block_title", ""),
            "{{block_content}}": block.get("content", ""),
            **{k: context[v] for k, v in PPTX_PLACEHOLDERS.items() if v in context},
        }
        for shape in new_slide.shapes:
            _replace_text_in_shape(shape, block_replacements)
            if shape.has_text_frame and PPTX_COLOR_TAG in shape.text_frame.text:
                _apply_department_color_to_shape(shape, rgb)

    # Удаляем слайд-шаблон блоков
    rId = prs.slides._sldIdLst[template_slide_idx].get('r:id') or \
          prs.slides._sldIdLst[template_slide_idx].attrib.get(
              '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
          )
    from lxml import etree
    slide_element = prs.slides._sldIdLst[template_slide_idx]
    prs.slides._sldIdLst.remove(slide_element)


class PptxService:
    def __init__(self) -> None:
        self.reports_dir = Path(settings.reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _get_template(self) -> Presentation:
        if not PPTX_TEMPLATE_PATH.exists():
            raise FileNotFoundError(
                f"PPTX-шаблон не найден: {PPTX_TEMPLATE_PATH}. "
                "Положите report_template.pptx в app/templates/"
            )
        return Presentation(str(PPTX_TEMPLATE_PATH))

    def generate(
        self,
        report: Report,
        student: Student,
        shift: Shift,
        teacher: User,
    ) -> Path:
        """Генерирует PPTX из шаблона и возвращает Path к файлу."""
        prs = self._get_template()
        context = _build_context(report, student, shift, teacher)
        rgb = _hex_to_rgb(context["department_color"])

        # Строим словарь замен для простых плейсхолдеров
        simple_replacements = {
            placeholder: str(context[field])
            for placeholder, field in PPTX_PLACEHOLDERS.items()
        }

        for slide in prs.slides:
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                full_text = shape.text_frame.text

                # Слайды с {{block_title}} / {{block_content}} обрабатываются отдельно
                if "{{block_title}}" in full_text or "{{block_content}}" in full_text:
                    continue

                # Применяем цвет к фреймам с тегом
                if PPTX_COLOR_TAG in full_text:
                    _apply_department_color_to_shape(shape, rgb)

                # Заменяем текстовые плейсхолдеры
                _replace_text_in_shape(shape, simple_replacements)

        # Обрабатываем блоки (дублирование слайда-шаблона)
        _fill_blocks_slide(prs, context)

        output_path = self.reports_dir / safe_pptx_filename(student.full_name)
        prs.save(str(output_path))
        logger.info(f"PPTX generated: {output_path} for student={student.full_name!r}")
        return output_path

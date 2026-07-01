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
# Официальные фирменные цвета департаментов (утверждено заказчиком).
# Должны совпадать с DEPARTMENTS в app/database/models.py.
DEPARTMENT_COLORS: dict[int, str] = {
    1: "F9423A",  # Департамент управления          — красный
    2: "FF672D",  # Департамент общественных связей — оранжево-красный
    3: "EDC731",  # Инженерный департамент          — жёлтый
    4: "242424",  # Департамент Икс                 — тёмно-серый / чёрный
    5: "50C787",  # Научный департамент             — зелёный
    6: "5A88FF",  # IT-департамент                  — синий
    7: "C061F3",  # Департамент дизайна             — фиолетовый
    8: "91D744",  # Проект 11                       — салатовый
    9: "FB4724",  # Летово Джун                     — оранжевый
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

def _resolve_shift_dates(shift: Shift) -> str:
    """Пытается собрать строку с датами смены из доступных полей модели."""
    dates = getattr(shift, "dates", None)
    if dates:
        return str(dates)
    start = getattr(shift, "start_date", None) or getattr(shift, "date_start", None)
    end = getattr(shift, "end_date", None) or getattr(shift, "date_end", None)
    try:
        if start and end:
            return f"{start:%d.%m} – {end:%d.%m.%Y}"
        if start:
            return f"{start:%d.%m.%Y}"
    except (ValueError, TypeError):
        pass
    return ""


def parse_numbered_answers(text: str) -> dict[int, str]:
    """
    Fallback-парсер: вытаскивает пронумерованные ответы «1. …», «2) …»
    из прозаического текста отчёта в словарь {номер: текст}.
    Используется, если структурированные q_answers не переданы явно.
    """
    if not text:
        return {}
    answers: dict[int, str] = {}
    current_num: int | None = None
    buf: list[str] = []
    num_re = re.compile(r"^\s*(\d{1,2})[\.\)]\s+(.*)")
    # Разделитель, после которого идёт полный (прозаический) отчёт — его в
    # пронумерованные ответы не тянем.
    stop_re = re.compile(r"(итогов\w*\s+отч|={3,})", re.IGNORECASE)
    for line in text.splitlines():
        if stop_re.search(line):
            break
        m = num_re.match(line)

        if m:
            if current_num is not None:
                answers[current_num] = " ".join(buf).strip()
            current_num = int(m.group(1))
            buf = [m.group(2).strip()]
        elif current_num is not None and line.strip():
            buf.append(line.strip())
    if current_num is not None:
        answers[current_num] = " ".join(buf).strip()
    return answers


def _build_context(
    report: Report,
    student: Student,
    shift: Shift,
    teacher: User,
    q_answers: dict[int, str] | None = None,
    shift_context: str | None = None,
) -> dict:
    dep_id = shift.department_id or 0
    # Источник ответов для q1..q13: явные структурированные ответы,
    # иначе — пытаемся распарсить пронумерованные пункты из текста отчёта.
    resolved_q = q_answers or parse_numbered_answers(report.generated_text or "")
    return {
        # Основные поля
        "student_name":     student.full_name,
        "shift_name":       shift.name,
        "shift_dates":      _resolve_shift_dates(shift),
        "department_name":  get_department_name(dep_id),
        "department_id":    dep_id,
        "department_color": get_department_color(dep_id),   # HEX без #, напр. "C0392B"
        "teacher_name":     teacher.full_name,
        "report_date":      date.today().strftime("%d.%m.%Y"),
        "report_text":      report.generated_text,
        "revision_count":   report.revision_count,
        # Данные для PPTX-шаблона
        "q_answers":        resolved_q,
        "shift_context":    shift_context or "",
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
        q_answers: dict[int, str] | None = None,
        shift_context: str | None = None,
    ) -> Path:
        """Генерирует DOCX и возвращает Path к файлу."""
        tpl = self._get_template()
        context = _build_context(
            report, student, shift, teacher, q_answers, shift_context
        )

        tpl.render(context)
        output_path = self.reports_dir / safe_filename(student.full_name)
        tpl.save(str(output_path))
        logger.info(f"DOCX generated: {output_path} for student={student.full_name!r}")
        return output_path


# ─── PPTX ─────────────────────────────────────────────────────────────────────
#
# Реальный шаблон report_template.pptx устроен так:
#   • Ответы вставляются по-вопросно: {{ q1_answer }} … {{ q13_answer }}.
#   • Шапка профиля: {{ shift_name }}, {{ shift_dates }}, {{ department_name }},
#     {{ student_name }}.
#   • Разделители между блоками — это СГРУППИРОВАННЫЕ фигуры (пунктирная линия
#     + 2 SVG-уголка), стоящие на фиксированных координатах.
#
# Проблема: текстовые блоки имеют auto-fit и растут вниз при длинном тексте,
# а разделители стоят на месте → длинный ответ «наезжает» на разделитель.
#
# Решение (Вариант A — поток с ре-флоу):
#   1. Заполняем плейсхолдеры (устойчиво к тому, что PowerPoint дробит
#      {{ q4_answer }} на несколько run-ов).
#   2. Оцениваем реальную высоту каждого текстового фрейма после вставки.
#   3. Проходим фигуры слайда сверху вниз и СДВИГАЕМ вниз всё, что ниже
#      выросшего блока (в т.ч. группы-разделители), на величину прироста.
#   4. Высоту слайда увеличиваем, чтобы контент никогда не обрезался.
# Итог: разделитель всегда идёт сразу после своего блока, при любой длине
# текста, а вёрстка не «разваливается».

from pptx.util import Emu

EMU_PER_PT = 12700

# Регекс-шаблоны плейсхолдеров (учитывают произвольные пробелы внутри {{ }})
_PLACEHOLDER_KEYS = [
    "student_name", "shift_name", "shift_dates", "department_name",
    *[f"q{i}_answer" for i in range(1, 14)],
]

# Плейсхолдеры, чей текст красится в цвет департамента
_COLORED_KEYS = {"department_name"}

# Совместимость: тег для явной покраски произвольного фрейма
PPTX_COLOR_TAG = "{{department_color}}"


def _hex_to_rgb(hex_color: str) -> RGBColor:
    """'C0392B' → RGBColor(192, 57, 43)"""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return RGBColor(r, g, b)


def _build_pptx_values(context: dict) -> dict[str, str]:
    """Готовит словарь key → строковое значение для плейсхолдеров шаблона."""
    values: dict[str, str] = {
        "student_name":    str(context.get("student_name", "")),
        "shift_name":      str(context.get("shift_name", "")),
        "shift_dates":     str(context.get("shift_dates", "")),
        "department_name": str(context.get("department_name", "")),
    }
    q_answers: dict[str, str] = context.get("q_answers", {}) or {}
    for i in range(1, 14):
        values[f"q{i}_answer"] = str(q_answers.get(i, q_answers.get(str(i), "")))
    return values


def _fill_paragraph(para, values: dict[str, str], rgb: RGBColor | None) -> bool:
    """
    Заменяет плейсхолдеры в параграфе, склеивая разбитые PowerPoint-ом run-ы.
    Возвращает True, если в параграфе был найден плейсхолдер.
    Если плейсхолдер из _COLORED_KEYS — красит текст в цвет департамента.
    """
    runs = para.runs
    if not runs:
        return False

    full_text = "".join(run.text for run in runs)
    if "{{" not in full_text:
        return False

    new_text = full_text
    found_colored = False
    for key in _PLACEHOLDER_KEYS:
        pattern = re.compile(r"\{\{\s*" + re.escape(key) + r"\s*\}\}")
        if pattern.search(new_text):
            new_text = pattern.sub(lambda _m: values.get(key, ""), new_text)
            if key in _COLORED_KEYS:
                found_colored = True

    if new_text == full_text:
        return False

    # Пишем результат в первый run, остальные очищаем (сохраняем формат первого)
    runs[0].text = new_text
    for run in runs[1:]:
        run.text = ""

    if found_colored and rgb is not None:
        runs[0].font.color.rgb = rgb

    return True


def _fill_shape_text(shape, values: dict[str, str], rgb: RGBColor | None) -> bool:
    """Заполняет плейсхолдеры во фрейме. Возвращает True, если что-то заменено."""
    if not shape.has_text_frame:
        return False
    changed = False
    for para in shape.text_frame.paragraphs:
        if _fill_paragraph(para, values, rgb):
            changed = True
    return changed


def _para_font_pt(para) -> float:
    """Определяет размер шрифта параграфа в пунктах (с запасным значением)."""
    for run in para.runs:
        if run.font.size is not None:
            return run.font.size.pt
    if para.font.size is not None:
        return para.font.size.pt
    return 10.0


def _estimate_textframe_height(shape) -> int:
    """
    Оценивает необходимую высоту текстового фрейма (в EMU) под текущий текст.
    Оценка приблизительная, но нам важен только ПРИРОСТ высоты, поэтому
    мы всегда только увеличиваем высоту и сдвигаем нижние фигуры.
    """
    tf = shape.text_frame
    width_emu = shape.width or 0
    if width_emu <= 0:
        return shape.height or 0
    width_pt = width_emu / EMU_PER_PT

    total_lines = 0.0
    max_font_pt = 10.0
    for para in tf.paragraphs:
        font_pt = _para_font_pt(para)
        max_font_pt = max(max_font_pt, font_pt)
        text = para.text or ""
        # Средняя ширина символа кириллицы ~0.55 от кегля
        char_pt = font_pt * 0.55
        chars_per_line = max(1, int(width_pt / char_pt))
        # Учитываем явные переносы строк внутри параграфа
        line_segments = text.split("\n") if text else [""]
        para_lines = 0
        for seg in line_segments:
            seg_len = len(seg)
            para_lines += max(1, -(-seg_len // chars_per_line))  # ceil-деление
        total_lines += para_lines

    # Высота строки ~1.3 кегля + межпараграфные отступы + внутр. поля фрейма
    line_h_pt = max_font_pt * 1.3
    text_h_pt = total_lines * line_h_pt
    para_gap_pt = 6.0 * len(tf.paragraphs)
    padding_pt = 8.0
    est_pt = text_h_pt + para_gap_pt + padding_pt
    return int(est_pt * EMU_PER_PT)


def _reflow_slide(slide, grown_extra: dict[int, int], slide_height: int) -> int:
    """
    Сдвигает фигуры вниз так, чтобы разделители всегда шли ПОСЛЕ своих блоков.
    grown_extra: {id(shape): прирост_высоты_в_EMU} для выросших текстовых боксов.
    Возвращает требуемую высоту слайда (EMU), чтобы ничего не обрезалось.
    """
    # Собираем фигуры верхнего уровня с валидной позицией
    shapes = [s for s in slide.shapes if s.top is not None and s.height is not None]
    shapes.sort(key=lambda s: s.top)

    cumulative = 0  # накопленный сдвиг вниз
    max_bottom = slide_height
    for shape in shapes:
        if cumulative:
            shape.top = shape.top + cumulative
        extra = grown_extra.get(id(shape), 0)
        bottom = shape.top + (shape.height or 0) + extra
        if bottom > max_bottom:
            max_bottom = bottom
        # После этой фигуры всё нижеследующее опускается на её прирост
        cumulative += extra

    return max_bottom + Emu(int(0.3 * 914400))  # +0.3" нижнего поля


def _insert_legend_block(slide, title: str, body_text: str,
                         rgb: RGBColor) -> int:
    """
    Вставляет блок «ЛЕГЕНДА СМЕНЫ» после профиля сотрудника (шапки).
    Возвращает суммарную высоту вставленного блока (EMU) — на неё нужно
    опустить всё, что расположено ниже точки вставки.
    Реализовано через клонирование ближайшего блока-заголовка и разделителя,
    что сохраняет фирменное оформление шаблона.
    """
    import copy
    from pptx.oxml.ns import qn

    # Находим якорь — текстовый бокс профиля («ПРОФИЛЬ СОТРУДНИКА …»)
    anchor = None
    for shape in slide.shapes:
        if shape.has_text_frame and "ПРОФИЛЬ СОТРУДНИКА" in shape.text_frame.text:
            anchor = shape
            break
    if anchor is None:
        return 0

    left = anchor.left
    width = anchor.width
    # Точка вставки — ниже блока «шапки» профиля.
    # Берём максимум низа среди верхних фигур профиля (шапка + инфо-группа).
    profile_bottom = anchor.top + (anchor.height or 0)
    for shape in slide.shapes:
        if shape is anchor:
            continue
        if shape.top is not None and shape.top < anchor.top + Emu(int(1.6 * 914400)):
            b = shape.top + (shape.height or 0)
            if b > profile_bottom:
                profile_bottom = b

    gap = Emu(int(0.12 * 914400))
    cur_y = profile_bottom + gap

    # --- Заголовок «ЛЕГЕНДА СМЕНЫ» ---
    title_box = slide.shapes.add_textbox(left, cur_y, width, Pt(24))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = title
    run.font.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = rgb
    title_h = _estimate_textframe_height(title_box)
    title_box.height = title_h
    cur_y = cur_y + title_h + gap

    # --- Тело легенды (контекст смены) ---
    body_box = slide.shapes.add_textbox(left, cur_y, width, Pt(24))
    bf = body_box.text_frame
    bf.word_wrap = True
    bp = bf.paragraphs[0]
    brun = bp.add_run()
    brun.text = body_text or "Контекст смены не указан."
    brun.font.size = Pt(10)
    brun.font.color.rgb = _hex_to_rgb("0F1115")
    body_h = _estimate_textframe_height(body_box)
    body_box.height = body_h
    cur_y = cur_y + body_h + gap

    # --- Разделитель: клонируем ближайшую группу-разделитель ---
    sep_height = 0
    sep_group_xml = None
    for shape in slide.shapes:
        # Разделитель — это группа, содержащая пунктирную линию (cxnSp)
        el = shape._element
        if el.tag == qn("p:grpSp") and el.find(".//" + qn("p:cxnSp")) is not None:
            sep_group_xml = copy.deepcopy(el)
            sep_height = shape.height or 0
            break

    if sep_group_xml is not None:
        # Переносим клон в дерево фигур и ставим его под телом легенды
        spTree = slide.shapes._spTree
        spTree.append(sep_group_xml)
        grp_xfrm = sep_group_xml.find(qn("p:grpSpPr") + "/" + qn("a:xfrm"))
        if grp_xfrm is not None:
            off = grp_xfrm.find(qn("a:off"))
            if off is not None:
                off.set("y", str(int(cur_y)))
        cur_y = cur_y + sep_height + gap

    return int(cur_y - profile_bottom)


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
        q_answers: dict[int, str] | None = None,
        shift_context: str | None = None,
    ) -> Path:
        """Генерирует PPTX из шаблона и возвращает Path к файлу."""
        prs = self._get_template()
        context = _build_context(
            report, student, shift, teacher, q_answers, shift_context
        )
        rgb = _hex_to_rgb(context["department_color"])
        values = _build_pptx_values(context)
        slide_height = prs.slide_height

        for idx, slide in enumerate(prs.slides):
            # 1) Легенда смены — сразу после профиля (только на 1-м слайде)
            legend_added = 0
            if idx == 0:
                legend_added = _insert_legend_block(
                    slide,
                    title="ЛЕГЕНДА СМЕНЫ",
                    body_text=context.get("shift_context") or "",
                    rgb=rgb,
                )


            # 2) Заполняем плейсхолдеры и запоминаем прирост высоты боксов
            grown_extra: dict[int, int] = {}
            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                # Явная покраска фрейма тегом (обратная совместимость)
                if PPTX_COLOR_TAG in shape.text_frame.text:
                    for para in shape.text_frame.paragraphs:
                        for run in para.runs:
                            run.text = run.text.replace(PPTX_COLOR_TAG, "")
                            run.font.color.rgb = rgb

                before_h = shape.height or 0
                if _fill_shape_text(shape, values, rgb):
                    needed = _estimate_textframe_height(shape)
                    if needed > before_h:
                        grown_extra[id(shape)] = needed - before_h

            # 3) Если вставили легенду — двигаем весь контент профиля ниже точки
            #    вставки (кроме самих новых фигур легенды, что уже на месте).
            #    Реализуется тем же ре-флоу: помечаем «нижние» фигуры приростом 0,
            #    а сдвиг обеспечиваем через отдельный проход.
            if legend_added:
                self._shift_below(slide, legend_added, context)

            # 4) Ре-флоу: разделители всегда идут после своих блоков,
            #    слайд растёт, чтобы ничего не обрезалось.
            required_h = _reflow_slide(slide, grown_extra, slide_height)
            if required_h > slide_height:
                slide_height = required_h

        # Единая высота слайда для всей презентации
        if slide_height > prs.slide_height:
            prs.slide_height = slide_height

        output_path = self.reports_dir / safe_pptx_filename(student.full_name)
        prs.save(str(output_path))
        logger.info(f"PPTX generated: {output_path} for student={student.full_name!r}")
        return output_path

    @staticmethod
    def _shift_below(slide, delta: int, context: dict) -> None:
        """
        Опускает вниз на delta все фигуры, которые находятся ниже блока профиля,
        освобождая место под вставленную «Легенду смены».
        Ориентир — верх текстового бокса «ИГРОВАЯ РОЛЬ».
        """
        anchor_top = None
        for shape in slide.shapes:
            if shape.has_text_frame and "ИГРОВАЯ РОЛЬ" in shape.text_frame.text:
                anchor_top = shape.top
                break
        if anchor_top is None:
            return
        for shape in slide.shapes:
            if shape.top is not None and shape.top >= anchor_top:
                shape.top = shape.top + delta


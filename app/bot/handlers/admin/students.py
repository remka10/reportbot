import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import (
    students_menu, shifts_list_keyboard, students_list_keyboard,
    confirm_keyboard, back_keyboard, departments_list_keyboard,
)
from app.bot.states.admin_states import (
    AddStudentStates, EditStudentStates, DeleteStudentStates,
    ViewStudentsStates,
)
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.department_repo import DepartmentRepository

logger = logging.getLogger(__name__)
router = Router(name="admin_students")


@router.callback_query(F.data == "admin:students")
async def cb_students_menu(cb: CallbackQuery, user: User) -> None:
    if user.role != UserRole.admin:
        await cb.answer("Нет доступа", show_alert=True)

        return
    await cb.message.edit_text("👦 <b>Управление учащимися</b>", reply_markup=students_menu())


async def _show_departments(cb: CallbackQuery, session: AsyncSession, shift_id: int) -> bool:
    """Показывает департаменты выбранной смены. Возвращает False если их нет."""
    dep_repo = DepartmentRepository(session)
    departments = list(await dep_repo.get_by_shift(shift_id))
    if not departments:
        await cb.message.edit_text(
            "В этой смене нет департаментов.",
            reply_markup=back_keyboard("admin:students"),
        )
        return False
    await cb.message.edit_text(
        "Выберите департамент:",
        reply_markup=departments_list_keyboard(departments, back_to="admin:students"),
    )
    return True


# ---------------------------------------------------------------------------
# Добавить учащегося
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:students:add")
async def cb_add_student_start(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    repo = ShiftRepository(session)
    shifts = list(await repo.get_all_active())
    if not shifts:
        await cb.message.edit_text("Нет активных смен.", reply_markup=back_keyboard("admin:students"))
        return
    await state.set_state(AddStudentStates.waiting_shift_select)
    await cb.message.edit_text(
        "Выберите смену, в которую добавить учащегося:",
        reply_markup=shifts_list_keyboard(shifts),
    )


@router.callback_query(AddStudentStates.waiting_shift_select, F.data.startswith("select_shift:"))
async def add_student_shift_selected(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(shift_id=shift_id)
    await state.set_state(AddStudentStates.waiting_department_select)
    await _show_departments(cb, session, shift_id)


@router.callback_query(AddStudentStates.waiting_department_select, F.data.startswith("select_department:"))
async def add_student_department_selected(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    department_id = int(cb.data.split(":")[1])
    dep = await DepartmentRepository(session).get_by_id(department_id)
    await state.update_data(department_id=department_id)
    await state.set_state(AddStudentStates.waiting_full_name)
    await cb.message.edit_text(
        f"Департамент: <b>{dep.name if dep else department_id}</b>\n\n"
        "Введите <b>полное имя</b> учащегося (Фамилия Имя) или список ФИО — каждое с новой строки:\n"
        "<i>Например:</i>\n"
        "Иванов Иван\n"
        "Петрова Анна\n\n"
        "Когда закончите — нажмите /done",
        reply_markup=back_keyboard("admin:students"),
    )


# ВАЖНО: /done должен быть ВЫШЕ общего хендлера имени
@router.message(AddStudentStates.waiting_full_name, Command("done"))
async def add_student_done(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Добавление учащихся завершено.")


@router.message(AddStudentStates.waiting_full_name, F.text)
async def add_student_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        await message.answer("⚠️ Неизвестная команда. Введите имя/список имён или нажмите /done для завершения.")
        return

    full_names = [line.strip() for line in text.splitlines() if line.strip()]
    invalid_names = [name for name in full_names if len(name) < 2]
    if not full_names or invalid_names:
        await message.answer(
            "⚠️ В списке есть слишком короткое имя. "
            "Введите ФИО заново: по одному или несколькими строками."
        )
        return

    data = await state.get_data()
    department_id = data.get("department_id")
    repo = StudentRepository(session)
    students = await repo.create_many(
        full_names=full_names,
        shift_id=data["shift_id"],
        department_id=department_id,
    )
    count = await repo.count_by_department(department_id) if department_id else await repo.count_by_shift(data["shift_id"])
    if len(students) == 1:
        result_text = f"✅ <b>{students[0].full_name}</b> добавлен (#{students[0].position})."
    else:
        result_lines = [f"✅ Добавлено учащихся: <b>{len(students)}</b>"]
        result_lines.extend(f"{student.position}. {student.full_name}" for student in students)
        result_text = "\n".join(result_lines)

    await message.answer(
        f"{result_text}\n"
        f"Всего в департаменте: {count} уч.\n"
        f"Введите следующее имя/список или нажмите /done чтобы завершить."
    )


# ---------------------------------------------------------------------------
# Список учащихся
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:students:list")
async def cb_students_list(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_all_active())
    if not shifts:
        await cb.message.edit_text("Нет активных смен.", reply_markup=back_keyboard("admin:students"))
        return
    await state.set_state(ViewStudentsStates.waiting_shift_select)
    await cb.message.edit_text(
        "Выберите смену для просмотра учащихся:",
        reply_markup=shifts_list_keyboard(shifts),
    )


@router.callback_query(ViewStudentsStates.waiting_shift_select, F.data.startswith("select_shift:"))
async def students_list_shift_selected(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(shift_id=shift_id)
    await state.set_state(ViewStudentsStates.waiting_department_select)
    await _show_departments(cb, session, shift_id)


@router.callback_query(ViewStudentsStates.waiting_department_select, F.data.startswith("select_department:"))
async def students_list_department_selected(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    department_id = int(cb.data.split(":")[1])
    student_repo = StudentRepository(session)
    dep_repo = DepartmentRepository(session)
    students = await student_repo.get_by_department(department_id)
    dep = await dep_repo.get_by_id(department_id)
    await state.clear()
    if not students:
        await cb.message.edit_text(
            f"В департаменте <b>{dep.name if dep else department_id}</b> нет учащихся.",
            reply_markup=back_keyboard("admin:students"),
        )
        return
    lines = [f"👦 <b>Учащиеся: {dep.name if dep else ''} ({len(students)})</b>"]
    for s in students:
        lines.append(f"{s.position}. {s.full_name}")
    await cb.message.edit_text("\n".join(lines), reply_markup=back_keyboard("admin:students"))


# ---------------------------------------------------------------------------
# Редактировать имя
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:students:edit")
async def cb_edit_student_start(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    shifts = list(await ShiftRepository(session).get_all_active())
    await state.set_state(EditStudentStates.waiting_shift_select)
    await cb.message.edit_text("Выберите смену:", reply_markup=shifts_list_keyboard(shifts))


@router.callback_query(EditStudentStates.waiting_shift_select, F.data.startswith("select_shift:"))
async def edit_student_shift(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(shift_id=shift_id)
    await state.set_state(EditStudentStates.waiting_department_select)
    await _show_departments(cb, session, shift_id)


@router.callback_query(EditStudentStates.waiting_department_select, F.data.startswith("select_department:"))
async def edit_student_department(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    department_id = int(cb.data.split(":")[1])
    students = list(await StudentRepository(session).get_by_department(department_id))
    await state.update_data(department_id=department_id)
    await state.set_state(EditStudentStates.waiting_student_select)
    if not students:
        await cb.message.edit_text("В департаменте нет учащихся.", reply_markup=back_keyboard("admin:students"))
        return
    await cb.message.edit_text("Выберите учащегося:", reply_markup=students_list_keyboard(students))


@router.callback_query(EditStudentStates.waiting_student_select, F.data.startswith("select_student:"))
async def edit_student_selected(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    student_id = int(cb.data.split(":")[1])
    student = await StudentRepository(session).get_by_id(student_id)
    await state.update_data(student_id=student_id)
    await state.set_state(EditStudentStates.waiting_new_name)
    await cb.message.edit_text(
        f"Текущее имя: <b>{student.full_name if student else '—'}</b>\nВведите новое имя:"
    )


@router.message(EditStudentStates.waiting_new_name, F.text)
async def edit_student_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    new_name = (message.text or "").strip()
    if len(new_name) < 2:
        await message.answer("⚠️ Имя слишком короткое.")
        return
    data = await state.get_data()
    await StudentRepository(session).update_name(data["student_id"], new_name)
    await state.clear()
    await message.answer(f"✅ Имя изменено на <b>{new_name}</b>.", reply_markup=back_keyboard("admin:students"))


# ---------------------------------------------------------------------------
# Удалить учащегося
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "admin:students:delete")
async def cb_delete_student_start(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    shifts = list(await ShiftRepository(session).get_all_active())
    await state.set_state(DeleteStudentStates.waiting_shift_select)
    await cb.message.edit_text("Выберите смену:", reply_markup=shifts_list_keyboard(shifts))


@router.callback_query(DeleteStudentStates.waiting_shift_select, F.data.startswith("select_shift:"))
async def delete_student_shift(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    shift_id = int(cb.data.split(":")[1])
    await state.update_data(shift_id=shift_id)
    await state.set_state(DeleteStudentStates.waiting_department_select)
    await _show_departments(cb, session, shift_id)


@router.callback_query(DeleteStudentStates.waiting_department_select, F.data.startswith("select_department:"))
async def delete_student_department(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    department_id = int(cb.data.split(":")[1])
    students = list(await StudentRepository(session).get_by_department(department_id))
    await state.update_data(department_id=department_id)
    await state.set_state(DeleteStudentStates.waiting_student_select)
    if not students:
        await cb.message.edit_text("В департаменте нет учащихся.", reply_markup=back_keyboard("admin:students"))
        return
    await cb.message.edit_text("Выберите учащегося для удаления:", reply_markup=students_list_keyboard(students))


@router.callback_query(DeleteStudentStates.waiting_student_select, F.data.startswith("select_student:"))
async def delete_student_selected(cb: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    student_id = int(cb.data.split(":")[1])
    student = await StudentRepository(session).get_by_id(student_id)
    await state.update_data(student_id=student_id)
    await state.set_state(DeleteStudentStates.confirm)
    await cb.message.edit_text(
        f"Удалить <b>{student.full_name if student else '—'}</b>?\n"
        "⚠️ Все ответы и отчёты по этому учащемуся будут удалены.",
        reply_markup=confirm_keyboard(yes_data="admin:students:delete:confirm"),
    )


@router.callback_query(DeleteStudentStates.confirm, F.data == "admin:students:delete:confirm")
async def delete_student_confirm(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    ok = await StudentRepository(session).delete(data["student_id"])
    await state.clear()
    msg = "✅ Учащийся удалён." if ok else "⚠️ Учащийся не найден."
    await cb.message.edit_text(msg, reply_markup=back_keyboard("admin:students"))

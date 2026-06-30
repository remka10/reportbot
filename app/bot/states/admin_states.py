from aiogram.fsm.state import State, StatesGroup


class AddUserStates(StatesGroup):
    waiting_user_id   = State()
    waiting_full_name = State()  # было waiting_fullname — не совпадало с roles.py
    waiting_role      = State()
    confirm           = State()


class ChangeRoleStates(StatesGroup):
    waiting_user_select = State()
    waiting_new_role    = State()


class DeactivateUserStates(StatesGroup):
    waiting_user_select = State()
    confirm             = State()


class CreateShiftStates(StatesGroup):
    # Департамент больше НЕ выбирается — при создании смены автоматически
    # создаются все 9 департаментов.
    waiting_name  = State()
    waiting_dates = State()


class ArchiveShiftStates(StatesGroup):
    waiting_shift_select = State()
    confirm              = State()


class AssignTeacherStates(StatesGroup):
    waiting_shift_select      = State()
    waiting_department_select = State()
    waiting_teacher_select    = State()


class AddStudentStates(StatesGroup):
    waiting_shift_select      = State()
    waiting_department_select = State()
    waiting_full_name         = State()


class EditStudentStates(StatesGroup):
    waiting_shift_select      = State()
    waiting_department_select = State()
    waiting_student_select    = State()
    waiting_new_name          = State()


class DeleteStudentStates(StatesGroup):
    waiting_shift_select      = State()
    waiting_department_select = State()
    waiting_student_select    = State()
    confirm                   = State()


class ViewStudentsStates(StatesGroup):
    waiting_shift_select      = State()
    waiting_department_select = State()


class AdminFillStates(StatesGroup):
    """Заполнение отчётов администратором: выбор любой смены и департамента."""
    waiting_shift_select      = State()
    waiting_department_select = State()



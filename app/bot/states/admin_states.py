from aiogram.fsm.state import State, StatesGroup


class AddUserStates(StatesGroup):
    waiting_user_id   = State()
    waiting_full_name = State()   # roles.py использует waiting_full_name
    waiting_role      = State()
    confirm           = State()


class ChangeRoleStates(StatesGroup):
    waiting_user_select = State()
    waiting_new_role    = State()


class DeactivateUserStates(StatesGroup):
    waiting_user_select = State()
    confirm             = State()


class CreateShiftStates(StatesGroup):
    waiting_name       = State()
    waiting_department = State()
    waiting_dates      = State()


class ArchiveShiftStates(StatesGroup):
    waiting_shift_select = State()
    confirm              = State()


class AssignTeacherStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_teacher_select = State()


class AddStudentStates(StatesGroup):
    waiting_shift_select = State()
    waiting_full_name    = State()   # students.py использует waiting_full_name


class EditStudentStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_student_select = State()
    waiting_new_name       = State()


class DeleteStudentStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_student_select = State()
    confirm                = State()

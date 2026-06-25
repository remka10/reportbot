from aiogram.fsm.state import State, StatesGroup


class AddUserStates(StatesGroup):
    waiting_user_id  = State()
    waiting_fullname = State()
    waiting_role     = State()
    confirm          = State()


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


# ДОБАВЛЕНО: отсутствовал — shifts.py его импортировал и падал
class ArchiveShiftStates(StatesGroup):
    waiting_shift_select = State()
    confirm              = State()


class AssignTeacherStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_teacher_select = State()


class AddStudentStates(StatesGroup):
    waiting_shift_select = State()
    waiting_fullname     = State()


class EditStudentStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_student_select = State()
    waiting_new_name       = State()


class DeleteStudentStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_student_select = State()
    confirm                = State()
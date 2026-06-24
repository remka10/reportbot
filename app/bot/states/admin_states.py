from aiogram.fsm.state import State, StatesGroup


class AddUserStates(StatesGroup):
    waiting_user_id   = State()  # Ввод Telegram ID
    waiting_full_name = State()  # Ввод имени
    waiting_role      = State()  # Выбор роли (inline-кнопки)
    confirm           = State()  # Подтверждение


class ChangeRoleStates(StatesGroup):
    waiting_user_select = State()  # Выбор пользователя из списка
    waiting_new_role    = State()  # Выбор новой роли


class DeactivateUserStates(StatesGroup):
    waiting_user_select = State()  # Выбор пользователя
    confirm             = State()  # Подтверждение


class CreateShiftStates(StatesGroup):
    waiting_name          = State()  # Название смены
    waiting_department    = State()  # Выбор департамента (1–8)
    waiting_start_date    = State()  # Дата начала (ДД.ММ.ГГГГ)
    waiting_end_date      = State()  # Дата окончания
    confirm               = State()  # Подтверждение


class AssignTeacherStates(StatesGroup):
    waiting_shift_select   = State()  # Выбор смены
    waiting_teacher_select = State()  # Выбор педагога


class AddStudentStates(StatesGroup):
    waiting_shift_select = State()  # Выбор смены
    waiting_full_name    = State()  # Имя учащегося (можно несколько через Enter)
    confirm              = State()


class EditStudentStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_student_select = State()
    waiting_new_name       = State()


class DeleteStudentStates(StatesGroup):
    waiting_shift_select   = State()
    waiting_student_select = State()
    confirm                = State()
from aiogram import Dispatcher

from app.bot.handlers.start import router as start_router
from app.bot.handlers.admin.roles import router as admin_roles_router
from app.bot.handlers.admin.shifts import router as admin_shifts_router
from app.bot.handlers.admin.students import router as admin_students_router
from app.bot.handlers.admin.fill import router as admin_fill_router

from app.bot.handlers.teacher.shift import router as teacher_shift_router
from app.bot.handlers.teacher.child import router as teacher_child_router
from app.bot.handlers.teacher.questions import router as teacher_questions_router
from app.bot.handlers.teacher.generation import router as teacher_generation_router
from app.bot.handlers.teacher.export import router as teacher_export_router


def register_all_routers(dp: Dispatcher) -> None:
    """Регистрирует все роутеры в диспетчере."""
    # Порядок важен — более специфичные роутеры раньше
    dp.include_router(start_router)

    # Admin
    dp.include_router(admin_roles_router)
    dp.include_router(admin_shifts_router)
    dp.include_router(admin_students_router)
    dp.include_router(admin_fill_router)


    # Teacher
    dp.include_router(teacher_shift_router)
    dp.include_router(teacher_child_router)
    dp.include_router(teacher_questions_router)
    dp.include_router(teacher_generation_router)
    dp.include_router(teacher_export_router)
from aiogram.fsm.state import State, StatesGroup


class UserReport(StatesGroup):
    waiting_photo = State()
    waiting_location = State()


class UserContactAdmin(StatesGroup):
    waiting_message = State()


class AdminAddRegion(StatesGroup):
    waiting_name = State()
    waiting_type = State()


class AdminAddAdmin(StatesGroup):
    waiting_telegram_id = State()
    waiting_role = State()
    waiting_region = State()
    waiting_district = State()
    waiting_channel = State()


class AdminRemoveAdmin(StatesGroup):
    waiting_telegram_id = State()


class AdminSetChannel(StatesGroup):
    waiting_telegram_id = State()
    waiting_channel = State()


class AdminEditRegion(StatesGroup):
    waiting_new_name = State()
    waiting_new_type = State()

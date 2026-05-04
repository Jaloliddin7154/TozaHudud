from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def superadmin_panel_kb() -> ReplyKeyboardMarkup:
    """Full panel for the superadmin."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Statistika"),
                KeyboardButton(text="📥 Hisobot yuklash"),
            ],
            [
                KeyboardButton(text="🗺 Hudud qo'shish"),
                KeyboardButton(text="📝 Hududlar boshqaruvi"),
            ],
            [
                KeyboardButton(text="👥 Admin boshqaruvi"),
                KeyboardButton(text="📋 Xabarlar ro'yxati"),
            ],
        ],
        resize_keyboard=True,
    )


def admin_panel_kb() -> ReplyKeyboardMarkup:
    """Simplified panel for regular (district) admins."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Statistika"),
                KeyboardButton(text="📥 Hisobot yuklash"),
            ],
            [KeyboardButton(text="📋 Xabarlar ro'yxati")],
        ],
        resize_keyboard=True,
    )


def report_export_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Excel (.xlsx)", callback_data="export_excel"),
                InlineKeyboardButton(text="📄 PDF", callback_data="export_pdf"),
            ]
        ]
    )


def region_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏙 Viloyat", callback_data="region_type:viloyat"),
                InlineKeyboardButton(text="🏘 Tuman", callback_data="region_type:tuman"),
            ]
        ]
    )


def admin_manage_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admin_add")],
            [InlineKeyboardButton(text="🗑 Admin o'chirish", callback_data="admin_remove")],
            [InlineKeyboardButton(text="📋 Adminlar ro'yxati", callback_data="admin_list")],
        ]
    )


def report_status_kb(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Bajarildi", callback_data=f"status:done:{report_id}"
                ),
                InlineKeyboardButton(
                    text="🔄 Jarayonda", callback_data=f"status:in_progress:{report_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Rad etildi", callback_data=f"status:rejected:{report_id}"
                )
            ],
        ]
    )


def regions_list_kb(regions: list) -> InlineKeyboardMarkup:
    """Inline keyboard with one button per region — tap to manage it."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"{'🏙' if r.type == 'viloyat' else '🏘'} {r.name} ({r.type})",
                callback_data=f"region_manage:{r.id}",
            )
        ]
        for r in regions
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def region_actions_kb(region_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Nomini tahrirlash",
                    callback_data=f"region_edit_name:{region_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Turini o'zgartirish",
                    callback_data=f"region_edit_type:{region_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=f"region_delete:{region_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Orqaga",
                    callback_data="regions_back",
                )
            ],
        ]
    )


def region_confirm_delete_kb(region_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, o'chirish",
                    callback_data=f"region_delete_confirm:{region_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=f"region_manage:{region_id}",
                ),
            ]
        ]
    )


def region_new_type_kb(region_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏙 Viloyat",
                    callback_data=f"region_set_type:{region_id}:viloyat",
                ),
                InlineKeyboardButton(
                    text="🏘 Tuman",
                    callback_data=f"region_set_type:{region_id}:tuman",
                ),
            ]
        ]
    )


def export_district_filter_kb(districts: list[str]) -> InlineKeyboardMarkup:
    """Superadmin: choose which district to export (or all)."""
    rows = [
        [InlineKeyboardButton(text="🌐 Barchasi", callback_data="xfilt:__all__")]
    ]
    for d in districts:
        rows.append(
            [InlineKeyboardButton(text=f"📍 {d}", callback_data=f"xfilt:{d}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def export_format_kb() -> InlineKeyboardMarkup:
    """Choose Excel or PDF after district is selected."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Excel (.xlsx)", callback_data="xfmt:excel"),
                InlineKeyboardButton(text="📄 PDF", callback_data="xfmt:pdf"),
            ]
        ]
    )

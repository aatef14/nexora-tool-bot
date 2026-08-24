"""Nexo Convert — unit conversion between length, weight, volume, and
temperature units. Pure Python, no external API or API key required.
"""

import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import deny_access, is_allowed

NAME = "Nexo Convert"
SLUG = "convert"
COMMAND = "convert"
EMOJI = "📐"
SUMMARY = "Convert between units — length, weight, volume, temperature."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Usage: /convert <number> <from_unit> to <to_unit>\n\n"
    "Examples:\n"
    "/convert 10 km to mi\n"
    "/convert 5 kg to lb\n"
    "/convert 100 c to f\n\n"
    "Supported units:\n"
    "- Length: m, km, cm, mm, mi, yd, ft, in\n"
    "- Weight: kg, g, mg, lb, oz\n"
    "- Volume: l, ml, gal, qt, pt, cup, floz\n"
    "- Temperature: c, f, k"
)

# {unit: (category, factor_to_base_unit)} for linear categories.
# Base units: meter (length), kilogram (weight), liter (volume).
_LINEAR_UNITS: dict[str, tuple[str, float]] = {
    # Length (base: m)
    "m": ("length", 1.0),
    "km": ("length", 1000.0),
    "cm": ("length", 0.01),
    "mm": ("length", 0.001),
    "mi": ("length", 1609.344),
    "yd": ("length", 0.9144),
    "ft": ("length", 0.3048),
    "in": ("length", 0.0254),
    # Weight (base: kg)
    "kg": ("weight", 1.0),
    "g": ("weight", 0.001),
    "mg": ("weight", 0.000001),
    "lb": ("weight", 0.45359237),
    "oz": ("weight", 0.028349523125),
    # Volume (base: l)
    "l": ("volume", 1.0),
    "ml": ("volume", 0.001),
    "gal": ("volume", 3.785411784),
    "qt": ("volume", 0.946352946),
    "pt": ("volume", 0.473176473),
    "cup": ("volume", 0.2365882365),
    "floz": ("volume", 0.0295735295625),
}

_TEMPERATURE_UNITS = {"c", "f", "k"}

PARSE_RE = re.compile(r"^\s*([-+]?[\d.]+)\s*([a-zA-Z]+)\s+to\s+([a-zA-Z]+)\s*$", re.IGNORECASE)


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    from_unit = from_unit.lower()
    to_unit = to_unit.lower()

    # Convert to Celsius first.
    if from_unit == "c":
        celsius = value
    elif from_unit == "f":
        celsius = (value - 32) * 5.0 / 9.0
    elif from_unit == "k":
        celsius = value - 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit!r}")

    if to_unit == "c":
        return celsius
    elif to_unit == "f":
        return celsius * 9.0 / 5.0 + 32
    elif to_unit == "k":
        return celsius + 273.15
    else:
        raise ValueError(f"Unknown temperature unit: {to_unit!r}")


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert `value` from `from_unit` to `to_unit`.

    Raises ValueError with a clear message if either unit is unknown or if
    the two units belong to different categories (e.g. km to kg).
    """
    from_key = from_unit.strip().lower()
    to_key = to_unit.strip().lower()

    from_is_temp = from_key in _TEMPERATURE_UNITS
    to_is_temp = to_key in _TEMPERATURE_UNITS

    if from_is_temp or to_is_temp:
        if not (from_is_temp and to_is_temp):
            raise ValueError(
                f"Can't convert between {from_unit!r} and {to_unit!r}: "
                "incompatible unit categories."
            )
        return _convert_temperature(value, from_key, to_key)

    from_entry = _LINEAR_UNITS.get(from_key)
    to_entry = _LINEAR_UNITS.get(to_key)

    if from_entry is None:
        raise ValueError(f"Unknown unit: {from_unit!r}")
    if to_entry is None:
        raise ValueError(f"Unknown unit: {to_unit!r}")

    from_category, from_factor = from_entry
    to_category, to_factor = to_entry

    if from_category != to_category:
        raise ValueError(
            f"Can't convert between {from_unit!r} ({from_category}) and "
            f"{to_unit!r} ({to_category}): incompatible unit categories."
        )

    base_value = value * from_factor
    return base_value / to_factor


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /convert <number> <from_unit> to <to_unit>."""
    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    args_text = " ".join(context.args) if context.args else ""
    match = PARSE_RE.match(args_text)
    if not match:
        await update.effective_message.reply_text(
            "Sorry, I couldn't parse that.\n\n" + USAGE
        )
        return

    raw_value, from_unit, to_unit = match.groups()
    try:
        value = float(raw_value)
    except ValueError:
        await update.effective_message.reply_text(
            "Sorry, I couldn't parse that number.\n\n" + USAGE
        )
        return

    try:
        result = convert(value, from_unit, to_unit)
    except ValueError as e:
        await update.effective_message.reply_text(f"{e}\n\n{USAGE}")
        return

    await update.effective_message.reply_text(
        f"{raw_value} {from_unit} = {result:.6g} {to_unit}"
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))

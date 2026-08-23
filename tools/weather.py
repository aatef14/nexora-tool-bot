"""Nexo Weather — current weather for a city via the free Open-Meteo API.

No API key required. Uses Open-Meteo's geocoding endpoint to resolve a city
name to coordinates, then fetches the current weather for those coordinates.
"""

import asyncio
import logging
import urllib.parse

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Weather"
SLUG = "weather"
COMMAND = "weather"
EMOJI = "🌤️"
SUMMARY = "Current weather for any city, no API key needed."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Usage: /weather <city name>\n"
    "Example: /weather London\n"
    "Example: /weather New York\n\n"
    "I'll look up the city and reply with the current temperature, wind "
    "speed, and conditions."
)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 8

logger = logging.getLogger("nexora-tool-bot.weather")

WEATHERCODE_LABELS = {
    0: ("Clear sky", "☀️"),
    1: ("Mainly clear", "🌤️"),
    2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"),
    48: ("Fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Drizzle", "🌦️"),
    55: ("Dense drizzle", "🌦️"),
    56: ("Freezing drizzle", "🌦️"),
    57: ("Freezing drizzle", "🌦️"),
    61: ("Light rain", "🌧️"),
    63: ("Rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"),
    67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"),
    73: ("Snow", "🌨️"),
    75: ("Heavy snow", "🌨️"),
    77: ("Snow grains", "🌨️"),
    80: ("Rain showers", "🌦️"),
    81: ("Rain showers", "🌦️"),
    82: ("Violent rain showers", "🌧️"),
    85: ("Snow showers", "🌨️"),
    86: ("Snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm with hail", "⛈️"),
    99: ("Thunderstorm with hail", "⛈️"),
}


def describe_weathercode(code) -> str:
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "Unknown conditions"
    label, _ = WEATHERCODE_LABELS.get(code, ("Unknown conditions", ""))
    return label


async def fetch_weather(city: str) -> dict | None:
    """Look up current weather for city. Returns None if the city can't be
    found, or raises RuntimeError on network/parsing failure."""
    try:
        geo_resp = await asyncio.to_thread(
            requests.get,
            GEOCODING_URL,
            params={"name": urllib.parse.quote(city), "count": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
    except Exception as e:
        raise RuntimeError(f"Geocoding request failed: {e}") from e

    results = geo_data.get("results") or []
    if not results:
        return None

    place = results[0]
    try:
        lat = place["latitude"]
        lon = place["longitude"]
        place_name = place.get("name") or city
        country = place.get("country") or ""
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"Malformed geocoding response: {e}") from e

    try:
        forecast_resp = await asyncio.to_thread(
            requests.get,
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        forecast_resp.raise_for_status()
        forecast_data = forecast_resp.json()
    except Exception as e:
        raise RuntimeError(f"Forecast request failed: {e}") from e

    try:
        current = forecast_data["current_weather"]
        temperature_c = current["temperature"]
        windspeed_kmh = current["windspeed"]
        weathercode = current["weathercode"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"Malformed forecast response: {e}") from e

    return {
        "city": place_name,
        "country": country,
        "temperature_c": temperature_c,
        "windspeed_kmh": windspeed_kmh,
        "condition": describe_weathercode(weathercode),
    }


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return

    if not context.args:
        await update.effective_message.reply_text(USAGE)
        return

    city = " ".join(context.args)

    try:
        weather = await fetch_weather(city)
    except RuntimeError as e:
        logger.warning("Weather lookup failed for %r: %s", city, e)
        await update.effective_message.reply_text(
            "Couldn't reach the weather service right now, try again later."
        )
        return

    if weather is None:
        await update.effective_message.reply_text(f"Couldn't find a place called '{city}'.")
        return

    location = weather["city"]
    if weather["country"]:
        location = f"{location}, {weather['country']}"

    message = (
        f"{EMOJI} Weather in {location}\n"
        f"Condition: {weather['condition']}\n"
        f"Temperature: {weather['temperature_c']}°C\n"
        f"Wind: {weather['windspeed_kmh']} km/h"
    )
    await update.effective_message.reply_text(message)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))

"""Nexo Crypto — look up a cryptocurrency's current price in USD.

Uses CoinGecko's free public API (no API key needed).
"""

import asyncio
import logging

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Crypto"
SLUG = "crypto"
COMMAND = "price"
EMOJI = "💰"
SUMMARY = "Check a cryptocurrency's current price."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Usage: /price <coin>\n\n"
    "<coin> can be a common ticker (btc, eth, sol, doge...) or a CoinGecko "
    "coin id (bitcoin, ethereum...).\n\n"
    "Examples:\n"
    "/price btc\n"
    "/price eth\n"
    "/price dogecoin"
)

TIMEOUT_SECONDS = 8

# CoinGecko's simple price endpoint needs a "coin id" (e.g. "bitcoin"), not
# a ticker symbol (e.g. "btc") — tickers and ids don't always match, so we
# map the common ones here. Anything not in this dict is passed through
# as-is, so people can also type a full CoinGecko id directly.
TICKER_TO_ID = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "doge": "dogecoin",
    "ada": "cardano",
    "xrp": "ripple",
    "bnb": "binancecoin",
    "usdt": "tether",
    "usdc": "usd-coin",
    "matic": "matic-network",
    "ltc": "litecoin",
    "dot": "polkadot",
    "avax": "avalanche-2",
    "shib": "shiba-inu",
    "trx": "tron",
    "link": "chainlink",
    "xlm": "stellar",
    "atom": "cosmos",
    "uni": "uniswap",
    "bch": "bitcoin-cash",
}

logger = logging.getLogger("nexora-tool-bot.crypto")


async def fetch_price(query: str) -> dict | None:
    """Look up a coin's current USD price via CoinGecko.

    Returns a dict with coin_id, price_usd, change_24h_pct, or None if the
    coin isn't found. Raises RuntimeError on network/parsing failure.
    """
    coin_id = TICKER_TO_ID.get(query.lower(), query.lower())

    try:
        response = await asyncio.to_thread(
            requests.get,
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch price for {coin_id!r}: {e}") from e

    coin_data = data.get(coin_id)
    if not coin_data or "usd" not in coin_data:
        return None

    return {
        "coin_id": coin_id,
        "price_usd": coin_data.get("usd"),
        "change_24h_pct": coin_data.get("usd_24h_change"),
    }


def _format_price(price: float) -> str:
    if price >= 1:
        return f"{price:,.2f}"
    # Small fractional coins shouldn't round to $0.00 — use up to 6 decimals.
    return f"{price:,.6f}".rstrip("0").rstrip(".")


def _format_change(change) -> str:
    if change is None:
        return "n/a"
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return

    if not context.args:
        await update.effective_message.reply_text(USAGE)
        return

    query = context.args[0]

    try:
        result = await fetch_price(query)
    except RuntimeError as e:
        logger.warning("Price fetch failed for %r: %s", query, e)
        await update.effective_message.reply_text(
            "Couldn't reach the price service right now, try again later."
        )
        return

    if result is None:
        await update.effective_message.reply_text(
            f"Couldn't find a coin called '{query}'. Try a ticker like btc, eth, sol, or a CoinGecko id."
        )
        return

    price_str = _format_price(result["price_usd"])
    change_str = _format_change(result["change_24h_pct"])
    await update.effective_message.reply_text(
        f"{result['coin_id']}: ${price_str} ({change_str} 24h)"
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))

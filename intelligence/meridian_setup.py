#!/usr/bin/env python3
"""Interactive setup wizard for Meridian product configuration."""

from __future__ import annotations

from meridian_config import (
    DEFAULT_ALLOWED_ORIGIN,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    save_config,
)

BANNER = r"""
 __  __           _     _ _
|  \/  | ___ _ __(_) __| (_)_ __ _ __
| |\/| |/ _ \ '__| |/ _` | | '__| '_ \
| |  | |  __/ |  | | (_| | | |  | | | |
|_|  |_|\___|_|  |_|\__,_|_|_|  |_| |_|
""".strip("\n")


def _prompt(message: str, default: str = "") -> str:
    raw = input(message).strip()
    if raw:
        return raw
    return default


def main() -> int:
    print(BANNER)
    print()
    llm_base_url = _prompt(f"LLM Base URL [default: {DEFAULT_LLM_BASE_URL}]: ", DEFAULT_LLM_BASE_URL)
    llm_model = _prompt(f"LLM Model Name [default: {DEFAULT_LLM_MODEL}]: ", DEFAULT_LLM_MODEL)
    llm_api_key = input("LLM API Key (Leave blank if using local GPU): ").strip()
    telegram_bot_token = input("Telegram Bot Token (Leave blank to skip): ").strip()
    allowed_origin = _prompt(
        f"Allowed Web Frontend Origin for CORS [default: {DEFAULT_ALLOWED_ORIGIN}]: ",
        DEFAULT_ALLOWED_ORIGIN,
    )

    path = save_config(
        {
            "llm_base_url": llm_base_url,
            "llm_model": llm_model,
            "llm_api_key": llm_api_key,
            "telegram_bot_token": telegram_bot_token,
            "allowed_origin": allowed_origin,
        }
    )
    print()
    print(f"Meridian configuration saved to {path}.")
    print("Startup guidance:")
    print('- Run python3 meridian_gateway.py')
    print('- Web requests are served on http://127.0.0.1:8266 when the gateway is running')
    print('- Telegram routing is enabled automatically when a bot token is configured')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

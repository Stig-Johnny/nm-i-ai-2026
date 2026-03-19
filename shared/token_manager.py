"""
Token manager — automated JWT + game token fetching for NM i AI 2026.

Auth flow:
  1. Stig logs in once via browser (Google OAuth) → sets `access_token` cookie
  2. We extract cookie from persistent Playwright browser state
  3. All subsequent game tokens fetched via httpx (no clicks needed)

API endpoints:
  GET  https://api.ainm.no/games/maps           → list maps
  POST https://api.ainm.no/games/request        → {map_id} → {token}
  POST https://api.ainm.no/tasks/request        → {task_id} → {token}  (main competition, unconfirmed)
  WS   wss://game.ainm.no/ws?token=JWT          → game
"""

import asyncio
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GAME_REQUEST_API_URL = "https://api.ainm.no/games/request"
TASK_REQUEST_API_URL = "https://api.ainm.no/tasks/request"   # Unconfirmed — update at kickoff
MAPS_API_URL = "https://api.ainm.no/games/maps"
LOGIN_URL = "https://app.ainm.no/challenge"
BROWSER_STATE_PATH = Path.home() / ".config" / "nm-game" / "browser_state"
AUTH_TOKEN_PATH = Path.home() / ".config" / "nm-game" / "access_token"

VALID_DIFFICULTIES = ["easy", "medium", "hard", "expert", "nightmare"]
LOGIN_TIMEOUT = 300  # seconds


class TokenManager:
    """Manages auth cookie + game/task token fetching."""

    def __init__(self):
        self._jwt: str | None = os.environ.get("NM_ACCESS_TOKEN") or None
        # Load cached token if available
        if not self._jwt and AUTH_TOKEN_PATH.exists():
            self._jwt = AUTH_TOKEN_PATH.read_text().strip()
            logger.debug("Loaded cached access_token from disk")

    # ─── Auth ────────────────────────────────────────────────────────────────

    async def get_jwt(self) -> str:
        """Return current JWT, refreshing from browser if needed."""
        if self._jwt:
            return self._jwt
        self._jwt = await self._extract_jwt_from_browser()
        AUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTH_TOKEN_PATH.write_text(self._jwt)
        return self._jwt

    async def _extract_jwt_from_browser(self) -> str:
        """Open persistent browser, wait for user to log in, extract cookie."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError("pip install playwright && playwright install chromium")

        logger.info(f"Opening browser at {LOGIN_URL}")
        logger.info("Log in with Google — waiting up to 5 minutes...")

        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_STATE_PATH),
                headless=False,
            )
            page = await ctx.new_page()
            await page.goto(LOGIN_URL)

            for _ in range(LOGIN_TIMEOUT):
                cookies = await ctx.cookies()
                tok = next((c for c in cookies if c["name"] == "access_token"), None)
                if tok:
                    await ctx.close()
                    logger.info("Login successful — access_token extracted")
                    return tok["value"]
                await asyncio.sleep(1)

            await ctx.close()
            raise TimeoutError("Login timed out after 5 minutes")

    def invalidate_jwt(self):
        """Force re-login on next call (e.g. after 403)."""
        self._jwt = None
        if AUTH_TOKEN_PATH.exists():
            AUTH_TOKEN_PATH.unlink()

    # ─── Maps ─────────────────────────────────────────────────────────────────

    async def get_maps(self) -> list[dict]:
        """List available maps."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(MAPS_API_URL)
            resp.raise_for_status()
            return resp.json()

    # ─── Grocery Bot token ───────────────────────────────────────────────────

    async def get_game_token(self, difficulty: str = "easy") -> str:
        """Get a game token for a Grocery Bot map."""
        if difficulty not in VALID_DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {VALID_DIFFICULTIES}")

        maps = await self.get_maps()
        map_info = next((m for m in maps if m.get("difficulty") == difficulty), None)
        if not map_info:
            raise ValueError(f"No map found for difficulty={difficulty}")

        map_id = map_info["id"]
        jwt = await self.get_jwt()

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GAME_REQUEST_API_URL,
                json={"map_id": map_id},
                cookies={"access_token": jwt},
            )
            if resp.status_code == 403:
                logger.warning("JWT rejected (403) — clearing cache")
                self.invalidate_jwt()
                raise RuntimeError("JWT expired — re-run to trigger fresh login")
            resp.raise_for_status()
            data = resp.json()

        token = data.get("token")
        if not token:
            raise RuntimeError(f"No token in response: {data}")

        logger.info(f"Got game token for {difficulty} map (id={map_id})")
        return token

    # ─── Main competition task token ─────────────────────────────────────────

    async def get_task_token(self, task_id: str) -> str:
        """
        Get a token for a main competition task.
        
        NOTE: Endpoint unconfirmed — update TASK_REQUEST_API_URL at kickoff
        if the actual endpoint differs.
        """
        jwt = await self.get_jwt()

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TASK_REQUEST_API_URL,
                json={"task_id": task_id},
                cookies={"access_token": jwt},
            )
            if resp.status_code == 403:
                self.invalidate_jwt()
                raise RuntimeError("JWT expired — re-run to trigger fresh login")
            resp.raise_for_status()
            data = resp.json()

        token = data.get("token")
        if not token:
            raise RuntimeError(f"No token in response: {data}")

        logger.info(f"Got task token for task_id={task_id}")
        return token


# ─── CLI helper ───────────────────────────────────────────────────────────────

async def _main():
    import argparse
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Fetch NM i AI game/task tokens")
    sub = parser.add_subparsers(dest="cmd")

    maps_p = sub.add_parser("maps", help="List available maps")

    game_p = sub.add_parser("game", help="Get grocery bot game token")
    game_p.add_argument("--difficulty", default="easy", choices=VALID_DIFFICULTIES)

    task_p = sub.add_parser("task", help="Get main competition task token")
    task_p.add_argument("task_id", help="Task ID from the competition platform")

    args = parser.parse_args()
    mgr = TokenManager()

    if args.cmd == "maps":
        maps = await mgr.get_maps()
        for m in maps:
            print(f"  {m.get('difficulty','?'):10} id={m.get('id','?')}")
    elif args.cmd == "game":
        token = await mgr.get_game_token(args.difficulty)
        print(f"wss://game.ainm.no/ws?token={token}")
    elif args.cmd == "task":
        token = await mgr.get_task_token(args.task_id)
        print(f"TOKEN: {token}")
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(_main())

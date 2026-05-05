"""
Optional Supabase smoke test.

This file intentionally reads credentials from environment variables instead of
hardcoding project URLs or JWTs. Run it only when you explicitly want to verify
connectivity against a Supabase project:

    SUPABASE_URL=... SUPABASE_KEY=... python backend/test_supa.py
"""

import asyncio
import os
import sys

from supabase import create_client


async def test() -> int:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("Skipping Supabase smoke test: set SUPABASE_URL and SUPABASE_KEY first.")
        return 0

    supabase = create_client(url, key)

    try:
        res = supabase.table("user_profiles").select("*").limit(1).execute()
        print("user_profiles select success:", len(res.data or []))
    except Exception as exc:
        print("user_profiles select error:", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(test()))

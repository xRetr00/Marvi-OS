from __future__ import annotations

import asyncio
import os

from livekit import rtc


async def main() -> None:
    room = rtc.Room()
    await room.connect(os.environ["LIVEKIT_URL"], os.environ["MARVI_TEST_TOKEN"])
    print(f"room_connected={room.name}")
    await asyncio.sleep(12)
    print(f"remote_participants={len(room.remote_participants)}")
    await room.disconnect()


asyncio.run(main())


"""Close every spike room left on the project, then list what is open."""
import asyncio
import lk
from livekit import api

async def main():
    client = lk._api()
    rooms = await client.room.list_rooms(api.ListRoomsRequest())
    await client.aclose()
    for r in rooms.rooms:
        print("open:", r.name, r.num_participants, "participants")
        if r.name.startswith("spike-"):
            await lk.close_room(r.name)
            print("closed", r.name)
    print("rooms open now:", await lk.list_rooms())

asyncio.run(main())

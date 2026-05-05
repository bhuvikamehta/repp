import asyncio
from backend.main import app
from httpx import AsyncClient

async def test():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/agent/run", json={"prompt": "Summarize the history of space exploration."})
        print("Status:", response.status_code)
        print("Body:", response.json())

if __name__ == "__main__":
    asyncio.run(test())

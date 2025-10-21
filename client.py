# client.py
import asyncio
import random
from GameNetAPI import GameNetAPI

def generate_game_data():
    """Generate random game data for testing."""
    player_id = random.randint(1, 10)
    pos_x = random.uniform(0, 500)
    pos_y = random.uniform(0, 500)
    direction = random.choice([0, 90, 180, 270])
    return {"player_id": player_id, "pos_x": pos_x, "pos_y": pos_y, "dir": direction}

async def main():
    # call the GameNetAPI to connect to the server
    api = GameNetAPI()
    await api.connect()

    for _ in range(50):
        reliable = random.choice([True, False])
        data = generate_game_data()
        await api.send(data, reliable=reliable)
        await asyncio.sleep(0.05)

    await api.close()

if __name__ == "__main__":
    asyncio.run(main())

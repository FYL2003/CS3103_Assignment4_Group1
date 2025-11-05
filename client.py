import asyncio
import random
from GameNetAPI import GameNetAPI

def generate_game_data():
    """Generate random game data packet for testing."""
    player_id = random.randint(1, 10)
    pos_x = random.uniform(0, 500)
    pos_y = random.uniform(0, 500)
    direction = random.choice([0, 90, 180, 270])
    location = random.choice(["forest", "desert", "city", "mountain", "beach"])
    return {
        "player_id": player_id,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "dir": direction,
        "location": location
    }

async def send_data(api):
    """Send 100 game data packets to the server."""
    for i in range(100):
        # add reliable or unreliable tag randomly
        reliable = random.choice([True, False])
        data = generate_game_data()
        await api.send(data, reliable=reliable)
        await asyncio.sleep(0.05)

async def handle_message(data, reliable):
    """Callback for received messages from server"""
    print(f"[SERVER -> CLIENT] {data} (reliable={reliable})")

async def main():
    api = GameNetAPI()
    api.set_message_callback(handle_message)

    await api.connect()
    await send_data(api)

    await api.close()
    await asyncio.sleep(0.1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\nClient stopped by user")
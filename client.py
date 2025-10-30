import asyncio
import random
import sys
import platform
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

async def wait_for_keypress(stop_event):
    """Wait for user to press 'q' key to stop the client."""
    print("Press 'q' to stop...\n")
    if platform.system() == "Windows":
        import msvcrt
        while not stop_event.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key.lower() == b'q':
                    stop_event.set()
                    break
            await asyncio.sleep(0.05)
    else:
        import termios, tty, select
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while not stop_event.is_set():
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    key = sys.stdin.read(1)
                    if key.lower() == 'q':
                        stop_event.set()
                        break
                await asyncio.sleep(0.05)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

async def send_task(stop_event, api):
    """Continuously send game data packets to the server."""
    while not stop_event.is_set():
        # add reliable or unreliable tag randomly
        reliable = random.choice([True, False])
        data = generate_game_data()
        await api.send(data, reliable=reliable)
        await asyncio.sleep(0.05)

async def main():
    stop_event = asyncio.Event()
    api = GameNetAPI()

    async def handle_message(data, reliable):
        """Callback for received messages from server"""
        print(f"[SERVER -> CLIENT] {data} (reliable={reliable})")

    api.set_message_callback(handle_message)
    await api.connect()

    # Run both tasks concurrently
    await asyncio.gather(
        wait_for_keypress(stop_event),
        send_task(stop_event, api),
        return_exceptions=True
    )

    await api.close()


if __name__ == "__main__":
    asyncio.run(main())
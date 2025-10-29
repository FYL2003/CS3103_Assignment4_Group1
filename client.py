import asyncio
import random
import sys
import termios
import tty
from GameNetAPI import GameNetAPI

def generate_game_data():
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

async def send_task(api, stop_event):
    while not stop_event.is_set():
        reliable = random.choice([True, False])
        data = generate_game_data()
        await api.send(data, reliable=reliable)
        await asyncio.sleep(0.05)

async def receive_task(api, stop_event):
    while not stop_event.is_set():
        response = await api.receive(timeout=0.1)
        if response:
            print(f"Received from server: {response}")

async def wait_for_keypress(stop_event):
    print("Press any key to stop...\n")
    
    # Save terminal settings
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        # Set terminal to raw mode
        tty.setraw(fd)
        # Wait for key press in a non-blocking way
        while not stop_event.is_set():
            # Check if input is available
            import select
            if select.select([sys.stdin], [], [], 0.1)[0]:
                sys.stdin.read(1)
                print("\n\nKey pressed! Shutting down...")
                stop_event.set()
                break
            await asyncio.sleep(0.1)
    finally:
        # Restore terminal settings
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

async def main():
    api = GameNetAPI()
    await api.connect()

    stop_event = asyncio.Event()

    # Run send, receive, and keypress listener concurrently
    send = asyncio.create_task(send_task(api, stop_event))
    receive = asyncio.create_task(receive_task(api, stop_event))
    keypress = asyncio.create_task(wait_for_keypress(stop_event))
    
    await keypress
    await send
    await receive
    
    await api.close()
    print("Connection closed")

if __name__ == "__main__":
    asyncio.run(main())
#!/usr/bin/env python3
"""
Test script for QUIC retransmission mechanism.
This script simulates packet loss scenarios to test timeout and retransmission.
"""
import asyncio
import random
from GameNetAPI import GameNetAPI

# Simulate packet loss by dropping some packets
PACKET_LOSS_RATE = 0.0  # Start with no loss to verify basic functionality

async def test_client():
    """Client that sends packets to test retransmission"""
    api = GameNetAPI()

    async def handle_message(data, reliable):
        """Callback for received messages from server"""
        print(f"[CLIENT RECEIVED] {data} (reliable={reliable})")

    api.set_message_callback(handle_message)
    await api.connect()

    print("\n=== Testing Sequential Packet Delivery ===")
    # Send 10 reliable packets
    for i in range(10):
        data = {
            "packet_id": i,
            "message": f"Test message {i}",
            "type": "test"
        }
        await api.send(data, reliable=True)
        await asyncio.sleep(0.05)  # 50ms between packets

    # Wait for all packets to be processed
    await asyncio.sleep(2)

    await api.close()
    print("\n[CLIENT] Test completed")

if __name__ == "__main__":
    asyncio.run(test_client())

"""
Test script for Reliable Data Transfer (RDT) implementation
This script tests both reliable and unreliable packet transmission
"""

import asyncio
import random
import time

from GameNetAPI import GameNetAPI


def generate_test_data(seq_no: int):
    """Generate test data with sequence number for tracking"""
    return {
        "type": "TEST",
        "seq": seq_no,
        "timestamp": int(time.time() * 1000),
        "data": random.randint(0, 1000),
    }


class RDTTester:
    def __init__(self):
        self.received_packets = []
        self.start_time = None
        self.reliable_count = 0
        self.unreliable_count = 0

    async def server_callback(self, data, reliable):
        """Callback for server received messages"""
        # Print statistics about received packet
        packet_type = "RELIABLE" if reliable else "UNRELIABLE"
        if reliable:
            self.reliable_count += 1
        else:
            self.unreliable_count += 1

        print(f"[SERVER] Received {packet_type} packet: {data}")
        self.received_packets.append((data, reliable))

    async def client_callback(self, data, reliable):
        """Callback for client received messages (ACKs etc)"""
        if data.get("type") == "ACK":
            print(f"[CLIENT] Received ACK for sequence {data.get('ack_no')}")
        else:
            print(f"[CLIENT] Received {data}")

    async def run_test(self, num_packets=50):
        """Run RDT test with specified number of packets"""
        # Start server
        server = GameNetAPI(isClient=False)
        server.set_message_callback(self.server_callback)
        server_task = asyncio.create_task(server.start_server())

        # Wait for server to start
        await asyncio.sleep(0.5)

        # Connect client
        client = GameNetAPI()
        client.set_message_callback(self.client_callback)
        await client.connect()

        print("\nStarting RDT test...")
        print("=====================")
        self.start_time = time.time()

        # Send test packets
        for i in range(num_packets):
            # Randomly choose reliable or unreliable
            reliable = random.choice([True, False])
            data = generate_test_data(i)

            # Send packet
            await client.send(data, reliable=reliable)
            print(
                f"[CLIENT] Sent {'reliable' if reliable else 'unreliable'} packet {i}"
            )

            # Random delay between packets
            await asyncio.sleep(random.uniform(0.01, 0.05))

        # Wait for final packets and ACKs
        await asyncio.sleep(1.0)

        # Print statistics
        elapsed = time.time() - self.start_time
        print("\nTest Results")
        print("============")
        print(f"Test duration: {elapsed:.2f} seconds")
        print(f"Total packets sent: {num_packets}")
        print(f"Reliable packets received: {self.reliable_count}")
        print(f"Unreliable packets received: {self.unreliable_count}")
        print(
            f"Packet loss rate: {(num_packets - len(self.received_packets))/num_packets:.2%}"
        )

        # Cleanup
        await client.close()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


async def main():
    tester = RDTTester()
    await tester.run_test(num_packets=50)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest stopped by user")

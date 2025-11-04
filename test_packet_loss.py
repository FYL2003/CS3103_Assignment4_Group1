#!/usr/bin/env python3
"""
Test script to simulate packet loss and verify timeout/retransmission behavior.
This creates a modified client that can drop packets to simulate network issues.
"""
import asyncio
import random
import time
from GameNetAPI import GameNetAPI, GameClientProtocol, RELIABLE, UNRELIABLE, TIMESTAMP_BYTES
import json

# Packet loss simulation parameters
DROP_RATE = 0.3  # Drop 30% of packets to test retransmission

class TestClientProtocol(GameClientProtocol):
    """Modified client protocol that can drop packets for testing"""
    
    def __init__(self, *args, drop_rate=0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self.drop_rate = drop_rate
        self.dropped_packets = []
    
    async def send_packet(self, data: dict, reliable: bool = True):
        """Send a packet with potential drop simulation"""
        channel = RELIABLE if reliable else UNRELIABLE
        seq_no = self.seq[channel]
        
        # Simulate packet drop (but only for initial transmission)
        if reliable and random.random() < self.drop_rate:
            print(f"[SIMULATED DROP] Dropping initial packet Seq {seq_no}")
            self.dropped_packets.append(seq_no)
            # Still track for ACK but don't actually send
            timestamp = int(time.time() * 1000)
            self.pending_acks[seq_no] = (data, time.time(), 0)
            self.seq[channel] += 1
            return
        
        # Normal send
        await super().send_packet(data, reliable)


async def test_with_packet_loss():
    """Test client with simulated packet loss"""
    print(f"\n{'='*70}")
    print(f"Testing with {DROP_RATE*100}% initial packet drop rate")
    print(f"This will test retransmission and timeout mechanisms")
    print(f"{'='*70}\n")
    
    api = GameNetAPI()
    
    async def handle_message(data, reliable):
        """Callback for received messages from server"""
        if not isinstance(data, dict) or data.get("type") != "ACK":
            print(f"[CLIENT RECEIVED] {data} (reliable={reliable})")

    api.set_message_callback(handle_message)
    
    # Manually create connection with our test protocol
    from aioquic.asyncio import connect
    api._connect_ctx = connect(
        api.host,
        api.port,
        configuration=api.config,
        create_protocol=lambda *args, **kwargs: TestClientProtocol(
            *args, on_message=api.on_message, drop_rate=DROP_RATE, **kwargs
        ),
    )
    api.conn = await api._connect_ctx.__aenter__()
    api.connected = True
    print("Connected to QUIC server\n")

    # Send test packets
    print("=== Sending 15 reliable packets ===")
    for i in range(15):
        data = {
            "packet_id": i,
            "message": f"Test message {i}",
            "test": "retransmission"
        }
        await api.conn.send_packet(data, reliable=True)
        await asyncio.sleep(0.03)  # 30ms between packets

    # Wait for retransmissions and server processing
    print("\n=== Waiting for retransmissions and server processing ===")
    await asyncio.sleep(3)

    # Check results
    print(f"\n=== Test Results ===")
    print(f"Dropped packets: {api.conn.dropped_packets}")
    print(f"Pending ACKs (not received): {list(api.conn.pending_acks.keys())}")
    
    await api.close()
    print("\n[CLIENT] Test completed\n")

if __name__ == "__main__":
    asyncio.run(test_with_packet_loss())

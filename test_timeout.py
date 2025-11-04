#!/usr/bin/env python3
"""
Test script to verify server-side timeout mechanism.
This creates a scenario where some packets are permanently lost (never arrive)
to test the server's ability to skip them after timeout.
"""
import asyncio
import time
from GameNetAPI import GameNetAPI, GameClientProtocol, RELIABLE, UNRELIABLE, TIMESTAMP_BYTES
import json

class PermanentDropClientProtocol(GameClientProtocol):
    """Client protocol that permanently drops certain packets"""
    
    def __init__(self, *args, drop_seqs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.drop_seqs = drop_seqs or []
        # Disable retransmission for permanently dropped packets
        if self.retransmit_task and not self.retransmit_task.done():
            self.retransmit_task.cancel()
    
    async def send_packet(self, data: dict, reliable: bool = True):
        """Send a packet, permanently dropping specified sequence numbers"""
        channel = RELIABLE if reliable else UNRELIABLE
        seq_no = self.seq[channel]
        
        # Permanently drop specified packets
        if reliable and seq_no in self.drop_seqs:
            print(f"[PERMANENT DROP] Never sending packet Seq {seq_no}")
            self.seq[channel] += 1
            return
        
        # Normal send (without tracking for retransmission)
        timestamp = int(time.time() * 1000)
        payload = json.dumps(data)
        header = (
            channel.to_bytes(1, "big")
            + seq_no.to_bytes(2, "big")
            + timestamp.to_bytes(TIMESTAMP_BYTES, "big")
        )
        packet = header + payload.encode()

        if reliable:
            stream_id = self._quic.get_next_available_stream_id()
            self._quic.send_stream_data(stream_id, packet, end_stream=True)
            print(f"[RELIABLE] Sent Seq {seq_no}: {payload}")
        
        self.seq[channel] += 1
        self.transmit()


async def test_server_timeout():
    """Test server timeout mechanism by permanently dropping packets"""
    print(f"\n{'='*70}")
    print(f"Testing Server-Side Timeout Mechanism")
    print(f"Packets 2, 5, and 8 will be permanently dropped")
    print(f"Server should timeout and skip them after 200ms")
    print(f"{'='*70}\n")
    
    api = GameNetAPI()
    
    async def handle_message(data, reliable):
        """Callback for received messages from server"""
        if not isinstance(data, dict) or data.get("type") != "ACK":
            print(f"[CLIENT RECEIVED] {data} (reliable={reliable})")

    api.set_message_callback(handle_message)
    
    # Create connection with permanent drop protocol
    from aioquic.asyncio import connect
    DROP_SEQS = [2, 5, 8]
    api._connect_ctx = connect(
        api.host,
        api.port,
        configuration=api.config,
        create_protocol=lambda *args, **kwargs: PermanentDropClientProtocol(
            *args, on_message=api.on_message, drop_seqs=DROP_SEQS, **kwargs
        ),
    )
    api.conn = await api._connect_ctx.__aenter__()
    api.connected = True
    print("Connected to QUIC server\n")

    # Send test packets
    print("=== Sending 12 reliable packets (skipping 2, 5, 8) ===")
    for i in range(12):
        data = {
            "packet_id": i,
            "message": f"Test message {i}",
            "test": "timeout"
        }
        await api.conn.send_packet(data, reliable=True)
        await asyncio.sleep(0.03)  # 30ms between packets

    # Wait for server to timeout and skip missing packets
    print("\n=== Waiting for server timeout (200ms + processing) ===")
    await asyncio.sleep(1.5)

    print("\n=== Expected Behavior ===")
    print(f"Server should have:")
    print(f"  1. Received packets 0, 1 in order")
    print(f"  2. Buffered packets 3, 4 waiting for 2")
    print(f"  3. After 200ms timeout, skipped packet 2 and delivered 3, 4")
    print(f"  4. Similar behavior for packets 5 and 8")
    print(f"  5. All other packets delivered in order")
    
    await api.close()
    print("\n[CLIENT] Test completed\n")

if __name__ == "__main__":
    asyncio.run(test_server_timeout())

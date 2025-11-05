import asyncio
import json
import time
from collections import deque

RELIABLE = 1
UNRELIABLE = 0
RETRANSMISSION_TIMEOUT = 0.2


def current_millis():
    return int(time.time() * 1000)


class UDPSessionServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_message=None):
        self.on_message = on_message
        self.transport = None
        self.peer_addr = None
        self.seq_received = {RELIABLE: set(), UNRELIABLE: set()}
        self.metrics = {
            RELIABLE: {
                "sent": 0,
                "received": 0,
                "rtts": deque(maxlen=1000),
                "bytes": 0,
                "jitter": 0.0,
            },
            UNRELIABLE: {
                "sent": 0,
                "received": 0,
                "rtts": deque(maxlen=1000),
                "bytes": 0,
                "jitter": 0.0,
            },
        }

    def connection_made(self, transport):
        self.transport = transport
        print("[SERVER] Listening for packets...")

    def datagram_received(self, data, addr):
        asyncio.create_task(self._handle_packet(data, addr))

    async def _handle_packet(self, data, addr):
        if len(data) < 11:
            return

        channel = data[0]
        seq_no = int.from_bytes(data[1:3], "big")
        timestamp = int.from_bytes(data[3:11], "big")
        payload = data[11:]
        self.peer_addr = addr

        # Acknowledge reliable packets
        if payload == b"ACK":
            # Ignore ACKs on server (they're from client)
            return

        now = current_millis()
        rtt_est = now - timestamp
        self.metrics[channel]["rtts"].append(rtt_est)
        self._update_jitter(channel, rtt_est)
        self.metrics[channel]["received"] += 1
        self.metrics[channel]["bytes"] += len(data)

        # ACK for reliable packets
        if channel == RELIABLE:
            ack_packet = (
                channel.to_bytes(1, "big")
                + seq_no.to_bytes(2, "big")
                + timestamp.to_bytes(8, "big")
                + b"ACK"
            )
            self.transport.sendto(ack_packet, addr)

        # Decode payload
        try:
            parsed = json.loads(payload.decode())
        except Exception:
            parsed = payload

        # Log
        print(
            f"[SERVER <- CLIENT] Seq={seq_no} "
            f"Type={'RELIABLE' if channel == RELIABLE else 'UNRELIABLE'} "
            f"Timestamp={timestamp} RTT={rtt_est} ms"
        )

        # Optional: echo the data back to client for testing
        await self.send_packet(parsed, reliable=(channel == RELIABLE))

        if self.on_message:
            await self.on_message(parsed, channel == RELIABLE, {"seq": seq_no})

    async def send_packet(self, data, reliable=True):
        if not self.peer_addr:
            return
        channel = RELIABLE if reliable else UNRELIABLE
        seq_no = int(time.time() * 1000) % 65536
        timestamp = current_millis()
        payload = json.dumps(data).encode()
        packet = (
            channel.to_bytes(1, "big")
            + seq_no.to_bytes(2, "big")
            + timestamp.to_bytes(8, "big")
            + payload
        )
        self.transport.sendto(packet, self.peer_addr)
        self.metrics[channel]["sent"] += 1
        self.metrics[channel]["bytes"] += len(packet)

    def _update_jitter(self, channel, new_rtt):
        m = self.metrics[channel]
        if len(m["rtts"]) < 2:
            return
        prev_rtt = list(m["rtts"])[-2]
        diff = abs(new_rtt - prev_rtt)
        m["jitter"] += (diff - m["jitter"]) / 16

    def report_metrics(self):
        print("\n=== SERVER Performance Report ===")
        for ch in (RELIABLE, UNRELIABLE):
            m = self.metrics[ch]
            avg_rtt = sum(m["rtts"]) / len(m["rtts"]) if m["rtts"] else 0
            throughput = m["bytes"] / max(len(m["rtts"]) / 1000, 1)
            pdr = (m["received"] / m["sent"] * 100) if m["sent"] > 0 else 0
            print(f"[{'RELIABLE' if ch == RELIABLE else 'UNRELIABLE'}]")
            print(f"  Avg RTT: {avg_rtt:.2f} ms")
            print(f"  Jitter: {m['jitter']:.2f} ms")
            print(f"  Throughput: {throughput:.2f} Bps")
            print(f"  Packet Delivery Ratio: {pdr:.2f}%")
        print("=================================\n")


async def main():
    loop = asyncio.get_running_loop()

    def factory():
        return UDPSessionServerProtocol()

    print("[SERVER] Starting UDP server on 127.0.0.1:9999")
    transport, proto = await loop.create_datagram_endpoint(
        factory, local_addr=("127.0.0.1", 9999)
    )

    try:
        while True:
            await asyncio.sleep(10)
            proto.report_metrics()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())

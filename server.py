import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from GameNetAPI import GameNetAPI

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class PacketInfo:
    seq_no: int
    channel: str  # "RELIABLE" or "UNRELIABLE"
    timestamp: float
    arrival_time: float
    delivery_time: float
    rtt_ms: float
    payload: dict
    out_of_order: bool = False


class Server:
    """H-QUIC receiver fully integrated with GameNetAPI."""

    def __init__(
        self, host="localhost", port=4433, certfile="cert.pem", keyfile="key.pem"
    ):
        # Initialize GameNetAPI in server mode
        self.api = GameNetAPI(
            is_client=False, host=host, port=port, certfile=certfile, keyfile=keyfile
        )
        # Set callbacks
        self.api.set_message_callback(self.on_message)
        self.api.set_connection_terminated_callback(self.on_disconnect)

        self.running = False
        self.delivered_packets: List[PacketInfo] = []

        self._print_header(host, port, certfile, keyfile)

    def _print_header(self, host, port, cert, key):
        print("\n" + "=" * 100)
        print("H-QUIC RECEIVER SERVER")
        print("=" * 100)
        print(f"Started:      {datetime.now():%Y-%m-%d %H:%M:%S}")
        print(f"Listening on: {host}:{port}")
        print(f"Certificate:  {cert}")
        print(f"Private Key:  {key}")
        print("=" * 100 + "\n")

    async def start(self):
        logger.info("Starting H-QUIC receiver...")
        self.running = True
        self.api.start_time = time.time()
        # Start GameNetAPI server as a background task
        self.server_task = asyncio.create_task(self.api.start_server())

    async def stop(self):
        self.running = False
        self.server_task.cancel()
        await self.api.close()
        logger.info("Receiver stopped.\n")

    # Message callback from GameNetAPI
    async def on_message(self, payload: dict, reliable: bool):
        seq_no = payload.get("seq_no", -1)
        timestamp = payload.get("timestamp", 0) / 1000.0

        metrics_data = self.api.track_packet_metrics(
            seq_no, timestamp, payload, reliable
        )
        delivery_time = time.time()

        # Increment delivered packets metric
        channel = "RELIABLE" if reliable else "UNRELIABLE"
        self.api.metrics[channel].packets_delivered += 1

        # Store delivered packet info
        self.delivered_packets.append(
            PacketInfo(
                seq_no=seq_no,
                channel=channel,
                timestamp=timestamp,
                arrival_time=metrics_data["arrival_time"],
                delivery_time=delivery_time,
                rtt_ms=metrics_data["rtt_ms"],
                payload=payload,
                out_of_order=metrics_data["out_of_order"],
            )
        )

    # Connection terminated callback
    async def on_disconnect(self):
        logger.info("\nClient disconnected — generating statistics...\n")
        out_of_order_count = sum(p.out_of_order for p in self.delivered_packets)
        self.api.print_statistics(
            delivered_packets_count=len(self.delivered_packets),
            out_of_order_count=out_of_order_count,
        )
        # Clear for next connection
        self.delivered_packets.clear()

    # Main loop
    async def run(self):
        await self.start()
        try:
            while self.running:
                await asyncio.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Shutting down server...")
        finally:
            await self.stop()


if __name__ == "__main__":
    print("CS3103 Assignment 4 - Adaptive Hybrid Transport Protocol (Server)")
    server = Server()
    asyncio.run(server.run())

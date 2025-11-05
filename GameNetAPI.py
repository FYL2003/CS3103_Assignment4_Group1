import asyncio
import json
import time
from collections import deque

RELIABLE = 1
UNRELIABLE = 0
RETRANSMISSION_TIMEOUT = 0.2


def current_millis():
    return int(time.time() * 1000)


from UDPClientProtocol import UDPSessionProtocol


# --------------------- Client Wrapper ---------------------
class GameNetAPI:
    """
    Minimal client API:
      - GameNetAPI()
      - set_message_callback(cb)
      - await connect()
      - await send(data, reliable=True)
      - await close()
    """

    def __init__(self, host="127.0.0.1", port=9999, t_threshold=RETRANSMISSION_TIMEOUT):
        self.host = host
        self.port = port
        self.t_threshold = t_threshold
        self.protocol = None
        self.transport = None
        self.connected = False
        self.on_message = None

    def set_message_callback(self, callback):
        """callback should be async def callback(data, reliable)"""
        self.on_message = callback

    async def connect(self):
        loop = asyncio.get_running_loop()

        def factory():
            return UDPSessionProtocol(
                is_client=True,
                on_message=self._on_message_wrapper,
                t_threshold=self.t_threshold,
            )

        transport, proto = await loop.create_datagram_endpoint(
            factory, remote_addr=(self.host, self.port)
        )
        self.transport = transport
        self.protocol = proto
        proto.set_peer((self.host, self.port))
        self.connected = True
        print(f"[CLIENT] connected to {self.host}:{self.port}")

    async def send(self, data: dict, reliable: bool = True):
        if not self.connected:
            raise RuntimeError("Not connected")
        await self.protocol.send_packet(data, reliable=reliable)

    async def close(self):
        if self.transport:
            self.transport.close()
        self.connected = False

    async def _on_message_wrapper(self, parsed, reliable, meta):
        if self.on_message:
            await self.on_message(parsed, reliable)

    def report_metrics(self):
        if not self.protocol:
            print("No metrics: not connected.")
            return
        results = self.protocol.get_metrics()
        print("\n=== Performance Report ===")
        for ch, vals in results.items():
            print(f"[{ch.upper()}]")
            for k, v in vals.items():
                print(f"  {k}: {v}")
        print("===========================\n")

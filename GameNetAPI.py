import asyncio
import json
import time
from aioquic.asyncio import connect
from aioquic.quic.configuration import QuicConfiguration

RELIABLE = 1
UNRELIABLE = 0

class GameNetAPI:
    def __init__(self, isClient=True, host="localhost", port=4433):
        self.is_client = isClient
        self.host = host
        self.port = port
        self.conn = None
        self._connect_ctx = None
        self.config = QuicConfiguration(is_client=isClient, alpn_protocols=["GameNetAPI"])
        self.config.verify_mode = False
        self.seq = {RELIABLE: 0, UNRELIABLE: 0}
        self.connected = False

    async def connect(self):
        if not self.is_client:
            raise RuntimeError("connect() should only be used in client mode")

        print(f"Connecting to {self.host}:{self.port} ...")
        self._connect_ctx = connect(self.host, self.port, configuration=self.config)
        self.conn = await self._connect_ctx.__aenter__()
        self.connected = True
        print("✅ Connected to QUIC server")

    async def send(self, data: dict, reliable: bool = True):
        if not self.connected:
            raise RuntimeError("Not connected — call connect() first")

        channel = RELIABLE if reliable else UNRELIABLE
        seq_no = self.seq[channel]
        timestamp = int(time.time() * 1000)

        payload = json.dumps(data)
        header = (
            channel.to_bytes(1, "big") +
            seq_no.to_bytes(2, "big") +
            timestamp.to_bytes(8, "big")
        )
        packet = header + payload.encode()

        if reliable:
            stream_id = self.conn._quic.get_next_available_stream_id()
            self.conn._quic.send_stream_data(stream_id, packet)
            print(f"[RELIABLE] Sent Seq {seq_no}: {payload}")
            print(f"Corresponding packet: {packet}")
        else:
            self.conn._quic.send_datagram_frame(packet)
            print(f"[UNRELIABLE] Sent Seq {seq_no}: {payload}")
            print(f"Corresponding packet: {packet}")

        self.seq[channel] += 1
        self.conn.transmit()

    async def close(self):
        if not self.connected:
            return
        print("Closing QUIC connection...")
        await self._connect_ctx.__aexit__(None, None, None)
        self.connected = False
        print("✅ Connection closed")

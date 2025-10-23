import asyncio
import json
import time
from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import StreamDataReceived, DatagramFrameReceived

RELIABLE = 1
UNRELIABLE = 0

class GameNetAPI:
    def __init__(self, isClient=True, host="localhost", port=4433, certfile=None, keyfile=None):
        self.is_client = isClient
        self.host = host
        self.port = port
        self.conn = None
        self._connect_ctx = None
        self.server = None
        self.connected = False
        self.seq = {RELIABLE: 0, UNRELIABLE: 0}
        self.incoming_queue = asyncio.Queue()

        # QUIC configuration
        self.config = QuicConfiguration(is_client=isClient, alpn_protocols=["GameNetAPI"])
        self.config.verify_mode = False
        if not isClient and certfile and keyfile:
            self.config.load_cert_chain(certfile, keyfile)
            self.config.max_datagram_frame_size = 65536

    # -------------------- Client Methods --------------------
    async def connect(self):
        if not self.is_client:
            raise RuntimeError("connect() only for client mode")

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

        payload_json = json.dumps(data)
        header = (
            channel.to_bytes(1, "big") +
            seq_no.to_bytes(2, "big") +
            timestamp.to_bytes(8, "big")
        )
        packet = header + payload_json.encode()

        if self.is_client:
            if reliable:
                stream_id = self.conn._quic.get_next_available_stream_id()
                self.conn._quic.send_stream_data(stream_id, packet)
            else:
                self.conn._quic.send_datagram_frame(packet)

            self.seq[channel] += 1
            self.conn.transmit()

        # Return structured log
        log_entry = {
            "seq_no": seq_no,
            "channel": "RELIABLE" if reliable else "UNRELIABLE",
            "timestamp": timestamp,
            "payload": data,
            "bytes": len(packet)
        }
        print(f"[{log_entry['channel']}] Sent Seq {seq_no}: {payload_json}")
        return log_entry

    # -------------------- Server Methods --------------------
    async def start(self):
        if self.is_client:
            raise RuntimeError("start() only for server mode")

        class ServerProtocol(QuicConnectionProtocol):
            def __init__(self, outer, quic):
                super().__init__(quic)
                self.outer = outer

            def quic_event_received(self, event):
                if isinstance(event, StreamDataReceived):
                    self.outer.incoming_queue.put_nowait((event.data, True))
                elif isinstance(event, DatagramFrameReceived):
                    self.outer.incoming_queue.put_nowait((event.data, False))

        self.server = await serve(
            self.host,
            self.port,
            configuration=self.config,
            create_protocol=lambda quic, **kwargs: ServerProtocol(self, quic)
        )
        self.connected = True
        print(f"🟢 GameNetAPI server listening on {self.host}:{self.port}")

    async def receive(self):
        """Return the next incoming packet: (payload_dict, reliable_flag)"""
        packet, reliable = await self.incoming_queue.get()

        # Parse header
        ch_flag = packet[0]
        seq_no = int.from_bytes(packet[1:3], "big")
        timestamp = int.from_bytes(packet[3:11], "big")
        payload = json.loads(packet[11:].decode())

        return {
            "seq_no": seq_no,
            "timestamp": timestamp,
            "payload": payload
        }, reliable

    # -------------------- Close --------------------
    async def close(self):
        if self.is_client and self.connected:
            print("Closing client connection...")
            await self._connect_ctx.__aexit__(None, None, None)
            self.connected = False
            print("✅ Client connection closed")
        elif not self.is_client and self.server:
            print("Closing server...")
            self.server.close()
            await self.server.wait_closed()
            self.connected = False
            print("✅ Server closed")

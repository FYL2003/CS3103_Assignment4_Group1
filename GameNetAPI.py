import asyncio
import json
import time

from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, DatagramFrameReceived
from aioquic.asyncio.protocol import QuicConnectionProtocol

from GameServerProtocol import GameServerProtocol, RETRANSMISSION_TIMEOUT

RELIABLE = 1
UNRELIABLE = 0

TIMESTAMP_BYTES = 8
RETRANSMIT_CHECK_INTERVAL = 0.05  # Check for retransmissions every 50ms

class GameClientProtocol(QuicConnectionProtocol):
    """Custom protocol for client to receive messages from server"""
    
    def __init__(self, *args, on_message=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_message = on_message
        self.seq = {RELIABLE: 0, UNRELIABLE: 0}
        self.pending_acks = {}  # seq_no -> (data, timestamp, retrans_count)
        self.retransmit_task = None
        
        # Start retransmission checker
        self.retransmit_task = asyncio.create_task(self._check_retransmit())

    def quic_event_received(self, event):
        """Handle incoming QUIC events (messages from server)"""
        if isinstance(event, StreamDataReceived):
            asyncio.create_task(self._handle_stream_data(event))
        elif isinstance(event, DatagramFrameReceived):
            asyncio.create_task(self._handle_datagram(event))

    async def _handle_stream_data(self, event):
        """Handle reliable stream data from server"""
        try:
            header_len = 1 + 2 + TIMESTAMP_BYTES
            if len(event.data) < header_len:
                return
            
            payload_bytes = event.data[header_len:]
            payload = json.loads(payload_bytes.decode())
            
            if self.on_message:
                await self.on_message(payload, reliable=True)
        except Exception as e:
            print(f"[CLIENT] Error handling stream data: {e}")

    async def _handle_datagram(self, event):
        """Handle unreliable datagram from server"""
        try:
            header_len = 1 + 2 + TIMESTAMP_BYTES
            if len(event.data) < header_len:
                return
            
            payload_bytes = event.data[header_len:]
            payload = json.loads(payload_bytes.decode())
            
            # Check if this is an ACK packet
            if isinstance(payload, dict) and payload.get("type") == "ACK":
                seq_no = payload.get("seq_no")
                if seq_no is not None and seq_no in self.pending_acks:
                    print(f"[ACK] Received ACK for Seq {seq_no}")
                    self.pending_acks.pop(seq_no)
                return
            
            if self.on_message:
                await self.on_message(payload, reliable=False)
        except Exception as e:
            print(f"[CLIENT] Error handling datagram: {e}")

    async def send_packet(self, data: dict, reliable: bool = True):
        """Send a packet to the server with proper seq and timestamp"""
        channel = RELIABLE if reliable else UNRELIABLE
        seq_no = self.seq[channel]
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
            
            # Track packet for ACK and potential retransmission
            self.pending_acks[seq_no] = (data, time.time(), 0)
        else:
            self._quic.send_datagram_frame(packet)
            print(f"[UNRELIABLE] Sent Seq {seq_no}: {payload}")

        self.seq[channel] += 1
        self.transmit()
    
    async def _check_retransmit(self):
        """Check for packets that need retransmission"""
        MAX_RETRANSMIT = 3  # Maximum retransmission attempts
        try:
            while True:
                await asyncio.sleep(RETRANSMIT_CHECK_INTERVAL)
                
                current_time = time.time()
                to_retransmit = []
                
                for seq_no, (data, sent_time, retrans_count) in list(self.pending_acks.items()):
                    elapsed = current_time - sent_time
                    if elapsed > RETRANSMISSION_TIMEOUT:
                        if retrans_count < MAX_RETRANSMIT:
                            to_retransmit.append((seq_no, data, retrans_count))
                        else:
                            # Give up after MAX_RETRANSMIT attempts
                            print(f"[RETRANSMIT] Giving up on Seq {seq_no} after {MAX_RETRANSMIT} attempts")
                            self.pending_acks.pop(seq_no)
                
                # Retransmit packets
                for seq_no, data, retrans_count in to_retransmit:
                    print(f"[RETRANSMIT] Retransmitting Seq {seq_no} (attempt {retrans_count + 1})")
                    timestamp = int(time.time() * 1000)
                    payload = json.dumps(data)
                    header = (
                        RELIABLE.to_bytes(1, "big")
                        + seq_no.to_bytes(2, "big")
                        + timestamp.to_bytes(TIMESTAMP_BYTES, "big")
                    )
                    packet = header + payload.encode()
                    
                    stream_id = self._quic.get_next_available_stream_id()
                    self._quic.send_stream_data(stream_id, packet, end_stream=True)
                    self.transmit()
                    
                    # Update tracking
                    self.pending_acks[seq_no] = (data, time.time(), retrans_count + 1)
                    
        except asyncio.CancelledError:
            pass  # Task was cancelled, exit gracefully

class GameNetAPI:
    def __init__(
        self, isClient=True, host="localhost", port=4433, certfile=None, keyfile=None
    ):
        self.is_client = isClient
        self.host = host
        self.port = port
        self.conn = None
        self._connect_ctx = None
        self.config = QuicConfiguration(
            is_client=isClient, alpn_protocols=["GameNetAPI"]
        )
        self.config.verify_mode = False
        self.seq = {RELIABLE: 0, UNRELIABLE: 0}
        self.connected = False
        self.on_message = None  # callback for received messages
        if not isClient:
            self.config.load_cert_chain(certfile=certfile, keyfile=keyfile)
        # enable datagram support
        if hasattr(self.config, "max_datagram_frame_size"):
            self.config.max_datagram_frame_size = 65536
        else:
            try:
                self.config.datagram_frame_size = 65536
            except Exception:
                pass

    async def connect(self):
        if not self.is_client:
            raise RuntimeError("connect() should only be used in client mode")

        print(f"Connecting to {self.host}:{self.port} ...")
        self._connect_ctx = connect(
            self.host,
            self.port,
            configuration=self.config,
            create_protocol=lambda *args, **kwargs: GameClientProtocol(
                *args, on_message=self.on_message, **kwargs
            ),
        )
        self.conn = await self._connect_ctx.__aenter__()
        self.connected = True
        print("Connected to QUIC server")

    async def send(self, data: dict, reliable: bool = True):
        if not self.connected:
            raise RuntimeError("Not connected — call connect() first")

        await self.conn.send_packet(data, reliable=reliable)

    async def close(self):
        if not self.connected:
            return
        print("Closing QUIC connection...")
        
        # Cancel retransmit task if it exists
        if hasattr(self.conn, 'retransmit_task') and self.conn.retransmit_task:
            if not self.conn.retransmit_task.done():
                self.conn.retransmit_task.cancel()
                try:
                    await self.conn.retransmit_task
                except asyncio.CancelledError:
                    pass
        
        await self._connect_ctx.__aexit__(None, None, None)
        self.connected = False
        print("Connection closed")

    def set_message_callback(self, callback):
        """Set callback for received messages.

        callback should be an async function taking (data: dict, reliable: bool)
        """
        self.on_message = callback

    async def start_server(self, create_protocol=None):
        """Start the QUIC server and wait for connections"""
        if self.is_client:
            raise RuntimeError("Server mode requires isClient=False")

        print(f"Starting QUIC server on {self.host}:{self.port} ...")

        # If no wrapper provided, use default
        if create_protocol is None:
            from GameServerProtocol import GameServerProtocol
            create_protocol = lambda *args, **kwargs: GameServerProtocol(
                *args, on_message=self.on_message, **kwargs
            )

        await serve(
            host=self.host,
            port=self.port,
            configuration=self.config,
            create_protocol=create_protocol,
        )

        print("Server running")
        await asyncio.Event().wait()

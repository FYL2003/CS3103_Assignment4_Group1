import asyncio
import json
import logging
import time

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import (
    ConnectionTerminated,
    DatagramFrameReceived,
    StreamDataReceived,
)

RELIABLE = 1
UNRELIABLE = 0

RETRANSMISSION_TIMEOUT = 0.2  # 200 ms default
TIMESTAMP_BYTES = 8

logger = logging.getLogger(__name__)


class GameServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, on_message=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reliable_buffer = {}  # seq_no -> (data, timestamp)
        self.expected_seq = 0  # next expected reliable seq
        self.next_ack_seq = 0  # seq for server -> client packets
        self.on_message = on_message  # callback for received messages
        self._timeout_task = None  # Task for checking packet timeouts
        self._expected_seq_time = None  # Time when we started waiting for expected_seq

    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            # schedule async handler
            asyncio.create_task(self._handle_packet(event.data, reliable=True))
            # Start timeout checker once (not on every packet)
            if self._timeout_task is None:
                self._timeout_task = asyncio.create_task(self._check_timeouts())
            if event.end_stream:
                # reset the stream if the peer closed it
                try:
                    self._quic.reset_stream(event.stream_id, 0)
                except Exception:
                    pass

        elif isinstance(event, DatagramFrameReceived):
            asyncio.create_task(self._handle_packet(event.data, reliable=False))

        elif isinstance(event, ConnectionTerminated):
            print("Connection terminated by client")
            # Cancel timeout task if running
            if self._timeout_task and not self._timeout_task.done():
                self._timeout_task.cancel()

    async def _handle_packet(self, packet: bytes, reliable: bool):
        # header: 1 byte channel | 2 bytes seq_no | 8 bytes timestamp
        header_len = 1 + 2 + TIMESTAMP_BYTES
        if len(packet) < header_len:
            print("Malformed packet received")
            return

        channel = packet[0]
        seq_no = int.from_bytes(packet[1:3], "big")
        timestamp = int.from_bytes(packet[3 : 3 + TIMESTAMP_BYTES], "big")
        payload_bytes = packet[3 + TIMESTAMP_BYTES :]

        try:
            data = json.loads(payload_bytes.decode())
        except Exception:
            print("Failed to decode JSON:", payload_bytes)
            return

        if reliable:
            # buffer and reorder
            self.reliable_buffer[seq_no] = (data, timestamp)
            # Initialize timer if this is the first packet we're waiting for
            if self._expected_seq_time is None and seq_no >= self.expected_seq:
                self._expected_seq_time = time.time()
            await self._deliver_reliable()
        else:
            # deliver immediately
            await self._deliver_packet(
                data, reliable=False, seq_no=seq_no, timestamp=timestamp
            )

    async def _check_timeouts(self):
        """
        Periodically check for packets that have exceeded RETRANSMISSION_TIMEOUT.
        Skip timed-out packets and deliver subsequent in-order packets.
        
        Per assignment requirement (e): "If any packet is lost and retransmission 
        is not reached by t milliseconds threshold, you should skip that packet 
        and display rest of the data."
        
        This method tracks when we start waiting for each expected packet.
        If a packet doesn't arrive within 200ms, it's considered lost and skipped.
        """
        try:
            while True:
                await asyncio.sleep(0.05)  # Check every 50ms
                
                current_time = time.time()
                
                # Only check timeout if we're actively waiting for a packet
                if self._expected_seq_time is None:
                    continue
                
                # Check if we've been waiting too long for expected packet
                elapsed_time = current_time - self._expected_seq_time
                
                if elapsed_time > RETRANSMISSION_TIMEOUT:
                    # Check if packet has arrived - if yes, deliver it instead of skipping
                    if self.expected_seq in self.reliable_buffer:
                        # Packet arrived but delivery was delayed - deliver it now
                        await self._deliver_reliable()
                    else:
                        # Packet never arrived - skip it
                        logger.warning(
                            f"Packet {self.expected_seq} timed out after {elapsed_time*1000:.1f}ms. "
                            f"Skipping and delivering subsequent packets."
                        )
                        
                        # Advance expected sequence number
                        self.expected_seq += 1
                        
                        # Reset timer for next expected packet
                        self._expected_seq_time = current_time
                        
                        # Try to deliver subsequent packets that arrived
                        await self._deliver_reliable()
        except asyncio.CancelledError:
            # Task cancelled during shutdown - normal behavior
            pass
        except Exception as e:
            logger.error(f"Error in timeout checker: {e}", exc_info=True)

    async def _deliver_reliable(self):
        # deliver all in-order packets
        while self.expected_seq in self.reliable_buffer:
            data, ts = self.reliable_buffer.pop(self.expected_seq)
            await self._deliver_packet(
                data, reliable=True, seq_no=self.expected_seq, timestamp=ts
            )
            self.expected_seq += 1
            # Reset timer for next expected packet
            self._expected_seq_time = time.time()

    async def _deliver_packet(self, data, reliable, seq_no, timestamp):
        """Deliver packet to application callback

        Formats the data as expected by ReceiverApplication:
        {
            'seq_no': int,
            'timestamp': float (in ms),
            'payload': dict (original data)
        }
        """
        rtt = int(time.time() * 1000) - timestamp
        print(
            f"{'[RELIABLE]' if reliable else '[UNRELIABLE]'} "
            f"Seq {seq_no} | Timestamp {timestamp} | RTT {rtt} ms | Data: {data}"
        )

        if self.on_message:
            # Format data as expected by ReceiverApplication
            formatted_data = {
                "seq_no": seq_no,
                "timestamp": timestamp,  # Original timestamp from sender
                "payload": data,  # Original data payload
            }
            try:
                await self.on_message(formatted_data, reliable, self)
            except Exception as e:
                print(f"Error in message callback: {e}")

    async def send_packet(self, data: dict, reliable: bool = True):
        """Send a packet to the client with proper seq and timestamp."""
        channel_byte = (0 if not reliable else 1).to_bytes(1, "big")
        seq_no = self.next_ack_seq if reliable else 0
        seq_bytes = seq_no.to_bytes(2, "big")
        timestamp = int(time.time() * 1000)
        ts_bytes = timestamp.to_bytes(TIMESTAMP_BYTES, "big")
        payload_bytes = json.dumps(data).encode()
        packet = channel_byte + seq_bytes + ts_bytes + payload_bytes

        if reliable:
            # send over a new QUIC stream for guaranteed delivery
            stream_id = self._quic.get_next_available_stream_id()
            self._quic.send_stream_data(stream_id, packet, end_stream=True)
            self.next_ack_seq = (self.next_ack_seq + 1) % 65536
        else:
            self._quic.send_datagram_frame(packet)

        self.transmit()
        print(f"[SERVER-SEND] Seq {seq_no} | Reliable={reliable} | Data: {data}")
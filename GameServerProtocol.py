import asyncio
import json
import time
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.events import (
    ConnectionTerminated,
    DatagramFrameReceived,
    StreamDataReceived,
)

RELIABLE = 1
UNRELIABLE = 0
TIMESTAMP_BYTES = 8

class GameServerProtocol(QuicConnectionProtocol):
    # -------------------- Initialization --------------------
    def __init__(self, *args, on_message=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reliable_buffer = {}           # seq_no -> packet
        self.expected_seq = 0               # next expected reliable seq
        self.next_ack_seq = 0               # seq for server -> client packets
        self.on_message = on_message        # callback for received messages
        self.reliable_seq_largest = 0
        self.unreliable_seq_largest = 0
        # Metrics
        self.metrics = {
            RELIABLE: {
                "packets_received": 0,
                "last_proper_seq": 0,
                "last_rtt": None,
                "rtt_samples": [],
                "jitter_samples": [],
                "bytes_received": 0,
                "start_time": None,
            },
            UNRELIABLE: {
                "packets_received": 0,
                "last_proper_seq": 0,
                "last_rtt": None,
                "rtt_samples": [],
                "jitter_samples": [],
                "bytes_received": 0,
                "start_time": None,
            },
        }

    # -------------------- Event Handling --------------------
    def quic_event_received(self, event):
        if isinstance(event, StreamDataReceived):
            asyncio.create_task(self._handle_packet(event.data, reliable=True))
            if event.end_stream:
                try:
                    self._quic.reset_stream(event.stream_id, 0)
                except Exception:
                    pass
        elif isinstance(event, DatagramFrameReceived):
            asyncio.create_task(self._handle_packet(event.data, reliable=False))
        elif isinstance(event, ConnectionTerminated):
            print("Connection terminated by client")

    # -------------------- Packet Handling --------------------
    async def _handle_packet(self, packet: bytes, reliable: bool):
        header_len = 1 + 2 + TIMESTAMP_BYTES
        if len(packet) < header_len:
            print("Malformed packet received")
            return

        channel = packet[0]
        seq_no = int.from_bytes(packet[1:3], "big")
        timestamp = int.from_bytes(packet[3:3 + TIMESTAMP_BYTES], "big")
        payload_bytes = packet[3 + TIMESTAMP_BYTES:]

        try:
            data = json.loads(payload_bytes.decode())
        except Exception:
            print("Failed to decode JSON:", payload_bytes)
            return

        # Update metrics
        if reliable:
            self.reliable_buffer[seq_no] = (data, timestamp)
            self.reliable_seq_largest = max(self.reliable_seq_largest, seq_no)
            await self._deliver_reliable()
            self._update_metrics(channel, len(packet), timestamp)
        else:
            self.unreliable_seq_largest = max(self.unreliable_seq_largest, seq_no)
            await self._deliver_packet(data, reliable=False, seq_no=seq_no, timestamp=timestamp)
            self._update_metrics(channel, len(packet), timestamp)

    async def _deliver_reliable(self):
        while self.expected_seq in self.reliable_buffer:
            data, ts = self.reliable_buffer.pop(self.expected_seq)
            await self._deliver_packet(data, reliable=True, seq_no=self.expected_seq, timestamp=ts)
            self.expected_seq += 1

    async def _deliver_packet(self, data, reliable, seq_no, timestamp):
        rtt = int(time.time() * 1000) - timestamp
        print(f"{'[RELIABLE]' if reliable else '[UNRELIABLE]'} "
              f"Seq {seq_no} | Timestamp {timestamp} | RTT {rtt} ms | Data: {data}")

        self.metrics[RELIABLE if reliable else UNRELIABLE]["last_rtt"] = rtt

        # Send an ACK back to the client
        # We create a task so we don't block the delivery pipeline
        response_payload = {
            "ack": "received",
            "seq_echo": seq_no
        }
        asyncio.create_task(self.send_packet(response_payload, reliable=reliable))

        # update only if seq_no is higher than previous highest, may be out of order
        self.metrics[RELIABLE]["last_proper_seq"] = max(self.metrics[RELIABLE]["last_proper_seq"], seq_no)
        self.metrics[UNRELIABLE]["last_proper_seq"] = max(self.metrics[UNRELIABLE]["last_proper_seq"], seq_no)

        if self.on_message:
            formatted_data = {
                "seq_no": seq_no,
                "timestamp": timestamp,
                "payload": data,
            }
            try:
                await self.on_message(formatted_data, reliable, self)
            except Exception as e:
                print(f"Error in message callback: {e}")

    # -------------------- Sending Packets --------------------
    async def send_packet(self, data: dict, reliable: bool = True):
        channel_byte = (1 if reliable else 0).to_bytes(1, "big")
        seq_no = self.next_ack_seq if reliable else 0
        seq_bytes = seq_no.to_bytes(2, "big")
        timestamp = int(time.time() * 1000)
        ts_bytes = timestamp.to_bytes(TIMESTAMP_BYTES, "big")
        payload_bytes = json.dumps(data).encode()
        packet = channel_byte + seq_bytes + ts_bytes + payload_bytes

        if reliable:
            stream_id = self._quic.get_next_available_stream_id()
            self._quic.send_stream_data(stream_id, packet, end_stream=True)
            self.next_ack_seq = (self.next_ack_seq + 1) % 65536
        else:
            self._quic.send_datagram_frame(packet)

        self.transmit()
        print(f"[SERVER-SEND] Seq {seq_no} | Reliable={reliable} | Data: {data}")

    # -------------------- Metrics --------------------
    def _update_metrics(self, channel, packet_size, timestamp):
        ch_metrics = self.metrics[channel]

        if ch_metrics["start_time"] is None:
            ch_metrics["start_time"] = time.time()

        ch_metrics["packets_received"] += 1
        ch_metrics["bytes_received"] += packet_size

        # Jitter calculation
        last_rtt = ch_metrics["last_rtt"]
        rtt = int(time.time() * 1000) - timestamp
        ch_metrics["rtt_samples"].append(rtt)
        if last_rtt is not None:
            ch_metrics["jitter_samples"].append(abs(rtt - last_rtt))

    def print_statistics(self):

        print("\nOVERALL STATISTICS:")
        for channel, name in [(RELIABLE, "RELIABLE"), (UNRELIABLE, "UNRELIABLE")]:
            ch_metrics = self.metrics[channel]

            if ch_metrics["packets_received"] == 0:
                print(f"[{name}] No packets received yet.")
                continue

            duration = max(time.time() - ch_metrics["start_time"], 1e-6)
            throughput = ch_metrics["bytes_received"] / duration

            if channel is RELIABLE:
                pdr = (ch_metrics["packets_received"] / (self.reliable_seq_largest + 1)) * 100
            else:
                pdr = (ch_metrics["packets_received"] / (self.unreliable_seq_largest + 1)) * 100


            last_rtt = ch_metrics["last_rtt"]
            avg_jitter = sum(ch_metrics["jitter_samples"]) / len(ch_metrics["jitter_samples"]) if ch_metrics["jitter_samples"] else 0

            print(
                f"[{name} Metrics] "
                f"Packets Received: {ch_metrics['packets_received']}, "
                f"Largest Seen Sequence Number: {self.reliable_seq_largest if channel is RELIABLE else self.unreliable_seq_largest}"
                f"Throughput: {throughput:.2f} Bps, "
                f"PDR: {pdr:.2f}%, "
                f"Last RTT: {last_rtt} ms, "
                f"Avg Jitter: {avg_jitter:.2f} ms"
            )

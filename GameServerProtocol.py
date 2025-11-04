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
RETRANSMISSION_TIMEOUT = 0.2  # 200 ms default
TIMEOUT_CHECK_INTERVAL = 0.01  # Check for timeouts every 10ms

class GameServerProtocol(QuicConnectionProtocol):
    # -------------------- Initialization --------------------
    def __init__(self, *args, on_message=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.reliable_buffer = {}           # seq_no -> (data, timestamp, arrival_time)
        self.expected_seq = 0               # next expected reliable seq
        self.next_ack_seq = 0               # seq for server -> client packets
        self.on_message = on_message        # callback for received messages
        self.timeout_task = None            # task for checking timeouts
        self.skipped_packets = set()        # track skipped packet sequence numbers

        # Metrics
        self.metrics = {
            RELIABLE: {
                "packets_received": 0,
                "packets_sent": 0,
                "last_rtt": None,
                "rtt_samples": [],
                "jitter_samples": [],
                "bytes_received": 0,
                "start_time": None,
                "packets_skipped": 0,
            },
            UNRELIABLE: {
                "packets_received": 0,
                "packets_sent": 0,
                "last_rtt": None,
                "rtt_samples": [],
                "jitter_samples": [],
                "bytes_received": 0,
                "start_time": None,
            },
        }
        
        # Start timeout checker task
        self.timeout_task = asyncio.create_task(self._check_timeouts())

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
            if self.timeout_task:
                self.timeout_task.cancel()

    # -------------------- Packet Handling --------------------
    async def _handle_packet(self, packet: bytes, reliable: bool):
        header_len = 1 + 2 + TIMESTAMP_BYTES
        if len(packet) < header_len:
            print("Malformed packet received")
            return

        channel = packet[0]
        seq_no = int.from_bytes(packet[1:3], "big")
        timestamp = int.from_bytes(packet[3:3+TIMESTAMP_BYTES], "big")
        payload_bytes = packet[3+TIMESTAMP_BYTES:]

        try:
            data = json.loads(payload_bytes.decode())
        except Exception:
            print("Failed to decode JSON:", payload_bytes)
            return

        # Update metrics
        self._update_metrics(channel, len(packet), timestamp)

        if reliable:
            arrival_time = time.time()
            self.reliable_buffer[seq_no] = (data, timestamp, arrival_time)
            
            # Send ACK immediately for received packet
            await self._send_ack(seq_no)
            
            await self._deliver_reliable()
        else:
            await self._deliver_packet(data, reliable=False, seq_no=seq_no, timestamp=timestamp)
    
    async def _send_ack(self, seq_no: int):
        """Send ACK packet to client for received reliable packet"""
        ack_data = {"type": "ACK", "seq_no": seq_no}
        await self.send_packet(ack_data, reliable=False)

    async def _deliver_reliable(self):
        """Deliver reliable packets in order, respecting skipped packets"""
        while self.expected_seq in self.reliable_buffer or self.expected_seq in self.skipped_packets:
            if self.expected_seq in self.skipped_packets:
                # Skip this sequence number as it timed out
                print(f"[RELIABLE] Skipping timed-out packet Seq {self.expected_seq}")
                self.expected_seq += 1
                continue
                
            if self.expected_seq in self.reliable_buffer:
                data, ts, arrival_time = self.reliable_buffer.pop(self.expected_seq)
                await self._deliver_packet(data, reliable=True, seq_no=self.expected_seq, timestamp=ts)
                self.expected_seq += 1

    async def _deliver_packet(self, data, reliable, seq_no, timestamp):
        rtt = int(time.time() * 1000) - timestamp
        print(f"{'[RELIABLE]' if reliable else '[UNRELIABLE]'} "
              f"Seq {seq_no} | Timestamp {timestamp} | RTT {rtt} ms | Data: {data}")

        self.metrics[RELIABLE if reliable else UNRELIABLE]["last_rtt"] = rtt

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
    
    async def _check_timeouts(self):
        """Periodically check for timed-out packets and skip them"""
        try:
            while True:
                await asyncio.sleep(TIMEOUT_CHECK_INTERVAL)
                
                current_time = time.time()
                timed_out_seqs = []
                
                # Check if expected packet is missing and if any buffered packets timed out
                for seq_no, (data, timestamp, arrival_time) in list(self.reliable_buffer.items()):
                    elapsed = current_time - arrival_time
                    if elapsed > RETRANSMISSION_TIMEOUT:
                        timed_out_seqs.append(seq_no)
                
                # Also check if we're waiting for expected_seq too long
                # If we have buffered packets beyond expected_seq and expected_seq is missing
                if self.reliable_buffer:
                    min_buffered_seq = min(self.reliable_buffer.keys())
                    if min_buffered_seq > self.expected_seq:
                        # We're waiting for expected_seq but have later packets
                        # Check if the earliest buffered packet has been waiting too long
                        _, _, earliest_arrival = self.reliable_buffer[min_buffered_seq]
                        if current_time - earliest_arrival > RETRANSMISSION_TIMEOUT:
                            # Skip expected_seq as it's missing and timeout exceeded
                            print(f"[TIMEOUT] Skipping missing packet Seq {self.expected_seq} after {RETRANSMISSION_TIMEOUT*1000}ms")
                            self.skipped_packets.add(self.expected_seq)
                            self.metrics[RELIABLE]["packets_skipped"] += 1
                            await self._deliver_reliable()
                
                # Mark timed-out buffered packets
                for seq_no in timed_out_seqs:
                    print(f"[TIMEOUT] Packet Seq {seq_no} timed out after {RETRANSMISSION_TIMEOUT*1000}ms")
                    self.reliable_buffer.pop(seq_no, None)
                    
        except asyncio.CancelledError:
            pass  # Task was cancelled, exit gracefully

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
        self.metrics[RELIABLE if reliable else UNRELIABLE]["packets_sent"] += 1
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
        for channel, name in [(RELIABLE, "RELIABLE"), (UNRELIABLE, "UNRELIABLE")]:
            ch_metrics = self.metrics[channel]
            if ch_metrics["packets_received"] == 0:
                print(f"[{name}] No packets received yet.")
                continue
            duration = max(time.time() - ch_metrics["start_time"], 1e-6)
            throughput = ch_metrics["bytes_received"] / duration
            pdr = (
                ch_metrics["packets_received"] / ch_metrics["packets_sent"] * 100
                if ch_metrics["packets_sent"] > 0 else 100.0
            )
            last_rtt = ch_metrics["last_rtt"]
            avg_jitter = sum(ch_metrics["jitter_samples"]) / len(ch_metrics["jitter_samples"]) if ch_metrics["jitter_samples"] else 0
            
            stats = (
                f"[{name} Metrics] "
                f"Packets Received: {ch_metrics['packets_received']}, "
                f"Packets Sent: {ch_metrics['packets_sent']}, "
                f"Throughput: {throughput:.2f} Bps, "
                f"PDR: {pdr:.2f}%, "
                f"Last RTT: {last_rtt} ms, "
                f"Avg Jitter: {avg_jitter:.2f} ms"
            )
            
            if channel == RELIABLE and "packets_skipped" in ch_metrics:
                stats += f", Packets Skipped: {ch_metrics['packets_skipped']}"
            
            print(stats)

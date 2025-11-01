import asyncio
import json
import time
from typing import Callable, Dict, Optional, Tuple

from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration

from ChannelMetrics import ChannelMetrics
from GameServerProtocol import GameServerProtocol
from generate_cert import ensure_certificates

RELIABLE = 1
UNRELIABLE = 0
RETRANSMISSION_TIMEOUT = 0.2  # 200 ms default


class GameNetAPI:
    def __init__(
        self, is_client=True, host="localhost", port=4433, certfile=None, keyfile=None
    ):
        self.is_client = is_client
        self.host = host
        self.port = port
        self.conn = None
        self._connect_ctx = None

        # QUIC configuration
        self.config = QuicConfiguration(
            is_client=is_client, alpn_protocols=["GameNetAPI"]
        )
        self.config.verify_mode = False
        if not is_client:
            self.config.idle_timeout = 30.0

        # Callbacks
        self.on_message: Optional[Callable[[dict, bool], asyncio.Future]] = None
        self.on_connection_terminated: Optional[Callable[[], asyncio.Future]] = None

        # Sequence numbers
        self.seq = {RELIABLE: 0, UNRELIABLE: 0}

        # Server metrics
        if not is_client:
            self.metrics = {
                "RELIABLE": ChannelMetrics(),
                "UNRELIABLE": ChannelMetrics(),
            }
            self.start_time: Optional[float] = None
            self.total_arrivals: int = 0
            self.last_packet_time: Optional[float] = None
            certfile, keyfile = self._ensure_certificates(certfile, keyfile)
            self.config.load_cert_chain(certfile=certfile, keyfile=keyfile)

        # Datagram support
        if hasattr(self.config, "max_datagram_frame_size"):
            self.config.max_datagram_frame_size = 65536
        else:
            try:
                self.config.datagram_frame_size = 65536
            except Exception:
                pass

        # Reliable packet tracking
        self.reliable_send_buffer: Dict[int, Dict] = (
            {}
        )  # seq -> {"packet", "timestamp", "payload"}
        self.next_reliable_seq = 0
        self.reliable_receive_buffer: Dict[int, Tuple[dict, float]] = {}
        self.next_expected_seq = 0
        self.retransmission_task = None
        self.connected = False

    def _ensure_certificates(self, certfile, keyfile):
        return ensure_certificates(certfile, keyfile)

    # ----------------------- CONNECTION -----------------------
    async def connect(self):
        if not self.is_client:
            raise RuntimeError("connect() only for client")
        self._connect_ctx = connect(self.host, self.port, configuration=self.config)
        self.conn = await self._connect_ctx.__aenter__()
        self.connected = True
        self.retransmission_task = asyncio.create_task(self._retransmission_loop())
        print(f"Connected to QUIC server {self.host}:{self.port}")

    async def start_server(self):
        if self.is_client:
            raise RuntimeError("start_server() only for server")
        await serve(
            host=self.host,
            port=self.port,
            configuration=self.config,
            create_protocol=lambda *args, **kwargs: GameServerProtocol(
                *args,
                on_message=self.on_message,
                on_connection_terminated=self.on_connection_terminated,
                **kwargs,
            ),
        )
        print(f"Server running on {self.host}:{self.port}")
        await asyncio.Event().wait()

    # ----------------------- SENDING -----------------------
    async def send(self, data: dict, reliable: bool = True):
        if not self.connected:
            raise RuntimeError("Not connected")
        if reliable:
            await self._send_reliable(data)
        else:
            await self._send_unreliable(data)

    async def _send_reliable(self, data: dict):
        seq_no = self.next_reliable_seq
        timestamp = int(time.time() * 1000)

        # Include seq_no and timestamp in payload
        data_to_send = data.copy()
        data_to_send["seq_no"] = seq_no
        data_to_send["timestamp"] = timestamp

        payload = json.dumps(data_to_send)

        # Build header (still keep for protocol)
        header = (
            RELIABLE.to_bytes(1, "big")
            + seq_no.to_bytes(2, "big")
            + timestamp.to_bytes(8, "big")
        )
        packet_bytes = header + payload.encode()

        # Buffer packet for retransmission
        self.reliable_send_buffer[seq_no] = {
            "packet": packet_bytes,
            "timestamp": time.time(),
            "payload": payload,
        }

        # Send packet
        stream_id = self.conn._quic.get_next_available_stream_id()
        self.conn._quic.send_stream_data(stream_id, packet_bytes)
        self.conn.transmit()
        print(f"[RELIABLE] Sent seq {seq_no}: {payload}")
        self.next_reliable_seq += 1

    async def _send_unreliable(self, data: dict):
        seq_no = self.seq[UNRELIABLE]
        timestamp = int(time.time() * 1000)
        payload = json.dumps(data)
        header = (
            UNRELIABLE.to_bytes(1, "big")
            + seq_no.to_bytes(2, "big")
            + timestamp.to_bytes(8, "big")
        )
        packet_bytes = header + payload.encode()
        self.conn._quic.send_datagram_frame(packet_bytes)
        self.conn.transmit()
        print(f"[UNRELIABLE] Sent seq {seq_no}: {payload}")
        self.seq[UNRELIABLE] += 1

    # ----------------------- RETRANSMISSION -----------------------

    async def _check_retransmissions(self):
        now = time.time()
        for seq_no, (packet_bytes, sent_time) in list(
            self.reliable_send_buffer.items()
        ):
            if now - sent_time > RETRANSMISSION_TIMEOUT:
                print(f"[RELIABLE] Skipping seq {seq_no} after timeout")
                del self.reliable_send_buffer[seq_no]  # remove from buffer
                # Optionally notify receiver that this packet is skipped

    async def _retransmission_loop(self):
        while self.connected:
            await self._check_retransmissions()
            await asyncio.sleep(0.05)

    # ----------------------- RECEIVING -----------------------
    async def on_receive_packet(self, packet_bytes: bytes):
        channel = packet_bytes[0]
        seq_no = int.from_bytes(packet_bytes[1:3], "big")
        payload = json.loads(packet_bytes[11:])

        if channel == RELIABLE:
            self.reliable_receive_buffer[seq_no] = (payload, time.time())
            await self._send_ack(seq_no)
            await self._deliver_in_order()
        elif channel == UNRELIABLE and self.on_message:
            await self.on_message(payload, False)

    async def _send_ack(self, seq_no: int):
        ack_packet = json.dumps({"ack": seq_no})
        stream_id = self.conn._quic.get_next_available_stream_id()
        self.conn._quic.send_stream_data(stream_id, ack_packet.encode())
        self.conn.transmit()

    async def _deliver_in_order(self):
        now = time.time()
        while True:
            entry = self.reliable_receive_buffer.get(self.next_expected_seq)
            if entry is None:
                # Check for missing packets exceeding timeout
                missing_seqs = [
                    s
                    for s in self.reliable_receive_buffer.keys()
                    if s > self.next_expected_seq
                ]
                if missing_seqs:
                    first_missing = min(missing_seqs)
                    payload, arrival_time = self.reliable_receive_buffer.get(
                        first_missing, (None, now)
                    )
                    if now - arrival_time > RETRANSMISSION_TIMEOUT:
                        print(
                            f"[RELIABLE] Skipping missing seq {self.next_expected_seq}"
                        )
                        self.next_expected_seq = first_missing
                        continue
                break
            payload, _ = self.reliable_receive_buffer.pop(self.next_expected_seq)
            if self.on_message:
                await self.on_message(payload, True)
            self.next_expected_seq += 1

    async def on_receive_ack(self, ack_packet_bytes: bytes):
        ack_data = json.loads(ack_packet_bytes)
        seq_no = ack_data.get("ack")
        if seq_no is not None and seq_no in self.reliable_send_buffer:
            print(f"[RELIABLE] Received ACK for seq {seq_no}")
            del self.reliable_send_buffer[seq_no]  # stop retransmission

    # ----------------------- CONNECTION CLOSE -----------------------
    async def close(self):
        if not self.connected:
            return
        if self.retransmission_task:
            self.retransmission_task.cancel()
        await self._connect_ctx.__aexit__(None, None, None)
        self.connected = False
        print("Connection closed")

    # ----------------------- CALLBACKS -----------------------
    def set_message_callback(self, callback: Callable[[dict, bool], asyncio.Future]):
        self.on_message = callback

    def set_connection_terminated_callback(
        self, callback: Callable[[], asyncio.Future]
    ):
        self.on_connection_terminated = callback

    # Metrics & statistics (server only)
    def track_packet_metrics(
        self, seq_no: int, timestamp: float, payload: dict, reliable: bool
    ) -> dict:
        if self.is_client:
            raise RuntimeError("track_packet_metrics() only for server mode")

        arrival_time = time.time()
        self.total_arrivals += 1
        self.last_packet_time = arrival_time
        channel = "RELIABLE" if reliable else "UNRELIABLE"
        metrics = self.metrics[channel]

        if metrics.start_time is None:
            metrics.start_time = arrival_time

        rtt_ms = (arrival_time - timestamp) * 1000
        metrics.add_rtt(rtt_ms)
        metrics.packets_received += 1
        metrics.received_seqs.add(seq_no)
        if seq_no > metrics.highest_seq:
            metrics.highest_seq = seq_no
        metrics.check_and_cleanup_seqs()

        payload_bytes = len(json.dumps(payload).encode())
        metrics.bytes_received += payload_bytes
        out_of_order = seq_no <= metrics.last_seq and metrics.last_seq >= 0
        if not out_of_order:
            metrics.last_seq = seq_no

        return {
            "arrival_time": arrival_time,
            "rtt_ms": rtt_ms,
            "out_of_order": out_of_order,
            "channel": channel,
        }

    def get_statistics_summary(self, delivered_packets_count: int = 0) -> dict:
        """
        Get comprehensive statistics summary for both channels

        Args:
            delivered_packets_count: Total number of packets delivered to application

        Returns:
            Dictionary containing statistics for both channels
        """
        runtime = time.time() - self.start_time if self.start_time else 0

        summary = {
            "runtime": runtime,
            "total_arrivals": self.total_arrivals,
            "total_delivered": delivered_packets_count,
            "channels": {},
        }

        for channel_name in ["RELIABLE", "UNRELIABLE"]:
            metrics = self.metrics[channel_name]
            channel_stats = {
                "packets_received": metrics.packets_received,
                "packets_delivered": metrics.packets_delivered,
                "bytes_received": metrics.bytes_received,
            }

            if metrics.rtts:
                channel_stats["latency"] = {
                    "avg_rtt": metrics.avg_rtt,
                    "min_rtt": metrics.min_rtt,
                    "max_rtt": metrics.max_rtt,
                }

                channel_stats["jitter"] = {
                    "avg_jitter": metrics.avg_jitter,
                }
                if metrics.jitter_samples:
                    channel_stats["jitter"]["min_jitter"] = min(metrics.jitter_samples)
                    channel_stats["jitter"]["max_jitter"] = max(metrics.jitter_samples)

                channel_stats["throughput"] = {
                    "kbps": metrics.throughput_kbps,
                    "KBps": metrics.throughput_kbps / 8,
                }

                # Calculate PDR (Packet Delivery Ratio)
                # PDR = (Packets Received / Expected Packets) * 100%
                pdr = metrics.calculate_pdr()
                channel_stats["packet_delivery_ratio"] = pdr
                channel_stats["expected_packets"] = (
                    metrics.highest_seq + 1 if metrics.highest_seq >= 0 else 0
                )

            summary["channels"][channel_name] = channel_stats

        # Calculate total throughput
        total_bytes = sum(m.bytes_received for m in self.metrics.values())
        if runtime > 0:
            summary["total_throughput_kbps"] = (total_bytes * 8) / (runtime * 1000)
        else:
            summary["total_throughput_kbps"] = 0

        return summary

    def print_statistics(
        self, delivered_packets_count: int = 0, out_of_order_count: int = 0
    ):
        """
        Print comprehensive statistics report

        Satisfies assignment requirement (i): Measure performance metrics
        including latency, jitter, throughput, and packet delivery ratio

        Args:
            delivered_packets_count: Total number of packets delivered to application
            out_of_order_count: Number of out-of-order packets received
        """
        stats = self.get_statistics_summary(delivered_packets_count)
        runtime = stats["runtime"]

        print("")
        print("=" * 100)
        print("H-QUIC RECEIVER STATISTICS")
        print("=" * 100)

        # Overall statistics
        print(f"\n{'OVERALL STATISTICS':^100}")
        print("-" * 100)
        print(f"  Total Runtime:              {runtime:.2f} seconds")
        print(f"  Total Packets Received:     {stats['total_arrivals']}")
        print(f"  Total Packets Delivered:    {stats['total_delivered']}")

        # Calculate total throughput
        total_bytes = sum(m.bytes_received for m in self.metrics.values())
        print(f"  Total Bytes Received:       {total_bytes:,} bytes")
        print(
            f"  Overall Throughput:         {stats['total_throughput_kbps']:.2f} Kbps"
        )

        # Channel-specific statistics
        print(f"\n{'CHANNEL-SPECIFIC STATISTICS':^100}")
        print("-" * 100)

        for channel_name in ["RELIABLE", "UNRELIABLE"]:
            channel_stats = stats["channels"][channel_name]

            print(f"\n  {channel_name} Channel:")
            print(f"    Packets Received:         {channel_stats['packets_received']}")
            print(f"    Packets Delivered:        {channel_stats['packets_delivered']}")
            print(
                f"    Bytes Received:           {channel_stats['bytes_received']:,} bytes"
            )

            if "latency" in channel_stats:
                print(f"\n    Latency (RTT):")
                print(
                    f"      Average:                {channel_stats['latency']['avg_rtt']:.2f} ms"
                )
                print(
                    f"      Minimum:                {channel_stats['latency']['min_rtt']:.2f} ms"
                )
                print(
                    f"      Maximum:                {channel_stats['latency']['max_rtt']:.2f} ms"
                )

                print(f"\n    Jitter (RFC 3550):")
                print(
                    f"      Average:                {channel_stats['jitter']['avg_jitter']:.2f} ms"
                )
                if "min_jitter" in channel_stats["jitter"]:
                    print(
                        f"      Minimum:                {channel_stats['jitter']['min_jitter']:.2f} ms"
                    )
                    print(
                        f"      Maximum:                {channel_stats['jitter']['max_jitter']:.2f} ms"
                    )

                print(f"\n    Throughput:")
                print(
                    f"      Rate:                   {channel_stats['throughput']['kbps']:.2f} Kbps"
                )
                print(
                    f"      Rate:                   {channel_stats['throughput']['KBps']:.2f} KBps"
                )

                if "packet_delivery_ratio" in channel_stats:
                    expected = channel_stats.get("expected_packets", 0)
                    print(f"\n    Packet Delivery:")
                    print(f"      Expected Packets:       {expected}")
                    print(
                        f"      Received Packets:       {channel_stats['packets_received']}"
                    )
                    print(
                        f"      Delivery Ratio:         {channel_stats['packet_delivery_ratio']:.2f}%"
                    )

        # Out-of-order statistics
        print(f"\n{'ORDERING STATISTICS':^100}")
        print("-" * 100)
        print(f"  Out-of-Order Packets:       {out_of_order_count}")
        print(
            f"  In-Order Packets:           {delivered_packets_count - out_of_order_count}"
        )

        print("=" * 100)

        # Reset metrics after displaying statistics to prepare for next connection
        self.reset_all_metrics()

    def reset_all_metrics(self):
        """Reset all metrics across all channels - called after statistics display"""
        if not self.is_client and hasattr(self, "metrics"):
            for channel_metrics in self.metrics.values():
                channel_metrics.reset_metrics()
            self.start_time = None
            self.total_arrivals = 0
            self.last_packet_time = None

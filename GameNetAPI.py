import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import List, Optional

from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration

from GameServerProtocol import GameServerProtocol

RELIABLE = 1
UNRELIABLE = 0

RETRANSMISSION_TIMEOUT = 0.2  # 200 ms default
TIMESTAMP_BYTES = 8


# -------------------- Metrics Classes --------------------
@dataclass
class ChannelMetrics:
    """Metrics for a single channel (reliable or unreliable)"""

    packets_received: int = 0
    packets_delivered: int = 0
    bytes_received: int = 0
    rtts: List[float] = field(default_factory=list)
    jitter_samples: List[float] = field(default_factory=list)
    last_rtt: Optional[float] = None
    start_time: Optional[float] = None
    last_seq: int = -1
    highest_seq: int = -1  # Track highest sequence number seen
    received_seqs: set = field(default_factory=set)  # Track all received sequence numbers

    def add_rtt(self, rtt_ms: float):
        """Add RTT sample and calculate jitter (RFC 3550)"""
        self.rtts.append(rtt_ms)

        if self.last_rtt is not None:
            jitter = abs(rtt_ms - self.last_rtt)
            self.jitter_samples.append(jitter)

        self.last_rtt = rtt_ms

    @property
    def avg_rtt(self) -> float:
        """Average RTT in milliseconds"""
        return sum(self.rtts) / len(self.rtts) if self.rtts else 0.0

    @property
    def min_rtt(self) -> float:
        """Minimum RTT in milliseconds"""
        return min(self.rtts) if self.rtts else 0.0

    @property
    def max_rtt(self) -> float:
        """Maximum RTT in milliseconds"""
        return max(self.rtts) if self.rtts else 0.0

    @property
    def avg_jitter(self) -> float:
        """Average jitter in milliseconds (RFC 3550)"""
        return (
            sum(self.jitter_samples) / len(self.jitter_samples)
            if self.jitter_samples
            else 0.0
        )

    @property
    def throughput_bps(self) -> float:
        """Throughput in bits per second"""
        if self.start_time is None:
            return 0.0
        duration = time.time() - self.start_time
        return (self.bytes_received * 8) / duration if duration > 0 else 0.0

    @property
    def throughput_kbps(self) -> float:
        """Throughput in kilobits per second"""
        return self.throughput_bps / 1000.0

    def calculate_pdr(self) -> float:
        """
        Calculate Packet Delivery Ratio based on received sequence numbers
        
        PDR = (Packets Received / Expected Packets) * 100%
        Expected Packets = highest_seq + 1 (since seq starts at 0)
        
        Returns:
            PDR as a percentage (0-100)
        """
        if self.highest_seq < 0:
            return 100.0  # No packets received yet
        
        expected_packets = self.highest_seq + 1
        if expected_packets == 0:
            return 100.0
        
        return (self.packets_received / expected_packets) * 100.0


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
        self.on_connection_terminated = None  # callback for connection termination
        
        # Metrics tracking for server mode
        self.metrics = {"RELIABLE": ChannelMetrics(), "UNRELIABLE": ChannelMetrics()}
        self.start_time: Optional[float] = None
        self.total_arrivals: int = 0
        
        if not isClient:
            # Ensure certificates exist for server mode
            certfile, keyfile = self._ensure_certificates(certfile, keyfile)
            self.config.load_cert_chain(certfile=certfile, keyfile=keyfile)
        
        # enable datagram support
        if hasattr(self.config, "max_datagram_frame_size"):
            self.config.max_datagram_frame_size = 65536
        else:
            try:
                self.config.datagram_frame_size = 65536
            except Exception:
                pass

    def _ensure_certificates(self, certfile, keyfile):
        """Ensure SSL certificates exist, generate if needed"""
        from generate_cert import ensure_certificates
        return ensure_certificates(certfile, keyfile)

    async def connect(self):
        if not self.is_client:
            raise RuntimeError("connect() should only be used in client mode")

        print(f"Connecting to {self.host}:{self.port} ...")
        self._connect_ctx = connect(self.host, self.port, configuration=self.config)
        self.conn = await self._connect_ctx.__aenter__()
        self.connected = True
        print("Connected to QUIC server")

    async def send(self, data: dict, reliable: bool = True):
        if not self.connected:
            raise RuntimeError("Not connected — call connect() first")

        channel = RELIABLE if reliable else UNRELIABLE
        seq_no = self.seq[channel]
        timestamp = int(time.time() * 1000)

        payload = json.dumps(data)
        header = (
            channel.to_bytes(1, "big")
            + seq_no.to_bytes(2, "big")
            + timestamp.to_bytes(8, "big")
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
            "channels": {}
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
                channel_stats["expected_packets"] = metrics.highest_seq + 1 if metrics.highest_seq >= 0 else 0
            
            summary["channels"][channel_name] = channel_stats
        
        # Calculate total throughput
        total_bytes = sum(m.bytes_received for m in self.metrics.values())
        if runtime > 0:
            summary["total_throughput_kbps"] = (total_bytes * 8) / (runtime * 1000)
        else:
            summary["total_throughput_kbps"] = 0
        
        return summary

    def print_statistics(self, delivered_packets_count: int = 0, out_of_order_count: int = 0):
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
        print(f"  Overall Throughput:         {stats['total_throughput_kbps']:.2f} Kbps")

        # Channel-specific statistics
        print(f"\n{'CHANNEL-SPECIFIC STATISTICS':^100}")
        print("-" * 100)

        for channel_name in ["RELIABLE", "UNRELIABLE"]:
            channel_stats = stats["channels"][channel_name]
            metrics = self.metrics[channel_name]

            print(f"\n  {channel_name} Channel:")
            print(f"    Packets Received:         {channel_stats['packets_received']}")
            print(f"    Packets Delivered:        {channel_stats['packets_delivered']}")
            print(f"    Bytes Received:           {channel_stats['bytes_received']:,} bytes")

            if "latency" in channel_stats:
                print(f"\n    Latency (RTT):")
                print(f"      Average:                {channel_stats['latency']['avg_rtt']:.2f} ms")
                print(f"      Minimum:                {channel_stats['latency']['min_rtt']:.2f} ms")
                print(f"      Maximum:                {channel_stats['latency']['max_rtt']:.2f} ms")

                print(f"\n    Jitter (RFC 3550):")
                print(f"      Average:                {channel_stats['jitter']['avg_jitter']:.2f} ms")
                if "min_jitter" in channel_stats["jitter"]:
                    print(f"      Minimum:                {channel_stats['jitter']['min_jitter']:.2f} ms")
                    print(f"      Maximum:                {channel_stats['jitter']['max_jitter']:.2f} ms")

                print(f"\n    Throughput:")
                print(f"      Rate:                   {channel_stats['throughput']['kbps']:.2f} Kbps")
                print(f"      Rate:                   {channel_stats['throughput']['KBps']:.2f} KBps")

                if "packet_delivery_ratio" in channel_stats:
                    expected = channel_stats.get('expected_packets', 0)
                    print(f"\n    Packet Delivery:")
                    print(f"      Expected Packets:       {expected}")
                    print(f"      Received Packets:       {channel_stats['packets_received']}")
                    print(f"      Delivery Ratio:         {channel_stats['packet_delivery_ratio']:.2f}%")

        # Out-of-order statistics
        print(f"\n{'ORDERING STATISTICS':^100}")
        print("-" * 100)
        print(f"  Out-of-Order Packets:       {out_of_order_count}")
        print(f"  In-Order Packets:           {delivered_packets_count - out_of_order_count}")

        print("=" * 100)

    async def close(self):
        if not self.connected:
            return
        print("Closing QUIC connection...")
        await self._connect_ctx.__aexit__(None, None, None)
        self.connected = False
        print("Connection closed")

    def set_message_callback(self, callback):
        """Set callback for received messages.

        callback should be an async function taking (data: dict, reliable: bool)
        """
        self.on_message = callback

    def set_connection_terminated_callback(self, callback):
        """Set callback for connection termination.
        
        callback should be an async function taking no arguments
        """
        self.on_connection_terminated = callback

    async def start_server(self):
        """Start the QUIC server and wait for connections"""
        if self.is_client:
            raise RuntimeError("Server mode requires isClient=False")

        print(f"Starting QUIC server on {self.host}:{self.port} ...")

        # Create protocol with our message callback
        await serve(
            host=self.host,
            port=self.port,
            configuration=self.config,
            create_protocol=lambda *args, **kwargs: GameServerProtocol(
                *args, 
                on_message=self.on_message, 
                on_connection_terminated=self.on_connection_terminated,
                **kwargs
            ),
        )

        print("Server running")
        await asyncio.Event().wait()

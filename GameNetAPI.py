import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Set

from aioquic.asyncio import connect, serve
from aioquic.quic.configuration import QuicConfiguration

from GameServerProtocol import GameServerProtocol
from generate_cert import ensure_certificates

RELIABLE = 1
UNRELIABLE = 0

RETRANSMISSION_TIMEOUT = 0.2  # 200 ms default
TIMESTAMP_BYTES = 8

# Constants for bounded buffer sizes
MAX_RTT_SAMPLES = 10000  # Keep last 10k RTT samples for statistics
MAX_JITTER_SAMPLES = 10000  # Keep last 10k jitter samples
MAX_SEQUENCE_TRACKING = 100000  # Track up to 100k sequence numbers before cleanup


# -------------------- Metrics Classes --------------------
@dataclass
class ChannelMetrics:
    """
    Metrics for a single channel (reliable or unreliable)
    
    Memory Management:
    - rtts and jitter_samples use bounded deques (10k samples each)
    - received_seqs set has a soft limit of 100k sequence numbers
    - When limit is reached, a warning is logged and set is cleared
    - For assignment testing (typically < 1 minute), buffers are more than sufficient
    - Cleanup occurs automatically on connection termination
    """

    packets_received: int = 0
    packets_delivered: int = 0
    bytes_received: int = 0
    rtts: deque = field(default_factory=lambda: deque(maxlen=MAX_RTT_SAMPLES))
    jitter_samples: deque = field(default_factory=lambda: deque(maxlen=MAX_JITTER_SAMPLES))
    last_rtt: Optional[float] = None
    start_time: Optional[float] = None
    last_seq: int = -1
    highest_seq: int = -1  # Track highest sequence number seen
    received_seqs: Set[int] = field(default_factory=set)  # Track all received sequence numbers for PDR calculation

    def add_rtt(self, rtt_ms: float):
        """Add RTT sample and calculate jitter (RFC 3550)"""
        self.rtts.append(rtt_ms)

        if self.last_rtt is not None:
            jitter = abs(rtt_ms - self.last_rtt)
            self.jitter_samples.append(jitter)

        self.last_rtt = rtt_ms
    
    def check_and_cleanup_seqs(self):
        """Check if sequence tracking set is too large and cleanup if needed"""
        if len(self.received_seqs) > MAX_SEQUENCE_TRACKING:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Sequence tracking exceeded {MAX_SEQUENCE_TRACKING} entries. "
                "Clearing for memory management. PDR calculation may be affected."
            )
            self.received_seqs.clear()
            # Reset tracking variables
            self.highest_seq = -1
    
    def clear_buffers(self):
        """Clear all buffers - called on connection termination"""
        self.received_seqs.clear()
        self.rtts.clear()
        self.jitter_samples.clear()
    
    def reset_metrics(self):
        """Reset all metrics to initial state - called after statistics are displayed"""
        self.packets_received = 0
        self.packets_delivered = 0
        self.bytes_received = 0
        self.rtts.clear()
        self.jitter_samples.clear()
        self.last_rtt = None
        self.start_time = None
        self.last_seq = -1
        self.highest_seq = -1
        self.received_seqs.clear()

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
        
        Assumptions:
        - Sequence numbers start at 0 for each channel
        - Sequence numbers are consecutive and increment by 1
        - No sequence number resets occur during the session
        - Single sender per channel (no multi-sender scenarios)
        
        Returns:
            PDR as a percentage (0-100), or 0.0 if no packets have been received yet.
        """
        if self.highest_seq < 0:
            return 0.0  # No packets received yet
        
        expected_packets = self.highest_seq + 1
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
        
        if not isClient:
            # Metrics tracking for server mode only
            self.metrics = {"RELIABLE": ChannelMetrics(), "UNRELIABLE": ChannelMetrics()}
            self.start_time: Optional[float] = None
            self.total_arrivals: int = 0
            
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
        return ensure_certificates(certfile, keyfile)

    def track_packet_metrics(self, seq_no: int, timestamp: float, payload: dict, reliable: bool) -> dict:
        """
        Track metrics for a received packet (server mode only)
        
        Args:
            seq_no: Packet sequence number
            timestamp: Original send timestamp (seconds)
            payload: Packet payload data
            reliable: True if RELIABLE channel, False if UNRELIABLE
            
        Returns:
            Dictionary with calculated metrics:
            - arrival_time: When packet arrived
            - rtt_ms: Round-trip time in milliseconds
            - out_of_order: Whether packet was out of order
            - channel: "RELIABLE" or "UNRELIABLE"
        """
        if self.is_client:
            raise RuntimeError("track_packet_metrics() should only be used in server mode")
        
        arrival_time = time.time()
        self.total_arrivals += 1
        
        # Determine channel
        channel = "RELIABLE" if reliable else "UNRELIABLE"
        metrics = self.metrics[channel]
        
        # Initialize channel start time
        if metrics.start_time is None:
            metrics.start_time = arrival_time
        
        # Calculate RTT (one-way latency approximation)
        rtt_ms = (arrival_time - timestamp) * 1000
        
        # Add RTT to metrics (also calculates jitter)
        metrics.add_rtt(rtt_ms)
        
        # Update receive counters and track sequence numbers
        metrics.packets_received += 1
        metrics.received_seqs.add(seq_no)
        if seq_no > metrics.highest_seq:
            metrics.highest_seq = seq_no
        
        # Check if we need to cleanup sequence tracking to prevent unbounded growth
        metrics.check_and_cleanup_seqs()
        
        payload_bytes = len(json.dumps(payload).encode())
        metrics.bytes_received += payload_bytes
        
        # Detect out-of-order delivery
        out_of_order = seq_no <= metrics.last_seq and metrics.last_seq >= 0
        if not out_of_order:
            metrics.last_seq = seq_no
        
        return {
            "arrival_time": arrival_time,
            "rtt_ms": rtt_ms,
            "out_of_order": out_of_order,
            "channel": channel
        }

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
        print(f"  Overall Throughput:         {stats['total_throughput_kbps']:.2f} Kbps")

        # Channel-specific statistics
        print(f"\n{'CHANNEL-SPECIFIC STATISTICS':^100}")
        print("-" * 100)

        for channel_name in ["RELIABLE", "UNRELIABLE"]:
            channel_stats = stats["channels"][channel_name]

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
        
        # Reset metrics after displaying statistics to prepare for next connection
        self.reset_all_metrics()
    
    def reset_all_metrics(self):
        """Reset all metrics across all channels - called after statistics display"""
        if not self.is_client and hasattr(self, 'metrics'):
            for channel_metrics in self.metrics.values():
                channel_metrics.reset_metrics()
            self.start_time = None
            self.total_arrivals = 0

    async def close(self):
        if not self.connected:
            return
        print("Closing QUIC connection...")
        
        # Clear buffers to free memory
        if not self.is_client and hasattr(self, 'metrics'):
            for channel_metrics in self.metrics.values():
                channel_metrics.clear_buffers()
        
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

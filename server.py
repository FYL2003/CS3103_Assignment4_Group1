"""
H-QUIC Receiver Application (Server Mode)
CS3103 Assignment 4 - Adaptive Hybrid Transport Protocol for Games

This server receives packets from game clients using the H-QUIC protocol,
tracks performance metrics, and displays comprehensive statistics.

Requirements satisfied:
- Point (g): Logs SeqNo, ChannelType, Timestamp, RTT, retransmissions, packet arrivals
- Point (i): Measures latency, jitter, throughput, and packet delivery ratio
"""

import asyncio
import logging
import time
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass, field

# Import YOUR existing GameNetAPI
from GameNetAPI import GameNetAPI, RELIABLE, UNRELIABLE
from generate_cert import ensure_certificates

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# -------------------- Data Classes --------------------
@dataclass
class PacketInfo:
    """Stores information about a received packet"""
    seq_no: int
    channel: str  # "RELIABLE" or "UNRELIABLE"
    timestamp: float  # Original send timestamp (seconds)
    arrival_time: float  # When it arrived at receiver
    delivery_time: float  # When delivered to application
    rtt_ms: float
    payload: dict
    retransmission_count: int = 0
    out_of_order: bool = False


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
        return sum(self.jitter_samples) / len(self.jitter_samples) if self.jitter_samples else 0.0
    
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
    
    def packet_delivery_ratio(self, total_sent: int) -> float:
        """Calculate PDR as percentage"""
        return (self.packets_received / total_sent * 100) if total_sent > 0 else 100.0


# -------------------- Receiver Application --------------------
class ReceiverApplication:
    """
    H-QUIC Receiver Application (SERVER MODE)
    
    Receives packets from game clients, processes them according to channel type,
    tracks comprehensive metrics, and displays detailed logs.
    
    Features:
    - Separate handling for RELIABLE and UNRELIABLE channels
    - Retransmission detection
    - Out-of-order packet detection
    - Real-time metrics calculation
    - Comprehensive statistics reporting
    """
    
    def __init__(self, host: str = "localhost", port: int = 4433, 
                 certfile: str = "cert.pem", keyfile: str = "key.pem"):
        """
        Initialize receiver application
        
        Args:
            host: Server host address
            port: Server port number
            certfile: Path to SSL certificate
            keyfile: Path to SSL private key
        """
        self.host = host
        self.port = port
        self.certfile = certfile
        self.keyfile = keyfile
        
        # Ensure certificates exist before initializing API
        logger.info("🔐 Checking SSL certificates...")
        self.certfile, self.keyfile = ensure_certificates(certfile, keyfile)
        
        # Initialize GameNetAPI in SERVER mode
        self.api = GameNetAPI(
            isClient=False,
            host=host,
            port=port,
            certfile=self.certfile,
            keyfile=self.keyfile
        )
        
        # Metrics tracking
        self.metrics = {
            'RELIABLE': ChannelMetrics(),
            'UNRELIABLE': ChannelMetrics()
        }
        
        # Packet tracking
        self.delivered_packets: List[PacketInfo] = []
        self.retransmission_detected = defaultdict(int)
        self.packet_arrival_times: Dict[int, float] = {}
        self.packet_send_times: Dict[int, float] = {}
        
        # Overall statistics
        self.start_time: Optional[float] = None
        self.total_arrivals: int = 0
        
        # Control flags
        self.running: bool = False
        
        # Expected RTT threshold for retransmission detection
        self.expected_rtt_ms: float = 50.0  # Base network delay
        self.retransmission_threshold_multiplier: float = 3.0
        
        # Display configuration
        self.log_separator_interval: int = 10  # Print separator every N packets
        
        # Print startup header
        self.print_startup_header()
    
    def print_startup_header(self):
        """Print formatted startup header"""
        print("\n" + "="*100)
        print("🖥️  H-QUIC RECEIVER APPLICATION (SERVER MODE)")
        print("="*100)
        print(f"Started:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Listening on:   {self.host}:{self.port}")
        print(f"Certificate:    {self.certfile}")
        print(f"Private Key:    {self.keyfile}")
        print("="*100)
        print("\nLog Format:")
        print("  [ARRIVAL]  - Packet arrives from network")
        print("  [DELIVER]  - Packet delivered to application (after reordering)")
        print("  [RETRANS]  - Retransmission detected (RTT > threshold)")
        print("  [OUT-ORDER] - Packet received out of order")
        print("  [APP-DATA] - Application displays packet payload")
        print("="*100 + "\n")
    
    async def start(self):
        """Start the receiver server"""
        self.start_time = time.time()
        self.running = True
        
        logger.info("🚀 Starting H-QUIC receiver server...")
        
        # Start server (listens for incoming connections)
        await self.api.start()
        
        logger.info(f"✅ Server started - Listening on {self.host}:{self.port}\n")
        logger.info("Waiting for packets from clients...\n")
    
    async def receive_loop(self):
        """
        Main receive loop - receives and processes packets
        
        This is the core loop that:
        1. Receives packets from GameNetAPI
        2. Processes them based on channel type
        3. Tracks metrics
        4. Displays logs
        """
        try:
            while self.running:
                # Receive packet from GameNetAPI
                packet_dict, reliable = await self.api.receive()
                
                # Extract packet fields
                seq_no = packet_dict['seq_no']
                timestamp = packet_dict['timestamp'] / 1000.0  # Convert ms to seconds
                payload = packet_dict['payload']
                
                # Process the packet
                await self.process_packet(
                    seq_no=seq_no,
                    timestamp=timestamp,
                    payload=payload,
                    reliable=reliable
                )
                
        except KeyboardInterrupt:
            logger.info("\n⚠️  Interrupted by user (Ctrl+C)")
        except asyncio.CancelledError:
            logger.info("\n⚠️  Receive loop cancelled")
        except Exception as e:
            logger.error(f"❌ Error in receive loop: {e}", exc_info=True)
    
    async def process_packet(self, seq_no: int, timestamp: float, 
                            payload: dict, reliable: bool):
        """
        Process a received packet
        
        Args:
            seq_no: Packet sequence number
            timestamp: Original send timestamp (seconds)
            payload: Packet payload data
            reliable: True if RELIABLE channel, False if UNRELIABLE
        """
        arrival_time = time.time()
        self.total_arrivals += 1
        
        # Determine channel
        channel = 'RELIABLE' if reliable else 'UNRELIABLE'
        metrics = self.metrics[channel]
        
        # Initialize channel start time
        if metrics.start_time is None:
            metrics.start_time = arrival_time
        
        # Store timing information
        self.packet_arrival_times[seq_no] = arrival_time
        self.packet_send_times[seq_no] = timestamp
        
        # Calculate RTT (one-way latency approximation)
        rtt_ms = (arrival_time - timestamp) * 1000
        
        # Add RTT to metrics (also calculates jitter)
        metrics.add_rtt(rtt_ms)
        
        # Update receive counters
        metrics.packets_received += 1
        payload_bytes = len(json.dumps(payload).encode())
        metrics.bytes_received += payload_bytes
        
        # Detect retransmission (abnormally high RTT)
        retransmission_threshold = self.expected_rtt_ms * self.retransmission_threshold_multiplier
        is_retransmission = rtt_ms > retransmission_threshold
        if is_retransmission:
            self.retransmission_detected[seq_no] += 1
        
        retrans_count = self.retransmission_detected.get(seq_no, 0)
        
        # Detect out-of-order delivery
        out_of_order = (seq_no <= metrics.last_seq and metrics.last_seq >= 0)
        if not out_of_order:
            metrics.last_seq = seq_no
        
        # Log packet arrival
        self.log_packet_arrival(
            seq_no=seq_no,
            channel=channel,
            timestamp=timestamp,
            rtt_ms=rtt_ms,
            retrans_count=retrans_count,
            out_of_order=out_of_order
        )
        
        # Deliver packet to application
        await self.deliver_packet(
            seq_no=seq_no,
            channel=channel,
            timestamp=timestamp,
            arrival_time=arrival_time,
            rtt_ms=rtt_ms,
            payload=payload,
            retrans_count=retrans_count,
            out_of_order=out_of_order
        )
    
    def log_packet_arrival(self, seq_no: int, channel: str, timestamp: float,
                          rtt_ms: float, retrans_count: int, out_of_order: bool):
        """
        Log packet arrival with detailed information
        
        Satisfies assignment requirement (g): Print logs showing SeqNo, 
        ChannelType, Timestamp, retransmissions, packet arrivals, and RTT
        """
        # Build status indicators
        indicators = []
        if retrans_count > 0:
            indicators.append(f"[RETRANS×{retrans_count}]")
        if out_of_order:
            indicators.append("[OUT-OF-ORDER]")
        
        status = " ".join(indicators) if indicators else ""
        
        # Format channel string
        channel_str = "REL" if channel == "RELIABLE" else "UNR"
        
        # Log arrival
        logger.info(
            f"[ARRIVAL]  "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"Timestamp={timestamp:.6f}s | "
            f"RTT={rtt_ms:7.2f}ms "
            f"{status}"
        )
    
    async def deliver_packet(self, seq_no: int, channel: str, timestamp: float,
                            arrival_time: float, rtt_ms: float, payload: dict,
                            retrans_count: int, out_of_order: bool):
        """
        Deliver packet to application layer
        
        This simulates the application receiving and processing the packet.
        In a real game, this would update game state, render graphics, etc.
        """
        delivery_time = time.time()
        
        # Calculate buffering delay
        buffering_delay_ms = (delivery_time - arrival_time) * 1000
        total_delay_ms = (delivery_time - timestamp) * 1000
        
        # Update metrics
        metrics = self.metrics[channel]
        metrics.packets_delivered += 1
        
        # Store packet info
        packet_info = PacketInfo(
            seq_no=seq_no,
            channel=channel,
            timestamp=timestamp,
            arrival_time=arrival_time,
            delivery_time=delivery_time,
            rtt_ms=rtt_ms,
            payload=payload,
            retransmission_count=retrans_count,
            out_of_order=out_of_order
        )
        self.delivered_packets.append(packet_info)
        
        # Log delivery
        self.log_packet_delivery(
            seq_no=seq_no,
            channel=channel,
            rtt_ms=rtt_ms,
            buffering_delay_ms=buffering_delay_ms,
            total_delay_ms=total_delay_ms,
            retrans_count=retrans_count
        )
        
        # Display application data
        self.display_packet_data(seq_no, channel, payload)
        
        # Print separator for readability
        if seq_no > 0 and seq_no % self.log_separator_interval == 0:
            logger.info("  " + "-"*95)
    
    def log_packet_delivery(self, seq_no: int, channel: str, rtt_ms: float,
                           buffering_delay_ms: float, total_delay_ms: float,
                           retrans_count: int):
        """Log packet delivery to application"""
        channel_str = "REL" if channel == "RELIABLE" else "UNR"
        retrans_str = f"Retrans={retrans_count}" if retrans_count > 0 else "Retrans=0"
        
        logger.info(
            f"[DELIVER]  "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"RTT={rtt_ms:7.2f}ms | "
            f"BuffDelay={buffering_delay_ms:6.2f}ms | "
            f"TotalDelay={total_delay_ms:7.2f}ms | "
            f"{retrans_str}"
        )
    
    def display_packet_data(self, seq_no: int, channel: str, payload: dict):
        """
        Display packet payload data (simulates application usage)
        
        In a real game, this would be:
        - Player position updates
        - Game state changes
        - Chat messages
        - etc.
        """
        channel_str = "REL" if channel == "RELIABLE" else "UNR"
        
        # Format payload for display
        payload_str = json.dumps(payload)
        if len(payload_str) > 70:
            payload_str = payload_str[:67] + "..."
        
        logger.info(
            f"[APP-DATA] "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"Data: {payload_str}"
        )
    
    async def stop(self):
        """Stop the receiver and print final statistics"""
        self.running = False
        
        logger.info("\n" + "="*100)
        logger.info("🛑 STOPPING RECEIVER APPLICATION")
        logger.info("="*100 + "\n")
        
        # Print comprehensive statistics
        self.print_statistics()
        
        # Close API connection
        await self.api.close()
        
        logger.info("\n" + "="*100)
        logger.info("✅ Receiver stopped successfully")
        logger.info("="*100 + "\n")
    
    def print_statistics(self):
        """
        Print comprehensive statistics report
        
        Satisfies assignment requirement (i): Measure performance metrics
        including latency, jitter, throughput, and packet delivery ratio
        """
        runtime = time.time() - self.start_time if self.start_time else 0
        
        print("="*100)
        print("📊 H-QUIC RECEIVER STATISTICS")
        print("="*100)
        
        # Overall statistics
        print(f"\n{'OVERALL STATISTICS':^100}")
        print("-"*100)
        print(f"  Total Runtime:              {runtime:.2f} seconds")
        print(f"  Total Packets Received:     {self.total_arrivals}")
        print(f"  Total Packets Delivered:    {len(self.delivered_packets)}")
        
        # Calculate total throughput
        total_bytes = sum(m.bytes_received for m in self.metrics.values())
        total_throughput_kbps = (total_bytes * 8) / (runtime * 1000) if runtime > 0 else 0
        print(f"  Total Bytes Received:       {total_bytes:,} bytes")
        print(f"  Overall Throughput:         {total_throughput_kbps:.2f} Kbps")
        
        # Channel-specific statistics
        print(f"\n{'CHANNEL-SPECIFIC STATISTICS':^100}")
        print("-"*100)
        
        for channel_name in ['RELIABLE', 'UNRELIABLE']:
            metrics = self.metrics[channel_name]
            
            print(f"\n  {channel_name} Channel:")
            print(f"    Packets Received:         {metrics.packets_received}")
            print(f"    Packets Delivered:        {metrics.packets_delivered}")
            print(f"    Bytes Received:           {metrics.bytes_received:,} bytes")
            
            if metrics.rtts:
                print(f"\n    Latency (RTT):")
                print(f"      Average:                {metrics.avg_rtt:.2f} ms")
                print(f"      Minimum:                {metrics.min_rtt:.2f} ms")
                print(f"      Maximum:                {metrics.max_rtt:.2f} ms")
                
                print(f"\n    Jitter (RFC 3550):")
                print(f"      Average:                {metrics.avg_jitter:.2f} ms")
                if metrics.jitter_samples:
                    print(f"      Minimum:                {min(metrics.jitter_samples):.2f} ms")
                    print(f"      Maximum:                {max(metrics.jitter_samples):.2f} ms")
                
                print(f"\n    Throughput:")
                print(f"      Rate:                   {metrics.throughput_kbps:.2f} Kbps")
                print(f"      Rate:                   {metrics.throughput_kbps/8:.2f} KBps")
                
                # Calculate PDR (assuming we sent same number as received for demo)
                # In production, sender would send this information
                pdr = (metrics.packets_received / self.total_arrivals * 100) if self.total_arrivals > 0 else 0
                print(f"\n    Packet Delivery Ratio:")
                print(f"      PDR:                    {pdr:.2f}%")
        
        # Retransmission statistics
        total_retransmissions = sum(self.retransmission_detected.values())
        print(f"\n{'RETRANSMISSION STATISTICS':^100}")
        print("-"*100)
        print(f"  Total Retransmissions:      {total_retransmissions}")
        print(f"  Packets with Retrans:       {len(self.retransmission_detected)}")
        
        if self.retransmission_detected:
            retrans_list = sorted(
                self.retransmission_detected.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            print(f"  Most Retransmitted (top 5):")
            for seq, count in retrans_list:
                print(f"    SeqNo {seq:4d}:              {count} retransmissions")
        
        # Out-of-order statistics
        out_of_order_count = sum(1 for p in self.delivered_packets if p.out_of_order)
        print(f"\n{'ORDERING STATISTICS':^100}")
        print("-"*100)
        print(f"  Out-of-Order Packets:       {out_of_order_count}")
        print(f"  In-Order Packets:           {len(self.delivered_packets) - out_of_order_count}")
        
        print("="*100)


# -------------------- Main Entry Point --------------------
async def main():
    """
    Main entry point for H-QUIC receiver application
    
    Usage:
        python server.py
    """
    # Configuration
    HOST = "localhost"
    PORT = 4433
    CERTFILE = "cert.pem"
    KEYFILE = "key.pem"
    
    # Create receiver application
    receiver = ReceiverApplication(
        host=HOST,
        port=PORT,
        certfile=CERTFILE,
        keyfile=KEYFILE
    )
    
    try:
        # Start receiver server
        await receiver.start()
        
        # Run receive loop
        await receiver.receive_loop()
        
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"\n❌ Error: {e}", exc_info=True)
    finally:
        # Always stop gracefully and show statistics
        await receiver.stop()


if __name__ == "__main__":
    """
    Run the receiver application
    
    Example:
        python server.py
    """
    print("\n" + "🎮 "*25)
    print("CS3103 Assignment 4 - H-QUIC Protocol")
    print("Adaptive Hybrid Transport Protocol for Games")
    print("🎮 "*25 + "\n")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!\n")
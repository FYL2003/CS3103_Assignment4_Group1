"""
H-QUIC Receiver Application (Server Mode)
CS3103 Assignment 4 - Adaptive Hybrid Transport Protocol for Games

This server receives packets from game clients using the H-QUIC protocol,
tracks performance metrics, and displays comprehensive statistics.

Requirements satisfied:
- Point (g): Logs SeqNo, ChannelType, Timestamp, RTT, packet arrivals
- Point (i): Measures latency, jitter, throughput, and packet delivery ratio
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from GameNetAPI import GameNetAPI

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d | %(message)s",
    datefmt="%H:%M:%S",
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
    out_of_order: bool = False


# -------------------- Receiver Application --------------------
class ReceiverApplication:
    """
    H-QUIC Receiver Application (SERVER MODE)

    Receives packets from game clients, processes them according to channel type,
    tracks comprehensive metrics, and displays detailed logs.

    Features:
    - Separate handling for RELIABLE and UNRELIABLE channels
    - Out-of-order packet detection
    - Real-time metrics calculation
    - Comprehensive statistics reporting
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4433,
        certfile: str = "cert.pem",
        keyfile: str = "key.pem",
    ):
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

        # Initialize GameNetAPI in SERVER mode
        # Certificate generation is now handled inside GameNetAPI
        self.api = GameNetAPI(
            isClient=False,
            host=host,
            port=port,
            certfile=certfile,
            keyfile=keyfile,
        )

        # Packet tracking
        self.delivered_packets: List[PacketInfo] = []
        self.packet_arrival_times: Dict[int, float] = {}
        self.packet_send_times: Dict[int, float] = {}

        # Control flags
        self.running: bool = False

        # Display configuration
        self.log_separator_interval: int = 10  # Print separator every N packets

        # Print startup header
        self.print_startup_header()

        # Set up message callback
        self.api.set_message_callback(self.on_message)

        # Set up connection termination callback
        self.api.set_connection_terminated_callback(self.on_connection_terminated)

    def print_startup_header(self):
        """Print formatted startup header"""
        print("\n" + "=" * 100)
        print("H-QUIC RECEIVER APPLICATION (SERVER MODE)")
        print("=" * 100)
        print(f"Started:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Listening on:   {self.host}:{self.port}")
        print(f"Certificate:    {self.certfile}")
        print(f"Private Key:    {self.keyfile}")
        print("=" * 100)
        print("\nLog Format:")
        print("  [ARRIVAL]  - Packet arrives from network")
        print("  [DELIVER]  - Packet delivered to application (after reordering)")
        print("  [OUT-ORDER] - Packet received out of order")
        print("  [APP-DATA] - Application displays packet payload")
        print("=" * 100 + "\n")

    async def start(self):
        """Start the receiver server"""
        self.api.start_time = time.time()
        self.running = True

        logger.info("Starting H-QUIC receiver server...")

        # Start server (listens for incoming connections)
        await self.api.start_server()

        logger.info(f"Server started - Listening on {self.host}:{self.port}\n")
        logger.info("Waiting for packets from clients...\n")

    async def on_message(self, data: dict, reliable: bool):
        """Callback for received messages - updates metrics"""
        # Extract packet fields
        seq_no = data["seq_no"]
        timestamp = data["timestamp"] / 1000.0  # Convert ms to seconds
        payload = data["payload"]

        # Track metrics using API
        metrics_data = self.api.track_packet_metrics(seq_no, timestamp, payload, reliable)
        # Store timing information for application use
        self.packet_arrival_times[seq_no] = metrics_data["arrival_time"]
        self.packet_send_times[seq_no] = timestamp

        # Log packet arrival
        self.log_packet_arrival(
            seq_no=seq_no,
            channel=metrics_data["channel"],
            timestamp=timestamp,
            rtt_ms=metrics_data["rtt_ms"],
            out_of_order=metrics_data["out_of_order"],
        )

        # Deliver packet to application
        await self.deliver_packet(
            seq_no=seq_no,
            channel=metrics_data["channel"],
            timestamp=timestamp,
            arrival_time=metrics_data["arrival_time"],
            rtt_ms=metrics_data["rtt_ms"],
            payload=payload,
            out_of_order=metrics_data["out_of_order"],
        )

    async def on_connection_terminated(self):
        """Callback when client connection is terminated - display statistics"""
        logger.info("")
        logger.info("=" * 100)
        logger.info("CLIENT CONNECTION TERMINATED")
        logger.info("=" * 100)

        # Display statistics
        out_of_order_count = sum(1 for p in self.delivered_packets if p.out_of_order)
        self.api.print_statistics(
            delivered_packets_count=len(self.delivered_packets),
            out_of_order_count=out_of_order_count
        )

        logger.info("")
        logger.info("=" * 100)
        logger.info("Server continues running - waiting for new connections...")
        logger.info("Press Ctrl+C to stop the server")
        logger.info("=" * 100)

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
                await asyncio.sleep(0.1)  # Prevent 100% CPU usage in loop

        except KeyboardInterrupt:
            logger.info("\nInterrupted by user (Ctrl+C)")
        except asyncio.CancelledError:
            logger.info("\nReceive loop cancelled")
        except Exception as e:
            logger.error(f"Error in receive loop: {e}", exc_info=True)

    def log_packet_arrival(
        self,
        seq_no: int,
        channel: str,
        timestamp: float,
        rtt_ms: float,
        out_of_order: bool,
    ):
        """
        Log packet arrival with detailed information

        Satisfies assignment requirement (g): Print logs showing SeqNo,
        ChannelType, Timestamp, packet arrivals, and RTT
        """
        # Build status indicators
        indicators = []
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

    async def deliver_packet(
        self,
        seq_no: int,
        channel: str,
        timestamp: float,
        arrival_time: float,
        rtt_ms: float,
        payload: dict,
        out_of_order: bool,
    ):
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
        metrics = self.api.metrics[channel]
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
            out_of_order=out_of_order,
        )
        self.delivered_packets.append(packet_info)

        # Log delivery
        self.log_packet_delivery(
            seq_no=seq_no,
            channel=channel,
            rtt_ms=rtt_ms,
            buffering_delay_ms=buffering_delay_ms,
            total_delay_ms=total_delay_ms,
        )

        # Display application data
        self.display_packet_data(seq_no, channel, payload)

        # Print separator for readability
        if seq_no > 0 and seq_no % self.log_separator_interval == 0:
            logger.info("  " + "-" * 95)

    def log_packet_delivery(
        self,
        seq_no: int,
        channel: str,
        rtt_ms: float,
        buffering_delay_ms: float,
        total_delay_ms: float,
    ):
        """Log packet delivery to application"""
        channel_str = "REL" if channel == "RELIABLE" else "UNR"

        logger.info(
            f"[DELIVER]  "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"RTT={rtt_ms:7.2f}ms | "
            f"BuffDelay={buffering_delay_ms:6.2f}ms | "
            f"TotalDelay={total_delay_ms:7.2f}ms | "
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
        """Stop the receiver gracefully"""
        self.running = False

        logger.info("\n" + "=" * 100)
        logger.info("STOPPING RECEIVER APPLICATION")
        logger.info("=" * 100)

        # Close API connection
        await self.api.close()

        logger.info("Receiver stopped successfully")
        logger.info("=" * 100 + "\n")


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
        host=HOST, port=PORT, certfile=CERTFILE, keyfile=KEYFILE
    )

    try:
        # Start receiver server
        await receiver.start()

        # Run receive loop
        await receiver.receive_loop()

    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"\nError: {e}", exc_info=True)
    finally:
        # Always stop gracefully and show statistics
        await receiver.stop()


if __name__ == "__main__":
    """
    Run the receiver application

    Example:
        python server.py
    """
    print("CS3103 Assignment 4 - H-QUIC Protocol")
    print("Adaptive Hybrid Transport Protocol for Games")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nEnd Connection")
    except Exception as e:
        logger.error(f"\nUnexpected error: {e}", exc_info=True)

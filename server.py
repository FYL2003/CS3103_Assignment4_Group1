"""
H-QUIC Receiver Application (Server Mode) - REFACTORED

This server receives packets from game clients using the H-QUIC protocol,
tracks performance metrics, and displays comprehensive statistics.

Simplifications:
- Consolidated all packet processing logic into `on_message`.
- Centralized exception handling and shutdown logic in `main`.
- Created a helper for statistics display and state reset.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from GameNetAPI import GameNetAPI  # Assuming GameNetAPI is in a separate file

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

    Receives packets, processes them, tracks metrics, and logs results.
    Logic is consolidated for clarity.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 4433,
        certfile: str = "cert.pem",
        keyfile: str = "key.pem",
    ):
        self.host = host
        self.port = port
        self.certfile = certfile
        self.keyfile = keyfile

        # Initialize GameNetAPI in SERVER mode
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

        # Set up callbacks
        self.api.set_message_callback(self.on_message)
        self.api.set_connection_terminated_callback(
            self.on_connection_terminated
        )

    def print_startup_header(self):
        """Print formatted startup header"""
        print("\n" + "=" * 100)
        print("H-QUIC RECEIVER APPLICATION (SERVER MODE)")
        print("=" * 100)
        print(f"Started:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Listening on:   {self.host}:{self.port}")
        print("=" * 100)
        print("\nLog Format:")
        print("  [ARRIVAL]   - Packet arrives from network")
        print("  [DELIVER]   - Packet delivered to application (after reordering)")
        print("  [OUT-ORDER] - Packet received out of order")
        print("  [APP-DATA]  - Application displays packet payload")
        print("=" * 100 + "\n")

    async def start(self):
        """Start the receiver server"""
        self.print_startup_header()
        self.api.start_time = time.time()
        self.running = True

        logger.info("Starting H-QUIC receiver server...")
        await self.api.start_server()
        logger.info(f"Server started - Listening on {self.host}:{self.port}\n")
        logger.info("Waiting for packets from clients...\n")

    async def on_message(self, data: dict, reliable: bool, proto: GameNetAPI):
        """
        Callback for received messages.
        This function now handles the *entire* packet lifecycle.
        """
        
        # --- 1. Extract Data and Track Core Metrics ---
        seq_no = data["seq_no"]
        timestamp = data["timestamp"] / 1000.0  # Convert ms to seconds
        payload = data["payload"]
        buffer_entry_time = data.get("buffer_entry_time")

        metrics_data = self.api.track_packet_metrics(
            seq_no, timestamp, payload, reliable, buffer_entry_time
        )
        
        # Store timing information
        self.packet_arrival_times[seq_no] = metrics_data["arrival_time"]
        self.packet_send_times[seq_no] = timestamp

        # --- 2. Send Acknowledgement (ACK) ---
        response = {
            "ack": "received",
            "seq_echo": seq_no,
            "payload_echo": payload,
        }
        await proto.send_packet(response, reliable=reliable)

        # --- 3. Log Packet Arrival ---
        self.log_packet_arrival(
            seq_no=seq_no,
            channel=metrics_data["channel"],
            timestamp=timestamp,
            rtt_ms=metrics_data["rtt_ms"],
            out_of_order=metrics_data["out_of_order"],
        )

        # --- 4. Process Application-Layer "Delivery" ---
        delivery_time = time.time()
        channel = metrics_data["channel"]
        rtt_ms = metrics_data["rtt_ms"]
        buffering_delay_ms = metrics_data["buffering_delay_ms"]
        total_delay_ms = rtt_ms + buffering_delay_ms

        # Update delivery metrics
        self.api.metrics[channel].packets_delivered += 1

        # Store packet info for final statistics
        packet_info = PacketInfo(
            seq_no=seq_no,
            channel=channel,
            timestamp=timestamp,
            arrival_time=metrics_data["arrival_time"],
            delivery_time=delivery_time,
            rtt_ms=rtt_ms,
            payload=payload,
            out_of_order=metrics_data["out_of_order"],
        )
        self.delivered_packets.append(packet_info)

        # --- 5. Log Packet Delivery & Application Data ---
        self.log_packet_delivery(
            seq_no=seq_no,
            channel=channel,
            rtt_ms=rtt_ms,
            buffering_delay_ms=buffering_delay_ms,
            total_delay_ms=total_delay_ms,
        )

        self.display_packet_data(seq_no, channel, payload)

        # --- 6. Print Separator (for readability) ---
        if seq_no > 0 and seq_no % self.log_separator_interval == 0:
            logger.info("  " + "-" * 95)

    def _display_and_reset_stats(self):
        """
        Helper function to print statistics and reset session state.
        """
        if not self.delivered_packets:
            logger.info("No packets were delivered in this session.")
            self.api.reset_all_metrics() # Still reset API state
            return

        logger.info("=" * 100)
        logger.info("SESSION STATISTICS")
        logger.info("=" * 100)

        out_of_order_count = sum(
            1 for p in self.delivered_packets if p.out_of_order
        )
        self.api.print_statistics(
            delivered_packets_count=len(self.delivered_packets),
            out_of_order_count=out_of_order_count,
        )
        
        # Clear delivered packets list for next connection
        self.delivered_packets.clear()
        self.packet_arrival_times.clear()
        self.packet_send_times.clear()
        
        # Explicitly reset all metrics for next connection
        self.api.reset_all_metrics()

    async def on_connection_terminated(self):
        """Callback when client connection is terminated."""
        logger.info("")
        logger.info("=" * 100)
        logger.info("CLIENT CONNECTION TERMINATED")
        
        self._display_and_reset_stats() # Display stats and reset

        logger.info("")
        logger.info("=" * 100)
        logger.info("Server continues running - waiting for new connections...")
        logger.info("Press Ctrl+C to stop the server")
        logger.info("=" * 100)

    async def receive_loop(self):
        """
        Main "keep-alive" loop.
        This just keeps the main coroutine running so the server can
        receive packets via its background callbacks.
        """
        try:
            while self.running:
                await asyncio.sleep(1)  # Sleep to prevent high CPU
        except asyncio.CancelledError:
            # This is expected when stop() is called
            logger.info("\nReceive loop cancelled")

    # -------------------- Logging Functions --------------------
    # (These are unchanged, as they are just log formatting)

    def log_packet_arrival(
        self,
        seq_no: int,
        channel: str,
        timestamp: float,
        rtt_ms: float,
        out_of_order: bool,
    ):
        """Log packet arrival with detailed information"""
        status = "[OUT-OF-ORDER]" if out_of_order else ""
        channel_str = "REL" if channel == "RELIABLE" else "UNR"
        logger.info(
            f"[ARRIVAL]   "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"Timestamp={timestamp:.6f}s | "
            f"RTT={rtt_ms:7.2f}ms "
            f"{status}"
        )

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
            f"[DELIVER]   "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"RTT={rtt_ms:7.2f}ms | "
            f"BuffDelay={buffering_delay_ms:6.2f}ms | "
            f"TotalDelay={total_delay_ms:7.2f}ms"
        )

    def display_packet_data(self, seq_no: int, channel: str, payload: dict):
        """Display packet payload data (simulates application usage)"""
        channel_str = "REL" if channel == "RELIABLE" else "UNR"
        payload_str = json.dumps(payload)
        if len(payload_str) > 70:
            payload_str = payload_str[:67] + "..."

        logger.info(
            f"[APP-DATA]  "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"Data: {payload_str}"
        )

    async def stop(self):
        """Stop the receiver gracefully"""
        if not self.running:  # Prevent double-stop
            return
            
        self.running = False
        logger.info("\n" + "=" * 100)
        logger.info("STOPPING RECEIVER APPLICATION")
        logger.info("=" * 100)

        # If a client was connected, print its final stats
        if self.delivered_packets:
            logger.info("Client was connected. Printing final session stats...")
            self._display_and_reset_stats()

        # Close API connection
        await self.api.close()
        await asyncio.sleep(0.1)  # Give tasks a moment to close

        logger.info("Receiver stopped successfully")
        logger.info("=" * 100 + "\n")


# -------------------- Main Entry Point --------------------
async def main():
    """
    Main entry point for H-QUIC receiver application
    """
    # Configuration
    HOST = "localhost"
    PORT = 4433
    CERTFILE = "cert.pem"
    KEYFILE = "key.pem"

    receiver = ReceiverApplication(
        host=HOST, port=PORT, certfile=CERTFILE, keyfile=KEYFILE
    )

    try:
        # Start receiver server
        await receiver.start()

        # Run "keep-alive" loop
        await receiver.receive_loop()

    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user (Ctrl+C). Stopping...")
    except Exception as e:
        logger.error(f"\nUncaught error in main: {e}", exc_info=True)
    finally:
        # This will *always* run, ensuring a clean shutdown
        logger.info("Shutting down...")
        await receiver.stop()


if __name__ == "__main__":
    """
    Run the receiver application
    """
    print("CS3103 Assignment 4 - H-QUIC Protocol")
    print("Adaptive Hybrid Transport Protocol for Games")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This catches the interrupt *after* asyncio.run() has finished
        # (because main() catches it first and returns)
        print("\nEnd Connection")
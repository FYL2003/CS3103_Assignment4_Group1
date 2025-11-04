"""
H-QUIC Receiver Application (Server Mode) - REFACTORED & FIXED

This server receives packets from game clients using the H-QUIC protocol,
tracks performance metrics, and displays comprehensive statistics.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from GameNetAPI import GameNetAPI  # Assuming GameNetAPI is in a separate file


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
    Logic is consolidated for clarity and robust shutdown.
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
        self.stats_printed_for_session: bool = False

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

        print("Starting H-QUIC receiver server...")
        await self.api.start_server()
        print(f"Server started - Listening on {self.host}:{self.port}\n")
        print("Waiting for packets from clients...\n")

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
            print("  " + "-" * 95)

    def _display_and_reset_stats(self):
        """
        Helper function to print statistics and reset session state.
        This is now "idempotent" - safe to call multiple times.
        """
        # FIX: If stats were already printed for this session, do nothing.
        if self.stats_printed_for_session:
            return

        if not self.delivered_packets:
            print("No packets were delivered in this session.")
            self.api.reset_all_metrics()  # Still reset API state
            return

        # --- This is a new session, print stats ---
        print("=" * 100)
        print("SESSION STATISTICS")
        print("=" * 100)
        
        # FIX: Set the flag so we don't print them again
        self.stats_printed_for_session = True 

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
        print("")
        print("=" * 100)
        print("CLIENT CONNECTION TERMINATED")
        
        self._display_and_reset_stats()  # Display stats and reset
        
        # FIX: RE-ARM THE FLAG for the *next* session
        self.stats_printed_for_session = False

        print("")
        print("=" * 100)
        print("Server continues running - waiting for new connections...")
        print("Press Ctrl+C to stop the server")
        print("=" * 100)

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
            print("\nReceive loop cancelled")

    # -------------------- Logging Functions --------------------

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
        print(
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
        print(
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

        print(
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
        print("\n" + "=" * 100)
        print("STOPPING RECEIVER APPLICATION")
        print("=" * 100)

        # Call the stats helper. If a client was connected,
        # this will print their stats. If stats were already
        # printed by on_connection_terminated, this will do nothing.
        self._display_and_reset_stats()

        # Close API connection
        await self.api.close()
        await asyncio.sleep(0.1)  # Give tasks a moment to close

        print("Receiver stopped successfully")
        print("=" * 100 + "\n")


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
        print("\n\nInterrupted by user (Ctrl+C). Stopping...")
    except Exception as e:
        print(f"\nUncaught error in main: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # This will *always* run, ensuring a clean shutdown
        print("Shutting down...")
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
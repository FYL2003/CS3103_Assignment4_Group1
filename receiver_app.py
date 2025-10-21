"""
Receiver Application - Works directly with existing GameNetAPI
Displays data received through gameNetAPI with detailed logs
Shows: SeqNo, ChannelType, Timestamp, Retransmissions, Packet Arrivals, RTT, etc.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

# Import YOUR existing GameNetAPI
from GameNetAPI import GameNetAPI

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class ReceiverApplication:
    """
    Receiver application that displays detailed packet information
    Implements all logging requirements from assignment point (g)
    """
    
    def __init__(self):
        """Initialize receiver application"""
        
        # Initialize YOUR GameNetAPI
        self.api = GameNetAPI()
        
        # Statistics tracking
        self.start_time = None
        self.packet_arrival_times = {}  # {seq_no: arrival_time}
        self.packet_send_times = {}     # {seq_no: send_time} (from timestamp)
        self.retransmission_detected = defaultdict(int)  # {seq_no: retx_count}
        self.delivered_packets = []
        self.total_arrivals = 0
        
        # Channel statistics
        self.channel_stats = {
            'reliable': {'received': 0, 'delivered': 0, 'rtts': []},
            'unreliable': {'received': 0, 'delivered': 0, 'rtts': []}
        }
        
        # Sequence tracking
        self.last_seq = {'reliable': -1, 'unreliable': -1}
        
        # Running flag
        self.running = False
        
        # Console formatting
        self.print_header()
    
    def print_header(self):
        """Print formatted header for logs"""
        print("\n" + "="*100)
        print("🖥️  RECEIVER APPLICATION - H-QUIC Protocol")
        print("="*100)
        print(f"Started:        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*100)
        print("\nLog Format:")
        print("  [ARRIVAL]  - Packet arrives from network")
        print("  [DELIVER]  - Packet delivered to application (after reordering)")
        print("  [RETRANS]  - Retransmission detected")
        print("  [APP-DATA] - Application displays packet data")
        print("="*100 + "\n")
    
    def on_packet_received(self, packet_data, reliable, seq_no=None, timestamp=None):
        """
        Callback/handler when packet is received
        Adjust parameter extraction based on YOUR packet structure
        
        Args:
            packet_data: Could be dict, object, or raw data
            reliable: Boolean indicating channel type
            seq_no: Sequence number (if available)
            timestamp: Send timestamp (if available)
        """
        self.total_arrivals += 1
        arrival_time = time.time()
        
        # Extract packet fields based on YOUR structure
        # Adjust this section based on how your packets are structured
        if isinstance(packet_data, dict):
            # If packet is a dictionary
            seq_no = seq_no or packet_data.get('seq_no', self.total_arrivals)
            timestamp = timestamp or packet_data.get('timestamp', arrival_time)
            payload = packet_data
        elif hasattr(packet_data, '__dict__'):
            # If packet is an object
            seq_no = seq_no or getattr(packet_data, 'seq_no', self.total_arrivals)
            timestamp = timestamp or getattr(packet_data, 'timestamp', arrival_time)
            payload = packet_data
        else:
            # Fallback
            seq_no = seq_no or self.total_arrivals
            timestamp = timestamp or arrival_time
            payload = packet_data
        
        # Store arrival time
        self.packet_arrival_times[seq_no] = arrival_time
        self.packet_send_times[seq_no] = timestamp
        
        # Calculate RTT (one-way latency)
        rtt_ms = (arrival_time - timestamp) * 1000
        
        # Update channel statistics
        channel_key = 'reliable' if reliable else 'unreliable'
        self.channel_stats[channel_key]['received'] += 1
        self.channel_stats[channel_key]['rtts'].append(rtt_ms)
        
        # Detect retransmission (if RTT is abnormally high)
        expected_rtt = 50  # Base network delay
        if rtt_ms > expected_rtt * 3:  # 3x threshold suggests retransmission
            self.retransmission_detected[seq_no] += 1
            retx_indicator = f"[RETRANS×{self.retransmission_detected[seq_no]}]"
        else:
            retx_indicator = ""
        
        # Check for out-of-order delivery
        if seq_no <= self.last_seq[channel_key] and self.last_seq[channel_key] >= 0:
            out_of_order_indicator = "[OUT-OF-ORDER]"
        else:
            out_of_order_indicator = ""
            self.last_seq[channel_key] = seq_no
        
        # Print arrival log
        channel_str = "REL" if reliable else "UNR"
        logger.info(
            f"[ARRIVAL]  "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"Timestamp={timestamp:.6f} | "
            f"RTT={rtt_ms:7.2f}ms {retx_indicator}{out_of_order_indicator}"
        )
        
        # Deliver packet (in your implementation, GameNetAPI handles reordering)
        self.on_packet_delivered(payload, reliable, seq_no, timestamp, rtt_ms)
    
    def on_packet_delivered(self, packet_data, reliable, seq_no, timestamp, rtt_ms):
        """
        Called when packet is ready for application delivery
        """
        delivery_time = time.time()
        self.delivered_packets.append({
            'seq_no': seq_no,
            'reliable': reliable,
            'data': packet_data,
            'rtt': rtt_ms,
            'timestamp': timestamp
        })
        
        # Update channel statistics
        channel_key = 'reliable' if reliable else 'unreliable'
        self.channel_stats[channel_key]['delivered'] += 1
        
        # Calculate buffering delay
        arrival_time = self.packet_arrival_times.get(seq_no, delivery_time)
        buffering_delay_ms = (delivery_time - arrival_time) * 1000
        total_delay_ms = (delivery_time - timestamp) * 1000
        
        # Check if this was retransmitted
        retx_count = self.retransmission_detected.get(seq_no, 0)
        retx_str = f"Retrans={retx_count}" if retx_count > 0 else "Retrans=0"
        
        # Print delivery log
        channel_str = "REL" if reliable else "UNR"
        logger.info(
            f"[DELIVER]  "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"RTT={rtt_ms:7.2f}ms | "
            f"BuffDelay={buffering_delay_ms:6.2f}ms | "
            f"TotalDelay={total_delay_ms:7.2f}ms | "
            f"{retx_str}"
        )
        
        # Display application data
        self.display_packet_data(packet_data, seq_no, channel_str)
    
    def display_packet_data(self, packet_data, seq_no, channel_str):
        """
        Display the actual packet payload data
        """
        # Format payload for display
        payload_str = str(packet_data)
        if len(payload_str) > 70:
            payload_str = payload_str[:67] + "..."
        
        logger.info(
            f"[APP-DATA] "
            f"SeqNo={seq_no:4d} | "
            f"Channel={channel_str} | "
            f"Data: {payload_str}"
        )
        
        # Print separator every 10 packets for readability
        if seq_no > 0 and seq_no % 10 == 0:
            logger.info("  " + "-"*95)
    
    async def start(self):
        """Start the receiver application"""
        self.start_time = time.time()
        self.running = True
        
        logger.info("🚀 Starting receiver...\n")
        
        # Connect using YOUR GameNetAPI
        await self.api.connect()
        
        logger.info("✅ Receiver connected - Listening for packets...\n")
    
    async def receive_loop(self):
        """
        Main receive loop
        Adapt this based on how YOUR GameNetAPI receives packets
        """
        try:
            while self.running:
                # OPTION 1: If your API has a receive() method
                if hasattr(self.api, 'receive'):
                    try:
                        packet = await self.api.receive()
                        if packet:
                            # Extract packet info based on YOUR structure
                            # Adjust these based on your packet format
                            if isinstance(packet, dict):
                                data = packet.get('data') or packet.get('payload') or packet
                                reliable = packet.get('reliable', True)
                                seq_no = packet.get('seq_no')
                                timestamp = packet.get('timestamp')
                            elif hasattr(packet, 'data'):
                                data = packet.data
                                reliable = getattr(packet, 'reliable', True)
                                seq_no = getattr(packet, 'seq_no', None)
                                timestamp = getattr(packet, 'timestamp', None)
                            else:
                                data = packet
                                reliable = True
                                seq_no = None
                                timestamp = None
                            
                            self.on_packet_received(data, reliable, seq_no, timestamp)
                    except asyncio.TimeoutError:
                        await asyncio.sleep(0.01)
                
                # OPTION 2: If your API has a get_packet() method
                elif hasattr(self.api, 'get_packet'):
                    packet = self.api.get_packet()
                    if packet:
                        # Process packet (same extraction as above)
                        self.on_packet_received(packet, True)  # Adjust parameters
                    else:
                        await asyncio.sleep(0.01)
                
                # OPTION 3: If your API uses callbacks (do nothing, callback handles it)
                elif hasattr(self.api, 'on_receive') or hasattr(self.api, 'set_receive_callback'):
                    # Just wait, callbacks handle reception
                    await asyncio.sleep(0.1)
                
                # OPTION 4: If your API has internal queue
                elif hasattr(self.api, 'packet_queue'):
                    if not self.api.packet_queue.empty():
                        packet = await self.api.packet_queue.get()
                        self.on_packet_received(packet, True)  # Adjust parameters
                    else:
                        await asyncio.sleep(0.01)
                
                else:
                    # Default: just wait
                    logger.warning("⚠️  No receive method found in GameNetAPI. Waiting...")
                    await asyncio.sleep(1)
                    
        except KeyboardInterrupt:
            logger.info("\n⚠️  Interrupted by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"❌ Error in receive loop: {e}", exc_info=True)
    
    async def stop(self):
        """Stop the receiver and print final statistics"""
        self.running = False
        
        logger.info("\n" + "="*100)
        logger.info("🛑 STOPPING RECEIVER APPLICATION")
        logger.info("="*100 + "\n")
        
        # Print comprehensive statistics
        self.print_statistics()
        
        # Close connection
        await self.api.close()
        
        logger.info("\n" + "="*100)
        logger.info("✅ Receiver stopped successfully")
        logger.info("="*100 + "\n")
    
    def print_statistics(self):
        """Print comprehensive statistics with all required metrics"""
        runtime = time.time() - self.start_time if self.start_time else 0
        
        print("="*100)
        print("📊 RECEIVER APPLICATION STATISTICS")
        print("="*100)
        
        # Overall statistics
        print(f"\n{'Overall Statistics':^100}")
        print("-"*100)
        print(f"  Total Runtime:        {runtime:.2f} seconds")
        print(f"  Total Arrivals:       {self.total_arrivals} packets")
        print(f"  Total Delivered:      {len(self.delivered_packets)} packets")
        
        # Channel-specific statistics
        print(f"\n{'Channel Statistics':^100}")
        print("-"*100)
        
        for channel in ['reliable', 'unreliable']:
            stats = self.channel_stats[channel]
            print(f"\n  {channel.upper()} Channel:")
            print(f"    Received:           {stats['received']} packets")
            print(f"    Delivered:          {stats['delivered']} packets")
            
            if stats['rtts']:
                rtts = stats['rtts']
                print(f"    Avg RTT:            {sum(rtts)/len(rtts):.2f} ms")
                print(f"    Min RTT:            {min(rtts):.2f} ms")
                print(f"    Max RTT:            {max(rtts):.2f} ms")
                
                # Jitter calculation
                if len(rtts) > 1:
                    jitter = sum(abs(rtts[i] - rtts[i-1]) for i in range(1, len(rtts))) / (len(rtts) - 1)
                    print(f"    Jitter:             {jitter:.2f} ms")
                
                # PDR calculation
                if self.total_arrivals > 0:
                    pdr = (stats['received'] / self.total_arrivals * 100)
                    print(f"    PDR:                {pdr:.2f}%")
        
        # Retransmission statistics
        total_retransmissions = sum(self.retransmission_detected.values())
        print(f"\n{'Retransmission Statistics':^100}")
        print("-"*100)
        print(f"  Total Retransmissions Detected: {total_retransmissions}")
        
        if self.retransmission_detected:
            print(f"  Packets with Retransmissions:   {len(self.retransmission_detected)}")
            retrans_list = [(seq, count) for seq, count in self.retransmission_detected.items()]
            retrans_list.sort(key=lambda x: x[1], reverse=True)
            print(f"  Most Retransmitted (top 5):     {retrans_list[:5]}")
        
        # Throughput calculation
        if runtime > 0:
            total_bytes = sum(len(str(p['data']).encode()) for p in self.delivered_packets)
            throughput_kbps = (total_bytes * 8) / (runtime * 1000)
            
            print(f"\n{'Throughput Statistics':^100}")
            print("-"*100)
            print(f"  Total Data Received:  {total_bytes} bytes")
            print(f"  Throughput:           {throughput_kbps:.2f} Kbps")
            print(f"  Avg Packet Size:      {total_bytes / len(self.delivered_packets) if self.delivered_packets else 0:.2f} bytes")
        
        print("="*100)


async def main():
    """Main entry point"""
    receiver = ReceiverApplication()
    
    try:
        await receiver.start()
        await receiver.receive_loop()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"\n❌ Error: {e}", exc_info=True)
    finally:
        await receiver.stop()


if __name__ == "__main__":
    asyncio.run(main())
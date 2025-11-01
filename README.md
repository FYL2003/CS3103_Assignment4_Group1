# CS3103_Assignment4_Group1
AY25/26 Sem1 CS3103 group project - H-QUIC Protocol Implementation

## Overview
This project implements H-QUIC (Hybrid QUIC), an adaptive hybrid transport protocol for real-time multiplayer games. The protocol dynamically manages both reliable and unreliable data delivery over QUIC.

## Dependencies
- `aioquic` >= 0.9.20
- `cryptography` >= 42.0.0

To install dependencies, run:
```bash
pip install -r requirements.txt
```

## Certificate Setup
SSL certificates are automatically generated when you run the server. The `generate_cert.py` module creates self-signed certificates for QUIC connections.

You can also manually generate certificates using OpenSSL:
```bash
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"
```

## Running the Application

### Start the Server
```bash
python3 server.py
```

The server will:
- Automatically generate SSL certificates if needed
- Listen on `localhost:4433`
- Display statistics when clients disconnect
- Continue running to accept new connections

### Run the Client
```bash
python3 client.py
```

The client sends 50 packets (mix of reliable and unreliable) to test the protocol.

## Network Testing Guide

This section describes how to test the H-QUIC implementation with network delay simulators as required by Assignment 4, Point (h).

### Option 1: tc-netem (Linux)

**tc-netem** is the recommended tool for Linux systems. It provides realistic network emulation including delay, jitter, packet loss, and bandwidth limitations.

#### Prerequisites
```bash
# Check if tc is available (usually pre-installed on Linux)
which tc

# If not available, install iproute2
sudo apt-get install iproute2  # Debian/Ubuntu
sudo yum install iproute        # RHEL/CentOS
```

#### Basic Usage

1. **Add delay (e.g., 50ms)**
```bash
sudo tc qdisc add dev lo root netem delay 50ms
```

2. **Add delay with jitter (e.g., 50ms ± 10ms)**
```bash
sudo tc qdisc add dev lo root netem delay 50ms 10ms
```

3. **Add packet loss (e.g., 2% loss)**
```bash
sudo tc qdisc add dev lo root netem loss 2%
```

4. **Combine delay, jitter, and packet loss (Low Loss Scenario)**
```bash
# Low loss scenario: 50ms delay, 10ms jitter, 2% packet loss
sudo tc qdisc add dev lo root netem delay 50ms 10ms loss 2%
```

5. **High Loss Scenario (>10% loss)**
```bash
# High loss scenario: 100ms delay, 20ms jitter, 15% packet loss
sudo tc qdisc add dev lo root netem delay 100ms 20ms loss 15%
```

6. **Remove network emulation**
```bash
sudo tc qdisc del dev lo root
```

#### Test Scenarios for Assignment

**Scenario 1: Low Loss (<2%)**
```bash
sudo tc qdisc add dev lo root netem delay 30ms 5ms loss 1%
python3 server.py &
sleep 2
python3 client.py
# Statistics display automatically when client disconnects
sudo tc qdisc del dev lo root
```

**Scenario 2: High Loss (>10%)**
```bash
sudo tc qdisc add dev lo root netem delay 100ms 20ms loss 12%
python3 server.py &
sleep 2
python3 client.py
# Statistics display automatically when client disconnects
sudo tc qdisc del dev lo root
```

### Option 2: Clumsy (Windows)

**Clumsy** is a network condition simulator for Windows that can introduce delays, packet loss, and other network issues.

#### Installation
1. Download from: https://jagt.github.io/clumsy/
2. Extract the zip file
3. Run clumsy.exe as Administrator

#### Usage
1. Launch Clumsy as Administrator
2. Select the network interface (usually your active network adapter)
3. Configure parameters:
   - **Lag**: Add delay (e.g., 50ms)
   - **Drop**: Add packet loss (e.g., 2% or 15%)
   - **Throttle**: Limit bandwidth
4. Click "Start" to begin emulation
5. Run your H-QUIC server and client
6. Click "Stop" when done

### Option 3: Mininet with tc-netem (Advanced)

For more advanced testing with virtual network topologies:

```bash
# Install Mininet
sudo apt-get install mininet

# Create a custom topology with network delays
sudo mn --custom=path/to/topology.py --topo mytopo
```

Example mininet topology with delays (topology.py):
```python
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.link import TCLink

class GameNetTopo(Topo):
    def build(self):
        # Add hosts
        client = self.addHost('client')
        server = self.addHost('server')
        
        # Add link with 50ms delay, 2% loss
        self.addLink(client, server, 
                     cls=TCLink, 
                     delay='50ms', 
                     loss=2)

# Run:
# sudo python3 topology.py
```

## Testing Procedure (Assignment Requirements)

### Test Duration and Packet Rate
- **Test Duration**: 30 seconds to 1 minute
- **Packet Rate**: 10-100 packets/second

The default client.py sends 50 packets with 50ms intervals (~20 packets/second), which meets the requirements.

### Modify client.py for extended testing:

```python
# For 30-second test at 20 packets/second
for _ in range(600):  # 30 seconds * 20 packets/second
    reliable = random.choice([True, False])
    data = generate_game_data()
    await api.send(data, reliable=reliable)
    await asyncio.sleep(0.05)  # 50ms = 20 packets/second
```

## Metrics Reported

The H-QUIC system automatically measures and reports:

1. **Latency (RTT)** - Average, Min, Max
2. **Jitter (RFC 3550)** - Average, Min, Max
3. **Throughput** - Kbps and KBps
4. **Packet Delivery Ratio (PDR)** - Percentage of packets successfully received

All metrics are reported **separately for RELIABLE and UNRELIABLE channels**.

### Test Scenarios Required

Report results for at least two network conditions:

#### Scenario 1: Low Loss (< 2%)
```bash
# Linux with tc-netem
sudo tc qdisc add dev lo root netem delay 30ms 5ms loss 1%

# Windows with Clumsy
# Set: Lag=30ms, Drop=1%
```

#### Scenario 2: High Loss (> 10%)
```bash
# Linux with tc-netem
sudo tc qdisc add dev lo root netem delay 100ms 20ms loss 12%

# Windows with Clumsy
# Set: Lag=100ms, Drop=12%
```

## Viewing Statistics

### Automatic Display on Client Disconnect
When the client closes its connection, the server will automatically display comprehensive statistics including:
- Overall statistics (runtime, total packets, throughput)
- Channel-specific statistics (RELIABLE and UNRELIABLE)
- Latency metrics (avg, min, max RTT)
- Jitter metrics (avg, min, max)
- Throughput (Kbps, KBps)
- Packet Delivery Ratio (PDR%)
- Ordering statistics (out-of-order packets)

### Manual Display
Press `Ctrl+C` on the server to stop and display final statistics.

## Example Output

```
====================================================================================================
H-QUIC RECEIVER STATISTICS
====================================================================================================

OVERALL STATISTICS
----------------------------------------------------------------------------------------------------
  Total Runtime:              30.45 seconds
  Total Packets Received:     580
  Total Packets Delivered:    580
  Total Bytes Received:       45,230 bytes
  Overall Throughput:         11.88 Kbps

CHANNEL-SPECIFIC STATISTICS
----------------------------------------------------------------------------------------------------

  RELIABLE Channel:
    Packets Received:         290
    Packets Delivered:        290
    Bytes Received:           22,615 bytes

    Latency (RTT):
      Average:                53.24 ms
      Minimum:                32.15 ms
      Maximum:                98.76 ms

    Jitter (RFC 3550):
      Average:                8.42 ms
      Minimum:                0.23 ms
      Maximum:                25.67 ms

    Throughput:
      Rate:                   5.94 Kbps
      Rate:                   0.74 KBps

    Packet Delivery:
      Expected Packets:       295
      Received Packets:       290
      Delivery Ratio:         98.31%

  UNRELIABLE Channel:
    Packets Received:         290
    Packets Delivered:        290
    Bytes Received:           22,615 bytes

    Latency (RTT):
      Average:                51.87 ms
      Minimum:                31.02 ms
      Maximum:                95.43 ms

    Jitter (RFC 3550):
      Average:                7.98 ms
      Minimum:                0.19 ms
      Maximum:                23.45 ms

    Throughput:
      Rate:                   5.94 Kbps
      Rate:                   0.74 KBps

    Packet Delivery:
      Expected Packets:       305
      Received Packets:       290
      Delivery Ratio:         95.08%

ORDERING STATISTICS
----------------------------------------------------------------------------------------------------
  Out-of-Order Packets:       15
  In-Order Packets:           565
====================================================================================================
```

## Tips for Testing

1. **Always remove tc rules after testing**: `sudo tc qdisc del dev lo root`
2. **Test multiple times** for consistent results
3. **Save statistics** to files for comparison: `python3 server.py > results_low_loss.txt 2>&1`
4. **Use different packet rates** to stress-test the protocol
5. **Compare RELIABLE vs UNRELIABLE** channels under different conditions

## Troubleshooting

### tc-netem not affecting localhost traffic
Some systems require special configuration for tc to affect localhost:
```bash
# Try using different interface
sudo tc qdisc add dev eth0 root netem delay 50ms

# Or use network namespaces for complete isolation
```

### Permission denied errors
Make sure to run tc commands with sudo:
```bash
sudo tc qdisc add dev lo root netem delay 50ms
```

### Clumsy not working
- Run Clumsy as Administrator
- Make sure to select the correct network interface
- Check Windows Firewall settings

## Project Structure

- `server.py` - H-QUIC receiver application (server mode)
- `client.py` - H-QUIC sender application (client mode)
- `GameNetAPI.py` - Core API with metrics tracking and statistics
- `GameServerProtocol.py` - QUIC protocol handler
- `generate_cert.py` - SSL certificate generation utility
- `requirements.txt` - Python dependencies

## Assignment Requirements Met

- ✅ Point (c): GameNetAPI receives packets and passes to receiver application
- ✅ Point (g): Logs show SeqNo, ChannelType, Timestamp, RTT, packet arrivals
- ✅ Point (h): Network emulator testing guide (tc-netem, Clumsy, Mininet)
- ✅ Point (i): Metrics measured separately for RELIABLE and UNRELIABLE channels


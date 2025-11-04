# QUIC Retransmission Implementation

This document describes the implementation of timer-based retransmission and reliability mechanisms for QUIC packets.

## Overview

The implementation adds reliable data transfer (RDT) features to QUIC communication, including:
- Explicit ACK mechanism
- Timer-based retransmission on client side
- Timeout-based packet skipping on server side
- In-order packet delivery with buffering and reordering

## Architecture

### Client Side (GameNetAPI.py)

The client implements:
1. **ACK Tracking**: Maintains `pending_acks` dictionary to track packets awaiting acknowledgment
2. **Retransmission Timer**: Runs every 50ms to check for unacknowledged packets
3. **Retransmission Logic**: Retransmits packets up to 3 times if ACK not received within 200ms
4. **ACK Processing**: Processes ACK datagrams from server to clear pending packets

Key components:
- `GameClientProtocol._check_retransmit()`: Background task checking for packets needing retransmission
- `GameClientProtocol.send_packet()`: Sends packets and tracks them for ACK
- `GameClientProtocol._handle_datagram()`: Processes incoming ACKs

### Server Side (GameServerProtocol.py)

The server implements:
1. **Immediate ACK**: Sends ACK datagram upon receiving each reliable packet
2. **Buffering**: Stores out-of-order packets in `reliable_buffer`
3. **Timeout Detection**: Runs every 10ms to detect missing packets
4. **Packet Skipping**: Skips packets that don't arrive within 200ms threshold
5. **In-Order Delivery**: Delivers packets in sequence after skipping timed-out ones

Key components:
- `GameServerProtocol._send_ack()`: Sends ACK for received packets
- `GameServerProtocol._check_timeouts()`: Background task monitoring for timeouts
- `GameServerProtocol._deliver_reliable()`: Delivers buffered packets in order

## Configuration

### Constants

- `RETRANSMISSION_TIMEOUT = 0.2` (200ms): Timeout threshold for both retransmission and packet skipping
- `TIMEOUT_CHECK_INTERVAL = 0.01` (10ms): How often server checks for timeouts
- `RETRANSMIT_CHECK_INTERVAL = 0.05` (50ms): How often client checks for retransmissions
- `MAX_RETRANSMIT = 3`: Maximum retransmission attempts before giving up

These can be tuned based on network conditions and requirements.

## Behavior

### Normal Operation (No Packet Loss)

1. Client sends packet with seq_no N
2. Server receives packet N, sends ACK N
3. Client receives ACK N, removes from pending
4. Server delivers packet N to application

### Packet Loss with Successful Retransmission

1. Client sends packet with seq_no N
2. Packet lost in transit
3. After 200ms, client retransmits packet N
4. Server receives retransmission, sends ACK N
5. Client receives ACK N, removes from pending
6. Server delivers packet N to application

### Permanent Packet Loss (Timeout)

1. Client sends packets N, N+1, N+2
2. Packet N permanently lost (never arrives)
3. Server receives N+1, N+2 and buffers them
4. After 200ms, server timeout fires
5. Server skips packet N, marks as timed out
6. Server delivers packets N+1, N+2 in order
7. Application receives remaining data without N

## Testing

Three test scripts verify the implementation:

### test_retransmission.py
Basic functionality test - verifies sequential delivery and ACK mechanism work correctly with no packet loss.

### test_packet_loss.py
Simulates 30% packet drop rate to test client-side retransmission. Verifies that all dropped packets are successfully retransmitted and received.

### test_timeout.py
Simulates permanent packet loss to test server-side timeout mechanism. Permanently drops packets 2, 5, and 8, then verifies:
- Server buffers subsequent packets
- Server skips missing packets after 200ms
- Remaining packets delivered in order

### Running Tests

```bash
# Start server
python3 server.py

# In another terminal, run tests
python3 test_retransmission.py
python3 test_packet_loss.py
python3 test_timeout.py

# Or use the integrated test script
bash run_test.sh
```

## Metrics

The server tracks additional metrics for reliable packets:
- `packets_skipped`: Number of packets that timed out and were skipped

View metrics by stopping the server (Ctrl+C), which prints statistics including skipped packets.

## Protocol Details

### Packet Format

All packets (both reliable and unreliable) have the following format:

```
[1 byte: channel] [2 bytes: seq_no] [8 bytes: timestamp] [N bytes: JSON payload]
```

- `channel`: 1 for reliable, 0 for unreliable
- `seq_no`: Sequence number (0-65535)
- `timestamp`: Milliseconds since epoch
- `payload`: JSON-encoded data

### ACK Packet Format

ACKs are sent as unreliable datagrams with special payload:

```json
{
  "type": "ACK",
  "seq_no": <acknowledged_sequence_number>
}
```

## Performance Considerations

### Timeout Check Interval

The server checks for timeouts every 10ms (`TIMEOUT_CHECK_INTERVAL`). This provides good timeout precision while maintaining reasonable CPU usage. If experiencing high CPU usage, consider increasing this value to 20-50ms.

### Retransmission Check Interval

The client checks for retransmissions every 50ms (`RETRANSMIT_CHECK_INTERVAL`). This balances responsiveness with efficiency. Lower values provide faster retransmission but increase CPU usage.

### Buffer Management

Out-of-order packets are buffered in memory. In production, consider:
- Limiting buffer size to prevent memory exhaustion
- Implementing flow control
- Adding buffer overflow detection

## Future Enhancements

Potential improvements:
1. **Adaptive Timeout**: Adjust timeout based on measured RTT
2. **Selective ACK**: ACK ranges instead of individual packets
3. **Congestion Control**: Reduce transmission rate under loss
4. **Flow Control**: Prevent sender from overwhelming receiver
5. **Configurable Timeout**: Allow runtime adjustment of timeout threshold

## References

- Kurose and Ross, Computer Networking textbook (RDT principles)
- QUIC RFC 9000 (QUIC protocol specification)
- aioquic documentation (Python QUIC implementation)

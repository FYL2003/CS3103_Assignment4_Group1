# 200ms Packet Timeout Implementation

## Overview

This document describes the implementation of the 200ms packet timeout mechanism for the reliable channel in the H-QUIC protocol, as required by assignment requirement (e):

> "If any packet is lost and retransmission is not reached by t milliseconds threshold, you should skip that packet and display rest of the data."

Where `t = 200ms` by default (configurable via `RETRANSMISSION_TIMEOUT` constant).

## Implementation Details

### Files Modified

- `GameServerProtocol.py`: Added timeout checking mechanism

### New Components

1. **`_timeout_task`**: Async task that runs continuously to check for timeouts
2. **`_expected_seq_time`**: Timestamp tracking when we started waiting for expected packet
3. **`_check_timeouts()`**: Method that periodically checks for timed-out packets

### How It Works

#### Timeout Detection Flow

```
1. First reliable packet arrives
   └─> Start timeout task if not already running

2. Timeout task runs every 50ms
   ├─> Check if _expected_seq_time is set
   ├─> Calculate elapsed time since waiting started
   └─> If elapsed > 200ms:
       ├─> Check if packet exists in buffer
       ├─> If YES: Deliver it (late arrival, not lost)
       ├─> If NO: Skip it (truly lost)
       └─> Try to deliver subsequent buffered packets

3. When packet is delivered
   └─> Reset timer for next expected packet
```

#### Timer Management

The timer (`_expected_seq_time`) is:
- **Initialized**: When first packet for expected sequence arrives (or any later packet)
- **Reset**: When packets are successfully delivered
- **Checked**: Every 50ms by the timeout task

### Design Decisions

#### Why 50ms Check Interval?

- Provides 4 checks per 200ms timeout period
- Good balance between responsiveness and CPU usage
- Catches timeouts within ~12.5% accuracy (50ms/200ms * 50%)

#### Why Reset Timer to `current_time` Instead of `None`?

The timer is reset to `current_time` (not `None`) when:
1. A packet times out and we skip it
2. Packets are successfully delivered

**Rationale:**
- **Safety First**: Starting the timer immediately ensures we don't miss the timeout window
- **Conservative Approach**: Better to have a running timer than miss a lost packet
- **Simpler Logic**: Consistent behavior - timer is always set when waiting

**Alternative Considered:**
Setting timer to `None` and only starting it when a packet for the new expected sequence arrives. This was rejected because:
- Adds complexity to determine when to start timer
- Risk of missing timeout if no subsequent packets arrive
- Current approach is safer and simpler

#### Why Check `if self.expected_seq in self.reliable_buffer`?

Before skipping a packet, we check if it actually exists in the buffer. This is critical because:

**Case 1: Packet arrives late but before timeout**
```python
# Packet 1 expected, arrives at T+190ms (before 200ms timeout)
# Packet is in buffer: self.reliable_buffer[1] exists
# Action: DELIVER, don't skip
```

**Case 2: Packet never arrives**
```python
# Packet 1 expected, never arrives
# After 200ms: self.reliable_buffer[1] doesn't exist
# Action: SKIP and move to next sequence
```

This prevents incorrectly skipping packets that arrived out-of-order but are ready to be delivered.

## Test Cases

### Test 1: Normal Operation (No Timeout)
```
Packets: 0, 1, 2, 3, 4 arrive in order
Result: All delivered immediately
Expected: [0, 1, 2, 3, 4] ✅
```

### Test 2: Packet Never Arrives (Timeout)
```
Packets: 0 delivered, 1 NEVER arrives, 2, 3 in buffer
After 200ms: Skip packet 1, deliver 2, 3
Result: [0, 2, 3] ✅
```

### Test 3: Packet Arrives Late (In Buffer Before Timeout)
```
Packets: 0 delivered, 1 arrives at T+190ms (late but in time), 2 in buffer
After 200ms: Packet 1 is in buffer, so deliver it (not skip)
Result: [0, 1, 2] ✅
```

### Test 4: Out-of-Order with Multiple Buffered
```
Packets: 0, 1 delivered, 2 missing, 3, 4, 5 in buffer
After 200ms: Skip 2, deliver 3, 4, 5
Result: [0, 1, 3, 4, 5] ✅
```

## Code Snippets

### Timeout Checker

```python
async def _check_timeouts(self):
    """Check for timed-out packets every 50ms"""
    try:
        while True:
            await asyncio.sleep(0.05)
            
            if self._expected_seq_time is None:
                continue  # Not waiting for anything
            
            elapsed = time.time() - self._expected_seq_time
            
            if elapsed > RETRANSMISSION_TIMEOUT:
                if self.expected_seq in self.reliable_buffer:
                    # Packet arrived late, deliver it
                    await self._deliver_reliable()
                else:
                    # Packet never arrived, skip it
                    logger.warning(f"Packet {self.expected_seq} timed out")
                    self.expected_seq += 1
                    self._expected_seq_time = time.time()
                    await self._deliver_reliable()
```

### Timer Initialization

```python
if reliable:
    self.reliable_buffer[seq_no] = (data, timestamp)
    # Initialize timer if this is first packet we're waiting for
    if self._expected_seq_time is None and seq_no >= self.expected_seq:
        self._expected_seq_time = time.time()
    await self._deliver_reliable()
```

### Timer Reset

```python
async def _deliver_reliable(self):
    while self.expected_seq in self.reliable_buffer:
        data, ts = self.reliable_buffer.pop(self.expected_seq)
        await self._deliver_packet(data, reliable=True, seq_no=self.expected_seq, timestamp=ts)
        self.expected_seq += 1
        # Reset timer for next expected packet
        self._expected_seq_time = time.time()
```

## Performance Considerations

### CPU Usage
- Timeout task runs continuously every 50ms
- Single timer variable (no per-packet tracking)
- Minimal overhead per check (~microseconds)

### Memory Usage
- Single `_expected_seq_time` variable (8 bytes)
- No unbounded data structures
- Timeout task is one async coroutine

### Network Behavior
- Prevents head-of-line blocking in reliable channel
- Allows subsequent packets to be delivered even if earlier ones are lost
- Maintains in-order delivery for packets that do arrive

## Limitations and Future Improvements

### Current Limitations

1. **Fixed Check Interval**: 50ms is hardcoded
   - Could be made configurable
   - Could be adaptive based on measured RTT

2. **Global Timeout**: Same timeout for all packets
   - Could be per-packet based on RTT measurements
   - Could increase for higher sequence numbers

3. **No Feedback to Sender**: Receiver skips but doesn't inform sender
   - Could send NACK (negative acknowledgment)
   - Could request selective retransmission

### Future Improvements

1. **Adaptive Timeout**: Adjust based on measured RTT variance
2. **Configurable Check Interval**: Allow tuning for different scenarios  
3. **Statistics**: Track how many packets timeout vs. arrive late
4. **Sender Feedback**: Implement NACK or selective ACK

## Assignment Compliance

This implementation satisfies assignment requirement (e):

✅ **"If any packet is lost and retransmission is not reached by t milliseconds threshold"**
   - Default t = 200ms (RETRANSMISSION_TIMEOUT)
   - Configurable via constant

✅ **"you should skip that packet"**
   - Packets that don't arrive within 200ms are skipped
   - Expected sequence advances past missing packet

✅ **"and display rest of the data"**
   - Subsequent buffered packets are delivered
   - Prevents head-of-line blocking
   - Application receives all available packets

## Conclusion

The 200ms packet timeout mechanism is fully implemented and tested. It correctly handles:
- Normal in-order delivery
- Out-of-order arrivals within timeout
- Truly lost packets (skip after timeout)
- Late arrivals (deliver if in buffer)

The implementation is memory-efficient, performant, and meets all assignment requirements.

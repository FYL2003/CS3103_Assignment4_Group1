import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Set

# Constants for bounded buffer sizes
MAX_RTT_SAMPLES = 10000
MAX_JITTER_SAMPLES = 10000
MAX_SEQUENCE_TRACKING = 100000


@dataclass
class ChannelMetrics:
    """
    Metrics for a single channel (reliable or unreliable).

    Memory Management:
    - rtts and jitter_samples use bounded deques (10k samples each)
    - received_seqs has a soft limit of 100k entries
    """

    packets_received: int = 0
    packets_delivered: int = 0
    bytes_received: int = 0

    rtts: deque = field(default_factory=lambda: deque(maxlen=MAX_RTT_SAMPLES))
    jitter_samples: deque = field(
        default_factory=lambda: deque(maxlen=MAX_JITTER_SAMPLES)
    )
    last_rtt: Optional[float] = None
    start_time: Optional[float] = None

    last_seq: int = -1
    highest_seq: int = -1
    received_seqs: Set[int] = field(default_factory=set)

    def add_rtt(self, rtt_ms: float):
        """Add RTT sample and calculate jitter (RFC 3550)."""
        self.rtts.append(rtt_ms)
        if self.last_rtt is not None:
            jitter = abs(rtt_ms - self.last_rtt)
            self.jitter_samples.append(jitter)
        self.last_rtt = rtt_ms

    def check_and_cleanup_seqs(self):
        """If sequence tracking grows too large, clear it."""
        if len(self.received_seqs) > MAX_SEQUENCE_TRACKING:
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Sequence tracking exceeded {MAX_SEQUENCE_TRACKING}. "
                "Clearing for memory management; PDR may be affected."
            )
            self.received_seqs.clear()
            self.highest_seq = -1

    def clear_buffers(self):
        """Clear all buffers (called on connection termination)."""
        self.received_seqs.clear()
        self.rtts.clear()
        self.jitter_samples.clear()

    def reset_metrics(self):
        """Reset all metrics to initial state (after stats are displayed)."""
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

    # ----------------------- Computed Properties -----------------------

    @property
    def avg_rtt(self) -> float:
        return sum(self.rtts) / len(self.rtts) if self.rtts else 0.0

    @property
    def min_rtt(self) -> float:
        return min(self.rtts) if self.rtts else 0.0

    @property
    def max_rtt(self) -> float:
        return max(self.rtts) if self.rtts else 0.0

    @property
    def avg_jitter(self) -> float:
        return (
            sum(self.jitter_samples) / len(self.jitter_samples)
            if self.jitter_samples
            else 0.0
        )

    @property
    def throughput_bps(self) -> float:
        if self.start_time is None:
            return 0.0
        duration = time.time() - self.start_time
        return (self.bytes_received * 8) / duration if duration > 0 else 0.0

    @property
    def throughput_kbps(self) -> float:
        return self.throughput_bps / 1000.0

    def calculate_pdr(self) -> float:
        """Calculate Packet Delivery Ratio (%) based on received sequence numbers."""
        if self.highest_seq < 0:
            return 0.0
        expected_packets = self.highest_seq + 1
        return (self.packets_received / expected_packets) * 100.0

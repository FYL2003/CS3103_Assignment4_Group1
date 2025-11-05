import asyncio
import json
import time
from collections import deque

RELIABLE = 1
UNRELIABLE = 0
RETRANSMISSION_TIMEOUT = 0.2


def current_millis():
    return int(time.time() * 1000)


class UDPSessionProtocol(asyncio.DatagramProtocol):
    """Handles sending/receiving reliable and unreliable packets over UDP."""

    def __init__(
        self, is_client=True, on_message=None, t_threshold=RETRANSMISSION_TIMEOUT
    ):
        self.is_client = is_client
        self.on_message = on_message
        self.t_threshold = t_threshold

        self.transport = None
        self.peer_addr = None
        self.seq = {RELIABLE: 0, UNRELIABLE: 0}
        self.pending_reliable = {}  # seq -> (data_bytes, send_time)
        self.retransmit_task = None

        # Performance metrics
        self.metrics = {
            RELIABLE: {
                "sent": 0,
                "received": 0,
                "rtts": deque(maxlen=1000),
                "bytes": 0,
                "jitter": 0.0,
            },
            UNRELIABLE: {
                "sent": 0,
                "received": 0,
                "rtts": deque(maxlen=1000),
                "bytes": 0,
                "jitter": 0.0,
            },
        }

    # --------------------- Connection Setup ---------------------
    def connection_made(self, transport):
        self.transport = transport
        print("[UDP] Connection established")
        self.retransmit_task = asyncio.create_task(self._retransmit_loop())

    def connection_lost(self, exc):
        if self.retransmit_task:
            self.retransmit_task.cancel()
        print("[UDP] Connection closed:", exc)

    def set_peer(self, addr):
        self.peer_addr = addr

    # --------------------- Packet I/O ---------------------
    async def send_packet(self, data: dict, reliable=True):
        channel = RELIABLE if reliable else UNRELIABLE
        seq_no = self.seq[channel]
        self.seq[channel] = (seq_no + 1) % 65536

        payload = json.dumps(data).encode()
        timestamp = current_millis()
        header = (
            channel.to_bytes(1, "big")
            + seq_no.to_bytes(2, "big")
            + timestamp.to_bytes(8, "big")
        )
        packet = header + payload

        self.transport.sendto(packet, self.peer_addr)
        self.metrics[channel]["sent"] += 1
        self.metrics[channel]["bytes"] += len(packet)

        if reliable:
            self.pending_reliable[seq_no] = (packet, timestamp)

    def datagram_received(self, data, addr):
        asyncio.create_task(self._handle_packet(data, addr))

    async def _handle_packet(self, data, addr):
        if len(data) < 11:
            return
        channel = data[0]
        seq_no = int.from_bytes(data[1:3], "big")
        timestamp = int.from_bytes(data[3:11], "big")
        payload = data[11:]

        # ACK handling
        if payload == b"ACK":
            if seq_no in self.pending_reliable:
                send_time = self.pending_reliable.pop(seq_no)[1]
                rtt = current_millis() - send_time
                self.metrics[channel]["rtts"].append(rtt)
                self._update_jitter(channel, rtt)
            return

        # normal data received
        self.metrics[channel]["received"] += 1
        self.metrics[channel]["bytes"] += len(data)

        # compute RTT for one-way approximation if timestamp present
        rtt_est = current_millis() - timestamp
        self.metrics[channel]["rtts"].append(rtt_est)
        self._update_jitter(channel, rtt_est)

        # send ACK if reliable
        if channel == RELIABLE:
            ack_packet = (
                channel.to_bytes(1, "big")
                + seq_no.to_bytes(2, "big")
                + timestamp.to_bytes(8, "big")
                + b"ACK"
            )
            self.transport.sendto(ack_packet, addr)

        try:
            parsed = json.loads(payload.decode())
        except Exception:
            parsed = payload

        if self.on_message:
            await self.on_message(
                parsed, channel == RELIABLE, {"seq": seq_no, "timestamp": timestamp}
            )

    # --------------------- Retransmission ---------------------
    async def _retransmit_loop(self):
        while True:
            await asyncio.sleep(self.t_threshold)
            now = current_millis()
            for seq, (packet, sent_time) in list(self.pending_reliable.items()):
                if now - sent_time > self.t_threshold * 1000:
                    self.transport.sendto(packet, self.peer_addr)
                    self.pending_reliable[seq] = (packet, now)

    # --------------------- Metrics helpers ---------------------
    def _update_jitter(self, channel, new_rtt):
        m = self.metrics[channel]
        if len(m["rtts"]) < 2:
            return
        prev_rtt = list(m["rtts"])[-2]
        diff = abs(new_rtt - prev_rtt)
        m["jitter"] += (diff - m["jitter"]) / 16  # RFC 3550

    def get_metrics(self):
        results = {}
        for ch in (RELIABLE, UNRELIABLE):
            m = self.metrics[ch]
            avg_rtt = sum(m["rtts"]) / len(m["rtts"]) if m["rtts"] else 0
            duration = (len(m["rtts"]) / 1000) if m["rtts"] else 1
            throughput = m["bytes"] / max(duration, 1)
            pdr = (m["received"] / m["sent"] * 100) if m["sent"] > 0 else 0
            results["reliable" if ch == RELIABLE else "unreliable"] = {
                "avg_rtt_ms": round(avg_rtt, 2),
                "jitter_ms": round(m["jitter"], 2),
                "throughput_Bps": round(throughput, 2),
                "packet_delivery_ratio_%": round(pdr, 2),
            }
        return results

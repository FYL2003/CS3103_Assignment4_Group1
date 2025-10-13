# implement a hybrid transport layer protocol that dynamically manages both reliable and unreliable data delivery over UDP 
# (or QUIC) for real-time multiplayer games. The protocol should allow game developers to mark
# data packets based on their reliability requirements — e.g., reliable for critical game state
# updates, unreliable but low-latency for movement or voice chat packets.

# Packet header: | ChannelType (1 B) | SeqNo (2 B) | Timestamp (4 B) | Payload |.

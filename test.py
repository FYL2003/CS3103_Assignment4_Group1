# implement a hybrid transport layer protocol that dynamically manages both reliable and unreliable data delivery over UDP 
# (or QUIC) for real-time multiplayer games. The protocol should allow game developers to mark
# data packets based on their reliability requirements — e.g., reliable for critical game state
# updates, unreliable but low-latency for movement or voice chat packets.

# Packet header: | ChannelType (1 B) | SeqNo (2 B) | Timestamp (4 B) | Payload |.

import sys
import socket

def server():
    sPort = int(sys.argv[1])  # 2nd command line argument is your port num
    sSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sSocket.bind(("", sPort)) 

    while True:
        msg, addr = sSocket.recvfrom(1024)
        print(f"Received message: {msg.decode()} from {addr}")
        if not msg:
            break
    sSocket.close()

server()
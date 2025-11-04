# server.py
import asyncio
from GameNetAPI import GameNetAPI

# -------------------- Message Callback --------------------
async def on_message(data, reliable, proto):
    """
    - proto: GameServerProtocol instance
    """
    # await proto.send_packet({"ACK": data["seq_no"] + 1} | data["payload"], reliable=reliable)
    pass

# -------------------- Main --------------------
async def main():
    api = GameNetAPI(
        isClient=False,
        host="localhost",
        port=4433,
        certfile="cert.pem",
        keyfile="key.pem",
    )

    api.set_message_callback(on_message)

    # Track connected server protocols
    api.server_protocols = []

    # Wrapper to track protocols automatically
    def protocol_wrapper(*args, **kwargs):
        from GameServerProtocol import GameServerProtocol
        proto = GameServerProtocol(*args, on_message=api.on_message, **kwargs)
        api.server_protocols.append(proto)
        return proto

    try:
        print("Starting QUIC server...")
        await api.start_server(create_protocol=protocol_wrapper)  # runs forever
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        # Print statistics once for all connected protocols
        if hasattr(api, "server_protocols"):
            for proto in api.server_protocols:
                proto.print_statistics()
        await api.close()

# -------------------- Entry Point --------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped by user")

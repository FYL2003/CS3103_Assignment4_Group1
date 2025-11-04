# CS3103_Assignment4_Group1
AY25/26 Sem1 CS3103 group project

## Features

- **QUIC Protocol**: High-performance QUIC communication with both reliable and unreliable channels
- **Timer-Based Retransmission**: Implements RDT with ACK mechanism and automatic retransmission
- **Timeout Handling**: Server-side timeout detection and packet skipping after 200ms threshold
- **In-Order Delivery**: Buffering and reordering ensures reliable packets delivered in sequence

For detailed implementation information, see [IMPLEMENTATION.md](IMPLEMENTATION.md).

## Dependencies
`aioquic`

To install dependencies, run `pip install -r requirements.txt`.  

As aioquic requires a TLS certificate for server mode, generate a self-signed certificate in the project:

```bash
# Generate certificate using provided script
python3 generate_cert.py

# Or manually with OpenSSL
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"
```

## Running the Application

### Server
```bash
python3 server.py
```

### Client
```bash
python3 client.py
```

## Testing

Three test scripts verify the retransmission implementation:

```bash
# Test basic sequential delivery
python3 test_retransmission.py

# Test retransmission with 30% packet loss
python3 test_packet_loss.py

# Test server timeout mechanism
python3 test_timeout.py

# Or run all tests
bash run_test.sh
```

See [IMPLEMENTATION.md](IMPLEMENTATION.md) for detailed testing documentation.


# CS3103_Assignment4_Group1
AY25/26 Sem1 CS3103 group project


## Dependencies:
`aioquic`

To install dependencies, run `pip install -r requirements.txt`.  

## SSL Certificates (Automatic)
The server requires SSL certificates (`cert.pem`, `key.pem`) to run QUIC.

Our code automatically generates these files for you the first time you run the server using generate_cert.py.

> Note: If you wish to use your own custom certificates, simply replace the auto-generated `cert.pem` and `key.pem` files in the root directory.

## Run the Server
Open a terminal and start the server:

```bash
python server.py
```

## Run the Client
Open a second terminal and run the client:
```bash
python client.py 
```
The client will connect, send 100 reliable and unreliable packets to the server, and then disconnect. You will see the server's output in its terminal window as it receives packets.

## Stop Server and View Statistics
To stop the server, go to its terminal window and press `Ctrl+C`.

Upon stopping, the server will automatically print the final performance statistics (Throughput, PDR, Jitter, etc.) for both reliable and unreliable channels.

## Network Simulator
To simulate packet losses in a network we used `tc-netem`. Refer to the enclosed video for the sample run. 


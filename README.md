# CS3103_Assignment4_Group1
AY25/26 Sem1 CS3103 group project


## Dependencies:
`aioquic`

To install dependencies, run `pip install -r requirements.txt`.  

## SSL Certificates (Automatic)
The server requires SSL certificates (`cert.pem`, `key.pem`) to run QUIC.

Our code automatically generates these files for you the first time you run the server using generate_cert.py.

> Note: If you wish to use your own custom certificates, simply replace the auto-generated `cert.pem` and `key.pem` files in the root directory.

## Running the server



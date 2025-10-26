# CS3103_Assignment4_Group1
AY25/26 Sem1 CS3103 group project


Dependencies:
`aioquic`

To install dependencies, run `pip install -r requirements.txt`.  

As aioquic requires a TLS certificate for server mode, generate a self-signed certificate in the project"
example command: 
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"


"""
SSL Certificate Manager
Auto-generates self-signed certificates for QUIC connections
Used by both client and server
"""

import os
from datetime import datetime, timedelta, timezone


def generate_self_signed_cert(certfile="cert.pem", keyfile="key.pem", force=False):
    """
    Generate self-signed SSL certificate for QUIC
    
    Args:
        certfile: Path to certificate file (default: cert.pem)
        keyfile: Path to private key file (default: key.pem)
        force: If True, regenerate even if files exist
    
    Returns:
        tuple: (certfile_path, keyfile_path)
    
    Raises:
        ImportError: If cryptography library is not installed
        Exception: If certificate generation fails
    """
    # Check if certificates already exist
    if not force and os.path.exists(certfile) and os.path.exists(keyfile):
        print(f"✅ Using existing certificates: {certfile}, {keyfile}")
        
        # Check if certificates are about to expire (optional)
        check_cert_expiry(certfile)
        
        return certfile, keyfile
    
    print("🔐 Generating self-signed SSL certificates...")
    
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import ipaddress  # ← Fix: Import ipaddress module
        
        # Generate private key
        print("   📝 Generating RSA private key (2048 bits)...")
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Create certificate subject
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "SG"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Singapore"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Singapore"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NUS"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "CS3103 Assignment 4"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])
        
        # Create certificate
        print("   📜 Creating X.509 certificate...")
        now_utc = datetime.now(timezone.utc)
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            now_utc
        ).not_valid_after(
            # Valid for 365 days
            now_utc + timedelta(days=365)
        ).add_extension(
            # Add Subject Alternative Names for localhost
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),  # ← Fix: Use ipaddress module
            ]),
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        # Write private key to file
        print(f"   💾 Writing private key to {keyfile}...")
        with open(keyfile, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        
        # Set restrictive permissions on private key (Unix-like systems)
        try:
            os.chmod(keyfile, 0o600)  # Read/write for owner only
        except:
            pass  # Windows doesn't support chmod
        
        # Write certificate to file
        print(f"   💾 Writing certificate to {certfile}...")
        with open(certfile, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        print(f"✅ Successfully generated certificates!")
        print(f"   Certificate: {certfile}")
        print(f"   Private Key: {keyfile}")
        print(f"   Valid from:  {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"   Valid until: {(now_utc + timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        
        return certfile, keyfile
        
    except ImportError as e:
        print(f"\n❌ Error: Missing required library!")
        if "cryptography" in str(e):
            print("\n📦 Install with:")
            print("   pip install cryptography")
        print("\n🔧 Or generate manually with OpenSSL:")
        print(f'   openssl req -x509 -newkey rsa:2048 -keyout {keyfile} -out {certfile} -days 365 -nodes \\')
        print('     -subj "/C=SG/ST=Singapore/L=Singapore/O=NUS/OU=CS3103/CN=localhost"')
        raise
    
    except Exception as e:
        print(f"\n❌ Error generating certificates: {e}")
        import traceback
        traceback.print_exc()
        raise


def check_cert_expiry(certfile, warn_days=30):
    """
    Check if certificate is about to expire
    
    Args:
        certfile: Path to certificate file
        warn_days: Warn if expiring within this many days (default: 30)
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        
        with open(certfile, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read(), default_backend())
        
        expiry = cert.not_valid_after_utc
        days_until_expiry = (expiry - datetime.now(timezone.utc)).days
        
        if days_until_expiry < 0:
            print(f"⚠️  WARNING: Certificate expired {abs(days_until_expiry)} days ago!")
            print(f"   Run with force=True to regenerate")
        elif days_until_expiry < warn_days:
            print(f"⚠️  WARNING: Certificate expires in {days_until_expiry} days")
            print(f"   Expires: {expiry.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    except:
        pass  # Silently skip if we can't check


def ensure_certificates(certfile="cert.pem", keyfile="key.pem"):
    """
    Ensure certificates exist, generate if needed
    Convenience function for simple use cases
    
    Args:
        certfile: Path to certificate file
        keyfile: Path to private key file
    
    Returns:
        tuple: (certfile_path, keyfile_path)
    """
    return generate_self_signed_cert(certfile, keyfile, force=False)


def regenerate_certificates(certfile="cert.pem", keyfile="key.pem"):
    """
    Force regeneration of certificates
    
    Args:
        certfile: Path to certificate file
        keyfile: Path to private key file
    
    Returns:
        tuple: (certfile_path, keyfile_path)
    """
    print("🔄 Force regenerating certificates...")
    return generate_self_signed_cert(certfile, keyfile, force=True)


# -------------------- Standalone Script Mode --------------------
if __name__ == "__main__":
    """
    Can be run standalone to generate certificates
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate self-signed SSL certificates for QUIC',
        epilog='Example: python cert_manager.py --cert mycert.pem --key mykey.pem'
    )
    parser.add_argument('--cert', default='cert.pem', help='Certificate file path (default: cert.pem)')
    parser.add_argument('--key', default='key.pem', help='Private key file path (default: key.pem)')
    parser.add_argument('--force', action='store_true', help='Force regeneration even if files exist')
    parser.add_argument('--check', action='store_true', help='Only check existing certificate expiry')
    
    args = parser.parse_args()
    
    if args.check:
        if os.path.exists(args.cert):
            print(f"🔍 Checking certificate: {args.cert}")
            check_cert_expiry(args.cert, warn_days=30)
        else:
            print(f"❌ Certificate not found: {args.cert}")
    else:
        try:
            generate_self_signed_cert(args.cert, args.key, force=args.force)
            print("\n✅ Done!")
        except Exception as e:
            print(f"\n❌ Failed: {e}")
            exit(1)
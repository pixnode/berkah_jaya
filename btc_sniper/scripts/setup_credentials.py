#!/usr/bin/env python3
"""
One-time script untuk generate Polymarket API credentials.
Jalankan SEKALI sebelum live trading:
  python scripts/setup_credentials.py

Output: tampilkan POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE
yang harus disalin ke .env
"""

import asyncio

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
except ImportError:
    print("ERROR: py_clob_client is not installed.")
    print("Please install requirements first: pip install -r requirements.txt")
    exit(1)

async def setup_credentials(private_key: str, chain_id: int = 137) -> None:
    """
    Generate API credentials dari private key wallet.
    
    Langkah:
    1. Init ClobClient dengan private key
    2. Derive API credentials (sign challenge message)
    3. Set API credentials ke CLOB
    4. Print hasil ke terminal untuk disalin ke .env
    """
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=chain_id,
    )
    
    print("Deriving API credentials (ini akan signing pesan dari wallet)...")
    try:
        # Derive credentials
        creds: ApiCreds = client.create_or_derive_api_creds()
        
        print("\n" + "="*60)
        print("POLYMARKET API CREDENTIALS — SALIN KE .env")
        print("="*60)
        print(f"POLY_API_KEY={creds.api_key}")
        print(f"POLY_API_SECRET={creds.api_secret}")
        print(f"POLY_API_PASSPHRASE={creds.api_passphrase}")
        print("="*60)
        print("PENTING: Simpan credentials ini dengan aman.")
        print("Jangan commit .env ke git.")
        print("="*60 + "\n")
    except Exception as e:
        print(f"Error deriving credentials: {e}")

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # Locate .env in parent dir or current dir
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_path):
        env_path = ".env"
    
    load_dotenv(env_path)
    
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not pk:
        print("ERROR: POLYMARKET_PRIVATE_KEY tidak ditemukan di .env")
        exit(1)
    
    chain_id_str = os.getenv("POLY_CHAIN_ID", "137")
    try:
        chain_id = int(chain_id_str)
    except ValueError:
        chain_id = 137
        
    asyncio.run(setup_credentials(pk, chain_id))

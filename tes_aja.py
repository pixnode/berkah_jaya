
import os
from dotenv import load_dotenv

# Coba muat .env
load_dotenv(override=True)

print("--- DIAGNOSA .ENV ---")
print(f"GAP_THRESHOLD_DEFAULT: {os.getenv('GAP_THRESHOLD_DEFAULT')}")
print(f"GAP_THRESHOLD_LOW_VOL: {os.getenv('GAP_THRESHOLD_LOW_VOL')}")
print(f"GAP_THRESHOLD_HIGH_VOL: {os.getenv('GAP_THRESHOLD_HIGH_VOL')}")
print("---------------------")

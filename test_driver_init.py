#!/usr/bin/env python3
"""Test driver initialization."""
from src.drivers.grpc_client import DriverClient

client = DriverClient()
print("Testing Init...")
r = client.init("YouTube", "https://youtube.com")
print(f"Init result: ok={r.ok}")
if not r.ok:
    print(f"Error: {r.error}")
else:
    print("✅ Browser initialized successfully!")


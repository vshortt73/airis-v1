#!/usr/bin/env python3
"""Test database connection"""
import sys
sys.path.append('/iris-v3/')
from database import persistence

def test():
    print("Testing database connection...")
    info = persistence.get_last_message_info()
    if info:
        print(f"✓ Last message: {info['timestamp']}")
        print(f"✓ Session: {info['session_id']}")
    else:
        print("✓ No previous messages")
    print("✓ Database connection OK")

if __name__ == "__main__":
    test()

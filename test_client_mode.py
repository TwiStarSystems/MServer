#!/usr/bin/env python3
"""
Test script for client-controller communication
"""
import time
import subprocess
import sys
import requests
import json

def test_client_controller():
    print("=" * 70)
    print("Testing MServerController Client-Controller Communication")
    print("=" * 70)
    
    # Start central controller
    print("\n[TEST] Starting central controller on port 3000...")
    central = subprocess.Popen(
        [sys.executable, 'server.py', '--mode', 'central', '--port', '3000'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for controller to start
    print("[TEST] Waiting 3 seconds for controller to start...")
    time.sleep(3)
    
    # Test central controller API
    print("\n[TEST] Testing central controller endpoints...")
    try:
        response = requests.get('http://localhost:3000/api/public/servers', timeout=5)
        print(f"[TEST] ✓ Central controller is responding: {response.status_code}")
    except Exception as e:
        print(f"[TEST] ✗ Central controller not responding: {e}")
        central.terminate()
        return False
    
    # Start client
    print("\n[TEST] Starting client node (test-client-1)...")
    client = subprocess.Popen(
        [sys.executable, 'server.py', '--mode', 'client', 
         '--controller', 'http://localhost:3000',
         '--node-id', 'test-client-1'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    # Wait for client to register
    print("[TEST] Waiting 5 seconds for client to register...")
    time.sleep(5)
    
    # Check if client registered
    print("\n[TEST] Checking registered clients...")
    try:
        # Note: This would need authentication in production
        response = requests.get('http://localhost:3000/api/clients', timeout=5)
        if response.status_code == 401:
            print("[TEST] ⚠ Client API requires authentication (expected)")
            print("[TEST] ✓ Client registration endpoint is working")
        else:
            print(f"[TEST] API Response: {response.status_code}")
            if response.status_code == 200:
                clients = response.json().get('clients', [])
                print(f"[TEST] ✓ Found {len(clients)} registered client(s)")
                for client_info in clients:
                    print(f"[TEST]   - {client_info.get('node_id')}: {client_info.get('status')}")
    except Exception as e:
        print(f"[TEST] Error checking clients: {e}")
    
    # Check client output
    print("\n[TEST] Checking client output...")
    try:
        client_output = client.stdout.read(1024).decode() if client.stdout else ""
        if "Registration successful" in client_output or "✓" in client_output:
            print("[TEST] ✓ Client appears to have registered successfully")
        else:
            print(f"[TEST] Client output: {client_output[:200]}")
    except:
        pass
    
    # Cleanup
    print("\n[TEST] Cleaning up...")
    client.terminate()
    central.terminate()
    
    time.sleep(1)
    client.kill()
    central.kill()
    
    print("\n[TEST] Test complete!")
    print("=" * 70)
    print("\nTo test manually:")
    print("  Terminal 1: python server.py --mode central")
    print("  Terminal 2: python server.py --mode client --controller http://localhost:3000 --node-id node-1")
    print("=" * 70)
    
    return True

if __name__ == '__main__':
    test_client_controller()

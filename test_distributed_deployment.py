#!/usr/bin/env python3
"""
Test script for distributed server deployment feature.
Tests load balancing, node selection, and server creation across nodes.
"""

import requests
import time
import json
import sys
from datetime import datetime

CONTROLLER_URL = "http://localhost:3000"
TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = "admin123"  # Change to your actual admin password

class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    """Print a formatted header"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_success(text):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")

def print_error(text):
    """Print error message"""
    print(f"{Colors.RED}✗ {text}{Colors.END}")

def print_info(text):
    """Print info message"""
    print(f"{Colors.YELLOW}ℹ {text}{Colors.END}")

def login():
    """Login and get session cookies"""
    print_header("Authentication")
    try:
        session = requests.Session()
        response = session.post(
            f"{CONTROLLER_URL}/login",
            data={
                'username': TEST_ADMIN_USERNAME,
                'password': TEST_ADMIN_PASSWORD
            }
        )
        
        if response.status_code == 200 and 'user_id' in session.cookies:
            print_success("Logged in successfully")
            return session
        else:
            print_error(f"Login failed: {response.status_code}")
            return None
    except Exception as e:
        print_error(f"Login error: {e}")
        return None

def test_get_available_nodes(session):
    """Test getting available nodes"""
    print_header("Test 1: Get Available Nodes")
    
    try:
        response = session.get(f"{CONTROLLER_URL}/api/nodes/available")
        
        if response.status_code == 200:
            data = response.json()
            nodes = data.get('nodes', [])
            
            print_success(f"Found {len(nodes)} available node(s)")
            
            for node in nodes:
                node_id = node.get('node_id')
                node_type = node.get('node_type')
                name = node.get('name')
                status = node.get('status')
                servers = node.get('servers', 0)
                load_score = node.get('load_score', 0)
                recommended = node.get('recommended', False)
                stats = node.get('stats', {})
                
                rec_marker = " ⭐ RECOMMENDED" if recommended else ""
                
                print(f"\n  Node: {Colors.BOLD}{name}{Colors.END} ({node_id}){rec_marker}")
                print(f"    Type: {node_type}")
                print(f"    Status: {status}")
                print(f"    Servers: {servers}")
                print(f"    Load Score: {load_score:.2f}")
                print(f"    CPU: {stats.get('cpu_percent', 0):.1f}%")
                print(f"    Memory: {stats.get('memory_percent', 0):.1f}%")
                print(f"    Disk: {stats.get('disk_percent', 0):.1f}%")
            
            return nodes
        else:
            print_error(f"Failed to get nodes: {response.status_code}")
            return []
            
    except Exception as e:
        print_error(f"Error getting nodes: {e}")
        return []

def test_create_server_on_central(session):
    """Test creating a server on central controller"""
    print_header("Test 2: Create Server on Central Controller")
    
    server_config = {
        'name': f'Test-Central-{int(time.time())}',
        'serverPath': f'/tmp/test-servers/central-{int(time.time())}',
        'executable': 'paper.jar',
        'javaArgs': '-Xmx1G -Xms512M',
        'serverType': 'paper',
        'version': '1.21',
        'category': 'test',
        'targetNode': 'central'
    }
    
    try:
        print_info(f"Creating server: {server_config['name']}")
        response = session.post(
            f"{CONTROLLER_URL}/api/servers",
            json=server_config
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                server_id = data.get('serverId')
                node = data.get('node')
                print_success(f"Server created on {node}")
                print(f"  Server ID: {server_id}")
                return server_id
            else:
                print_error(f"Server creation failed: {data.get('message', 'Unknown error')}")
                return None
        else:
            print_error(f"Failed to create server: {response.status_code}")
            print(f"  Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Error creating server: {e}")
        return None

def test_create_server_with_auto(session):
    """Test creating a server with auto node selection"""
    print_header("Test 3: Create Server with Auto Load Balancing")
    
    server_config = {
        'name': f'Test-Auto-{int(time.time())}',
        'serverPath': f'/tmp/test-servers/auto-{int(time.time())}',
        'executable': 'paper.jar',
        'javaArgs': '-Xmx1G -Xms512M',
        'serverType': 'paper',
        'version': '1.21',
        'category': 'test',
        'targetNode': 'auto'
    }
    
    try:
        print_info(f"Creating server with auto node selection: {server_config['name']}")
        response = session.post(
            f"{CONTROLLER_URL}/api/servers",
            json=server_config
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                server_id = data.get('serverId', 'pending')
                node = data.get('node')
                is_pending = data.get('pending', False)
                
                print_success(f"Server creation initiated on {node}")
                print(f"  Server ID: {server_id}")
                
                if is_pending:
                    command_id = data.get('commandId')
                    print_info(f"Server creation queued (Command ID: {command_id})")
                    print_info("Client will create server when it polls for commands")
                
                return server_id
            else:
                print_error(f"Server creation failed: {data.get('message', 'Unknown error')}")
                return None
        else:
            print_error(f"Failed to create server: {response.status_code}")
            print(f"  Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Error creating server: {e}")
        return None

def test_create_server_on_client(session, node_id):
    """Test creating a server on a specific client node"""
    print_header(f"Test 4: Create Server on Client Node ({node_id})")
    
    server_config = {
        'name': f'Test-Client-{int(time.time())}',
        'serverPath': f'/tmp/test-servers/client-{int(time.time())}',
        'executable': 'paper.jar',
        'javaArgs': '-Xmx1G -Xms512M',
        'serverType': 'paper',
        'version': '1.21',
        'category': 'test',
        'targetNode': node_id
    }
    
    try:
        print_info(f"Creating server on node {node_id}: {server_config['name']}")
        response = session.post(
            f"{CONTROLLER_URL}/api/servers",
            json=server_config
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                server_id = data.get('serverId', 'pending')
                command_id = data.get('commandId')
                
                print_success(f"Server creation queued on {node_id}")
                print(f"  Server ID: {server_id}")
                print(f"  Command ID: {command_id}")
                print_info("Waiting for client to process command...")
                
                # Wait a bit for client to process
                time.sleep(8)
                
                print_info("Client should have processed the command by now")
                return server_id
            else:
                print_error(f"Server creation failed: {data.get('message', 'Unknown error')}")
                return None
        else:
            print_error(f"Failed to create server: {response.status_code}")
            print(f"  Response: {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Error creating server: {e}")
        return None

def test_load_balancing_algorithm(session, nodes):
    """Test the load balancing algorithm"""
    print_header("Test 5: Load Balancing Algorithm")
    
    if not nodes:
        print_error("No nodes available for testing")
        return
    
    print_info("Testing load calculation and node selection")
    
    # Sort nodes by load score
    sorted_nodes = sorted(nodes, key=lambda x: x.get('load_score', 999))
    
    print("\nNodes sorted by load (best to worst):")
    for i, node in enumerate(sorted_nodes, 1):
        node_id = node.get('node_id')
        name = node.get('name')
        load_score = node.get('load_score', 0)
        servers = node.get('servers', 0)
        stats = node.get('stats', {})
        
        print(f"\n  {i}. {Colors.BOLD}{name}{Colors.END} ({node_id})")
        print(f"     Load Score: {load_score:.3f}")
        print(f"     Servers: {servers}")
        print(f"     CPU: {stats.get('cpu_percent', 0):.1f}%")
        print(f"     Memory: {stats.get('memory_percent', 0):.1f}%")
    
    best_node = sorted_nodes[0]
    print(f"\n{Colors.GREEN}Best node for deployment: {best_node.get('name')} ({best_node.get('node_id')}){Colors.END}")

def run_tests():
    """Run all tests"""
    print(f"\n{Colors.BOLD}Distributed Server Deployment Test Suite{Colors.END}")
    print(f"Controller URL: {CONTROLLER_URL}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Login
    session = login()
    if not session:
        print_error("Cannot proceed without authentication")
        return False
    
    # Test 1: Get available nodes
    nodes = test_get_available_nodes(session)
    if not nodes:
        print_error("No nodes available - cannot continue tests")
        return False
    
    # Test 2: Create server on central
    central_server_id = test_create_server_on_central(session)
    
    # Test 3: Create server with auto selection
    auto_server_id = test_create_server_with_auto(session)
    
    # Test 4: Create server on client (if available)
    client_nodes = [n for n in nodes if n.get('node_type') == 'client' and n.get('status') == 'online']
    if client_nodes:
        client_node_id = client_nodes[0].get('node_id')
        client_server_id = test_create_server_on_client(session, client_node_id)
    else:
        print_header("Test 4: Create Server on Client Node")
        print_info("Skipping - no client nodes available")
        print_info("Start a client node with: python server.py --mode client --controller http://localhost:3000 --node-id test-node")
    
    # Test 5: Load balancing algorithm
    test_load_balancing_algorithm(session, nodes)
    
    # Summary
    print_header("Test Summary")
    print_success("All tests completed!")
    print_info("Check the logs and dashboard to verify server creation")
    
    return True

if __name__ == "__main__":
    try:
        success = run_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

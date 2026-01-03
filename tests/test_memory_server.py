"""
Test script for memory MCP server and tool registration
Verifies server startup and tool database registration
"""

import os
import sys
import subprocess
import time
import asyncio

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from app import config

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)

def register_tools_in_database():
    """Insert tool definitions into mcp_tools table"""
    print("\n[test_memory_server] Registering tools in database...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Read and execute SQL file
    sql_file = os.path.join(PROJECT_ROOT, 'database', 'sql', 'insert_memory_tools.sql')
    with open(sql_file, 'r') as f:
        sql = f.read()

    # Execute SQL (will show verification query results)
    cursor.execute(sql)
    conn.commit()

    # Fetch verification results
    results = cursor.fetchall()
    print(f"\n[test_memory_server] Registered {len(results)} memory tools:")
    for row in results:
        tool_name, enabled, priority, icon = row
        status = "✓ ENABLED" if enabled else "✗ DISABLED"
        print(f"  {icon} {tool_name} - {status} (priority: {priority})")

    cursor.close()
    conn.close()

    return len(results)

def verify_server_configs():
    """Verify memory server is in server_configs.py"""
    print("\n[test_memory_server] Verifying server configuration...")

    from mcp_servers.server_configs import get_server_configs, get_server_for_tool, is_tool_autonomous

    configs = get_server_configs()

    # Find memory server
    memory_server = None
    for config in configs:
        if config['name'] == 'memory':
            memory_server = config
            break

    if not memory_server:
        print("[test_memory_server] ✗ Memory server not found in configs!")
        return False

    print(f"[test_memory_server] ✓ Memory server found")
    print(f"  Command: {memory_server['command']}")
    print(f"  Script: {memory_server['args'][0]}")
    print(f"  Tools: {len(memory_server['tools'])}")

    # Verify tools
    for tool_name in memory_server['tools']:
        server = get_server_for_tool(tool_name)
        autonomous = is_tool_autonomous(tool_name)
        auto_str = "🟢 AUTONOMOUS" if autonomous else "🔴 REQUIRES CONFIRMATION"
        print(f"    - {tool_name}: {auto_str} (server: {server})")

    return True

async def test_server_startup():
    """Test that the memory server can start without errors"""
    print("\n[test_memory_server] Testing server startup...")

    server_script = os.path.join(PROJECT_ROOT, 'mcp_servers', 'memory', 'memory_server.py')

    try:
        # Run server with --help to verify it loads without import errors
        process = subprocess.run(
            ['python', server_script, '--help'],
            capture_output=True,
            timeout=5,
            env={**os.environ, 'IRIS_DB_PASSWORD': os.environ.get('IRIS_DB_PASSWORD', 'yourpassword')}
        )

        # MCP servers via stdio exit immediately without a client
        # We just need to verify no import errors occurred
        if process.returncode in [0, 2]:  # 0 = success, 2 = FastMCP --help exit code
            print("[test_memory_server] ✓ Server loads without errors")
            return True
        else:
            print(f"[test_memory_server] ✗ Server exited with unexpected code {process.returncode}")
            if process.stderr:
                print(f"  Error: {process.stderr.decode()[:500]}")
            return False

    except subprocess.TimeoutExpired:
        print(f"[test_memory_server] ✗ Server startup timed out")
        return False
    except Exception as e:
        print(f"[test_memory_server] ✗ Error testing startup: {e}")
        return False

def test_tool_execution():
    """Test tool execution via ToolManager"""
    print("\n[test_memory_server] Testing tool execution via ToolManager...")

    try:
        from mcp_servers.tool_manager import ToolManager

        # Create tool manager
        tool_manager = ToolManager()
        print(f"[test_memory_server] ✓ ToolManager created ({len(tool_manager.tools)} tools loaded)")

        # Check if memory tools are loaded
        memory_tools = [t for t in tool_manager.tools if 'memory' in t['function']['name']]
        print(f"[test_memory_server] Found {len(memory_tools)} memory tools in ToolManager")

        for tool in memory_tools:
            name = tool['function']['name']
            desc = tool['function']['description'][:60]
            print(f"    - {name}: {desc}...")

        if len(memory_tools) == 3:
            print("[test_memory_server] ✓ All 3 memory tools loaded")
            return True
        else:
            print(f"[test_memory_server] ✗ Expected 3 memory tools, found {len(memory_tools)}")
            return False

    except Exception as e:
        print(f"[test_memory_server] ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("=" * 70)
    print("MEMORY SERVER TESTS")
    print("=" * 70)

    results = {}

    try:
        # 1. Register tools in database
        count = register_tools_in_database()
        results['database_registration'] = count == 3

        # 2. Verify server configs
        results['server_configs'] = verify_server_configs()

        # 3. Test server startup (async)
        results['server_startup'] = asyncio.run(test_server_startup())

        # 4. Test tool loading via ToolManager
        results['tool_manager'] = test_tool_execution()

        # Summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)

        for test_name, passed in results.items():
            status = "✓ PASSED" if passed else "✗ FAILED"
            print(f"{test_name.replace('_', ' ').title()}: {status}")

        all_passed = all(results.values())
        print("\n" + "=" * 70)
        if all_passed:
            print("✓ ALL TESTS PASSED")
        else:
            print("✗ SOME TESTS FAILED")
        print("=" * 70)

        return all_passed

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

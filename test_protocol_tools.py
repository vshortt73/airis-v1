"""
Test Protocol Management Tools

Tests the protocol management MCP server and tool functions
"""

import os
import sys
import json
import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.tool_manager import ToolManager

# ============================================
# TEST CASES
# ============================================

async def test_protocol_list():
    """Test protocol_list tool"""
    print("\n" + "="*60)
    print("TEST: protocol_list")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_list", {})

    print(f"\nResponse:")
    print(json.dumps(response, indent=2))

    assert response["success"], "Tool manager should return success"
    result = response["result"]  # Unwrap the actual tool result

    assert result["success"], "Tool should return success"
    assert "protocols" in result, "Should return protocols list"
    assert result["count"] > 0, "Should have at least one protocol"

    print("\n✓ protocol_list test passed")


async def test_protocol_status():
    """Test protocol_status tool"""
    print("\n" + "="*60)
    print("TEST: protocol_status")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_status", {})
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    assert result["success"], "Tool should return success"
    assert "active_protocol" in result, "Should return active protocol name"
    assert "is_default" in result, "Should indicate if default"

    print("\n✓ protocol_status test passed")


async def test_protocol_activate_simple():
    """Test protocol_activate with simple request - should ask for parameters"""
    print("\n" + "="*60)
    print("TEST: protocol_activate (simple - needs more info)")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_activate", {
        "request": "activate protocol Theta"
    })
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    # Should NOT succeed immediately - should ask for parameters
    assert result["success"] == False, "Should not succeed without parameters"
    assert result["needs_more_info"] == True, "Should indicate more info needed"
    assert "duration" in result["missing_parameters"], "Should ask for duration"
    assert "passphrase" in result["missing_parameters"], "Should ask for passphrase"
    assert "prompts" in result, "Should provide prompts"

    print("\n✓ protocol_activate (needs more info) test passed")


async def test_protocol_activate_with_confirm_defaults():
    """Test protocol_activate with confirm_defaults=True"""
    print("\n" + "="*60)
    print("TEST: protocol_activate (confirm defaults)")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_activate", {
        "request": "activate protocol Theta",
        "confirm_defaults": True
    })
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    # Should succeed with defaults
    assert result["success"], "Tool should return success with confirm_defaults"
    assert result["protocol_name"] == "Theta", "Should extract protocol name"
    assert result["duration_minutes"] == 0, "Should default to permanent"
    assert result["passphrase_required"] == False, "Should default to no passphrase"

    print("\n✓ protocol_activate (confirm defaults) test passed")


async def test_protocol_activate_with_duration():
    """Test protocol_activate with duration parsing - still asks for passphrase"""
    print("\n" + "="*60)
    print("TEST: protocol_activate (with duration - asks for passphrase)")
    print("="*60)

    tool_manager = ToolManager()

    # First call - provides duration but not passphrase
    response = await tool_manager.execute_tool("protocol_activate", {
        "request": "activate protocol Professional for 8 hours"
    })
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    # Should ask for passphrase
    assert result["success"] == False, "Should not succeed without passphrase"
    assert result["needs_more_info"] == True, "Should indicate more info needed"
    assert "passphrase" in result["missing_parameters"], "Should ask for passphrase"
    assert "duration" not in result["missing_parameters"], "Should have parsed duration"

    print("\n✓ protocol_activate (with duration, asks for passphrase) test passed")


async def test_protocol_activate_complete():
    """Test protocol_activate with all parameters provided"""
    print("\n" + "="*60)
    print("TEST: protocol_activate (all parameters)")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_activate", {
        "request": "activate protocol Professional for 8 hours",
        "passphrase": "test123"  # Explicitly provide passphrase
    })
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    assert result["success"], "Tool should return success with all params"
    assert result["protocol_name"] == "Professional", "Should extract protocol name"
    assert result["duration_minutes"] == 480, "Should parse 8 hours as 480 minutes"
    assert "expires_at" in result, "Should include expiration timestamp"
    assert result["passphrase_required"] == True, "Should indicate passphrase set"

    print("\n✓ protocol_activate (all parameters) test passed")


async def test_protocol_activate_with_passphrase():
    """Test protocol_activate with passphrase parsing"""
    print("\n" + "="*60)
    print("TEST: protocol_activate (with passphrase)")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_activate", {
        "request": "activate protocol Theta for 30 minutes with passphrase \"bank teller\""
    })
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    assert result["success"], "Tool should return success"
    assert result["protocol_name"] == "Theta", "Should extract protocol name"
    assert result["duration_minutes"] == 30, "Should parse 30 minutes"
    assert result["passphrase_required"], "Should indicate passphrase required"
    assert result["passphrase_set"], "Should indicate passphrase was set"

    print("\n✓ protocol_activate (with passphrase) test passed")


async def test_protocol_deactivate_simple():
    """Test protocol_deactivate without passphrase"""
    print("\n" + "="*60)
    print("TEST: protocol_deactivate (simple)")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_deactivate", {
        "request": "deactivate protocol"
    })
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    assert result["success"], "Tool should return success"
    assert "protocol_name" in result, "Should return deactivated protocol name"

    print("\n✓ protocol_deactivate (simple) test passed")


async def test_protocol_deactivate_with_passphrase():
    """Test protocol_deactivate with passphrase"""
    print("\n" + "="*60)
    print("TEST: protocol_deactivate (with passphrase)")
    print("="*60)

    tool_manager = ToolManager()

    response = await tool_manager.execute_tool("protocol_deactivate", {
        "request": "deactivate with passphrase \"bank teller\""
    })
    result = response["result"]

    print(f"\nResult:")
    print(json.dumps(result, indent=2))

    assert result["success"], "Tool should return success"
    assert result["passphrase_provided"], "Should indicate passphrase was provided"

    print("\n✓ protocol_deactivate (with passphrase) test passed")


# ============================================
# MAIN EXECUTION
# ============================================

async def run_all_tests():
    """Run all protocol management tool tests"""
    # Run all tests
    await test_protocol_list()
    await test_protocol_status()
    await test_protocol_activate_simple()
    await test_protocol_activate_with_confirm_defaults()
    await test_protocol_activate_with_duration()
    await test_protocol_activate_complete()
    await test_protocol_activate_with_passphrase()
    await test_protocol_deactivate_simple()
    await test_protocol_deactivate_with_passphrase()

    print("\n" + "="*60)
    print("✓ ALL TESTS PASSED")
    print("="*60)
    print("\nProtocol management tools are working correctly!")
    print("You can now test them via Iris chat interface.")
    print("\nExample commands:")
    print("  - 'Iris, what protocols are available?'")
    print("  - 'Iris, activate protocol Theta for 8 hours'")
    print("  - 'Iris, check protocol status'")
    print("  - 'Iris, deactivate protocol'")


if __name__ == "__main__":
    print("="*60)
    print("PROTOCOL MANAGEMENT TOOL TESTS")
    print("="*60)
    print("\n⚠️  WARNING: These are SKELETON implementations")
    print("⚠️  Tools parse requests but do NOT change system state\n")

    try:
        asyncio.run(run_all_tests())

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

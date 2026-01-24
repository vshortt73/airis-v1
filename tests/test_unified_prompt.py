#!/usr/bin/env python3
"""
Phase 2 Unified Prompt Builder Test Script

Tests the new KV cache optimized prompt system:
1. Verifies static section is byte-identical across turns
2. Tests tool call normalization (random ID stripping)
3. Validates prompt structure and section ordering
4. Measures expected vs actual token counts

Run with: python tests/test_unified_prompt.py

Expected results:
- Static section: 100% identical across calls
- Tool calls: IDs stripped, simple format used
- Cache efficiency: 80%+ expected
"""

import os
import sys
import json
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

# Set DB password if not set
if not os.environ.get('IRIS_DB_PASSWORD'):
    print("WARNING: IRIS_DB_PASSWORD not set, using 'yourpassword'")
    os.environ['IRIS_DB_PASSWORD'] = 'yourpassword'

from core.prompt_builder import UnifiedPromptBuilder, get_active_protocol
from core.token_counter import TokenCounter


def test_static_section_consistency():
    """Test that static section is byte-identical across multiple calls"""
    print("\n" + "=" * 60)
    print("TEST 1: Static Section Consistency")
    print("=" * 60)

    builder = UnifiedPromptBuilder()
    protocol = get_active_protocol()

    # Sample tool definitions
    tools = [
        {
            "type": "function",
            "function": {
                "name": "weather_get",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "news_headlines",
                "description": "Get latest news headlines",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ]

    # Build static section multiple times
    static1 = builder.build_static_section(protocol, tools)
    static2 = builder.build_static_section(protocol, tools)
    static3 = builder.build_static_section(protocol, tools)

    # Compare
    is_identical = (static1 == static2 == static3)

    if is_identical:
        print(f"✓ PASS: Static section is byte-identical across 3 calls")
        print(f"  Static section length: {len(static1)} chars, {TokenCounter.count_tokens(static1):,} tokens")
    else:
        print(f"✗ FAIL: Static section differs between calls!")
        # Find first difference
        for i, (c1, c2) in enumerate(zip(static1, static2)):
            if c1 != c2:
                print(f"  First difference at position {i}:")
                print(f"  Call 1: ...{static1[max(0,i-20):i+20]}...")
                print(f"  Call 2: ...{static2[max(0,i-20):i+20]}...")
                break

    return is_identical


def test_tool_alphabetical_order():
    """Test that tools are sorted alphabetically"""
    print("\n" + "=" * 60)
    print("TEST 2: Tool Alphabetical Ordering")
    print("=" * 60)

    builder = UnifiedPromptBuilder()
    protocol = get_active_protocol()

    # Unsorted tools
    tools = [
        {"type": "function", "function": {"name": "zebra_tool", "description": "Z", "parameters": {}}},
        {"type": "function", "function": {"name": "alpha_tool", "description": "A", "parameters": {}}},
        {"type": "function", "function": {"name": "middle_tool", "description": "M", "parameters": {}}},
    ]

    static = builder.build_static_section(protocol, tools)

    # Check order in output
    alpha_pos = static.find("### alpha_tool")
    middle_pos = static.find("### middle_tool")
    zebra_pos = static.find("### zebra_tool")

    if alpha_pos < middle_pos < zebra_pos:
        print(f"✓ PASS: Tools are alphabetically sorted")
        print(f"  alpha_tool at position {alpha_pos}")
        print(f"  middle_tool at position {middle_pos}")
        print(f"  zebra_tool at position {zebra_pos}")
        return True
    else:
        print(f"✗ FAIL: Tools are NOT alphabetically sorted!")
        print(f"  alpha_tool at position {alpha_pos}")
        print(f"  middle_tool at position {middle_pos}")
        print(f"  zebra_tool at position {zebra_pos}")
        return False


def test_tool_call_normalization():
    """Test that tool call IDs are stripped from conversation history"""
    print("\n" + "=" * 60)
    print("TEST 3: Tool Call ID Normalization")
    print("=" * 60)

    builder = UnifiedPromptBuilder()

    # Simulated conversation with tool calls (including random IDs)
    conversation = [
        {"role": "user", "content": "What's the weather?"},
        {
            "role": "assistant",
            "content": "I'll check the weather for you.",
            "tool_calls": [
                {
                    "id": "O4ojxenbqUyZZMdcUcdL9GAbpBqhVop",  # Random ID that should be stripped
                    "type": "function",
                    "function": {"name": "weather_get", "arguments": '{"location": "Seattle"}'}
                }
            ]
        },
        {
            "role": "tool",
            "content": '{"temperature": 65, "condition": "cloudy"}',
            "tool_name": "weather_get",
            "tool_call_id": "O4ojxenbqUyZZMdcUcdL9GAbpBqhVop"  # Should also be stripped
        },
        {"role": "assistant", "content": "It's 65°F and cloudy in Seattle."}
    ]

    dynamic = builder.build_dynamic_section(conversation, "Thanks!")

    # Check that random ID is NOT in output
    has_random_id = "O4ojxenbqUyZZMdcUcdL9GAbpBqhVop" in dynamic

    # Check that normalized format IS in output
    has_normalized = "[Tools used: weather_get]" in dynamic
    has_tool_result = "Tool (weather_get):" in dynamic

    if not has_random_id and has_normalized and has_tool_result:
        print(f"✓ PASS: Tool call IDs are properly stripped")
        print(f"  - Random ID not found: ✓")
        print(f"  - Normalized format found: ✓")
        print(f"  - Tool result format correct: ✓")
        return True
    else:
        print(f"✗ FAIL: Tool call normalization issues!")
        print(f"  - Random ID not found: {'✓' if not has_random_id else '✗ (BAD: ID still present)'}")
        print(f"  - Normalized format found: {'✓' if has_normalized else '✗'}")
        print(f"  - Tool result format correct: {'✓' if has_tool_result else '✗'}")
        if has_random_id:
            print(f"\n  Dynamic section preview:")
            print(f"  {dynamic[:500]}...")
        return False


def test_full_prompt_structure():
    """Test full prompt assembly and token distribution"""
    print("\n" + "=" * 60)
    print("TEST 4: Full Prompt Structure & Token Distribution")
    print("=" * 60)

    builder = UnifiedPromptBuilder()
    protocol = get_active_protocol()

    tools = [
        {"type": "function", "function": {"name": "test_tool", "description": "Test", "parameters": {}}}
    ]

    conversation = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I'm doing well, thank you!"}
    ]

    prompt, token_report = builder.build_full_prompt(
        protocol_config=protocol,
        tool_definitions=tools,
        memories="Test memory content",
        facts="Test facts content",
        dreams="Test dream content",
        conversation_history=conversation,
        current_message="What can you help me with?"
    )

    print(f"Token Distribution:")
    print(f"  Static:      {token_report['static_tokens']:,} tokens ({token_report['static_percentage']:.1f}%)")
    print(f"  Semi-static: {token_report['semi_static_tokens']:,} tokens")
    print(f"  Dynamic:     {token_report['dynamic_tokens']:,} tokens")
    print(f"  Total:       {token_report['total_tokens']:,} tokens")
    print(f"")
    print(f"  Expected cache efficiency: {token_report['expected_cache_efficiency']:.1f}%")

    # Check section markers are present
    has_context_marker = "CONTEXT" in prompt
    has_conversation_marker = "CURRENT CONVERSATION" in prompt

    if has_context_marker and has_conversation_marker:
        print(f"\n✓ PASS: Prompt structure is correct")
        print(f"  - CONTEXT section marker: ✓")
        print(f"  - CONVERSATION section marker: ✓")
        return True
    else:
        print(f"\n✗ FAIL: Prompt structure issues!")
        print(f"  - CONTEXT section marker: {'✓' if has_context_marker else '✗'}")
        print(f"  - CONVERSATION section marker: {'✓' if has_conversation_marker else '✗'}")
        return False


def test_cache_efficiency_simulation():
    """Simulate multiple turns and check cache consistency"""
    print("\n" + "=" * 60)
    print("TEST 5: Cache Efficiency Simulation (3 turns)")
    print("=" * 60)

    builder = UnifiedPromptBuilder()
    protocol = get_active_protocol()

    tools = [
        {"type": "function", "function": {"name": "weather_get", "description": "Get weather", "parameters": {}}}
    ]

    # Simulate 3 turns with growing conversation
    prompts = []
    conversations = [
        [{"role": "user", "content": "Hello"}],
        [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"}, {"role": "user", "content": "Weather?"}],
        [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"}, {"role": "user", "content": "Weather?"}, {"role": "assistant", "content": "Let me check."}, {"role": "user", "content": "Thanks!"}]
    ]

    for i, conv in enumerate(conversations, 1):
        prompt, report = builder.build_full_prompt(
            protocol_config=protocol,
            tool_definitions=tools,
            memories="Test memory",
            facts="Test facts",
            dreams=None,
            conversation_history=conv,
            current_message=f"Turn {i} message"
        )
        prompts.append(prompt)
        print(f"Turn {i}: {report['total_tokens']:,} tokens, expected cache: {report['expected_cache_efficiency']:.1f}%")

    # Compare static portions across turns
    # Find where static section ends (at the first section delimiter)
    delimiter = "═══════════════════════════════════════════════════════════════"

    static_sections = []
    for p in prompts:
        idx = p.find(delimiter)
        if idx > 0:
            static_sections.append(p[:idx])

    if len(static_sections) == 3:
        all_match = (static_sections[0] == static_sections[1] == static_sections[2])
        if all_match:
            print(f"\n✓ PASS: Static section identical across all 3 turns")
            print(f"  Static section size: {len(static_sections[0])} chars")
            return True
        else:
            print(f"\n✗ FAIL: Static sections differ between turns!")
            return False
    else:
        print(f"\n✗ FAIL: Could not extract static sections")
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("PHASE 2: UNIFIED PROMPT BUILDER VALIDATION")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = []

    # Run tests
    results.append(("Static Section Consistency", test_static_section_consistency()))
    results.append(("Tool Alphabetical Ordering", test_tool_alphabetical_order()))
    results.append(("Tool Call Normalization", test_tool_call_normalization()))
    results.append(("Full Prompt Structure", test_full_prompt_structure()))
    results.append(("Cache Efficiency Simulation", test_cache_efficiency_simulation()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed")

    if failed == 0:
        print("\n🎉 All tests passed! Phase 2 unified prompt system is ready.")
        print("   Next step: Run Iris and monitor KV cache efficiency in logs.")
    else:
        print("\n⚠️  Some tests failed. Please review the issues above.")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

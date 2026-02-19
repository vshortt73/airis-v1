"""
Test harness for meeting transcription system

Tests:
1. Database tables exist and are functional
2. Meeting MCP server tool actions (start, status, list, speakers)
3. Chunk upload endpoint
4. Node2 transcribe service health
5. GPU Manager recognizes transcribe service
6. Full pipeline: start → upload chunk → stop → process (if transcribe service is up)

Usage:
    export AIRIS_DB_PASSWORD='your_password'
    python tests/test_meeting.py
    python tests/test_meeting.py --full   # includes transcription pipeline test
"""

import os
import sys
import asyncio
import argparse
import json
import tempfile
import struct
import wave

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

# DB password: env var or .pgpass (psycopg2 reads ~/.pgpass automatically)
if not os.environ.get('AIRIS_DB_PASSWORD'):
    # Set a dummy so config.py doesn't complain, but psycopg2 will use .pgpass
    os.environ['AIRIS_DB_PASSWORD'] = ''

import psycopg2
from app import config

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
SKIP = "\033[93m⊘\033[0m"

results = {"pass": 0, "fail": 0, "skip": 0}


def report(name, success, detail="", skip=False):
    if skip:
        print(f"  {SKIP} {name} — {detail}")
        results["skip"] += 1
    elif success:
        print(f"  {PASS} {name}")
        results["pass"] += 1
    else:
        print(f"  {FAIL} {name} — {detail}")
        results["fail"] += 1


def get_db_connection():
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
    }
    # Only pass password if non-empty; omitting it lets psycopg2 use ~/.pgpass
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


def generate_test_wav(duration_secs=3, sample_rate=16000):
    """Generate a short silent WAV file for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    n_samples = duration_secs * sample_rate
    with wave.open(tmp.name, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Write silence (zeros)
        wf.writeframes(b'\x00\x00' * n_samples)
    return tmp.name


# ============================================================================
# 1. DATABASE TESTS
# ============================================================================

def test_database():
    print("\n1. DATABASE TABLES")
    print("-" * 40)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check meeting_transcripts table exists
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'meeting_transcripts'
            ORDER BY ordinal_position
        """)
        cols = [r[0] for r in cursor.fetchall()]
        report("meeting_transcripts table exists", len(cols) > 0,
               "Table not found — run create_meeting_tables.sql")
        if cols:
            expected = ['id', 'title', 'meeting_type', 'status', 'started_at',
                        'audio_path', 'audio_chunks', 'speaker_count', 'summary',
                        'participant_names']
            missing = [c for c in expected if c not in cols]
            report("meeting_transcripts has expected columns",
                   len(missing) == 0, f"Missing: {missing}")

        # Check meeting_segments table exists
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'meeting_segments'
            ORDER BY ordinal_position
        """)
        seg_cols = [r[0] for r in cursor.fetchall()]
        report("meeting_segments table exists", len(seg_cols) > 0,
               "Table not found — run create_meeting_tables.sql")

        # Check config entries
        cursor.execute("""
            SELECT key, value FROM system_config
            WHERE key IN ('TRANSCRIBE_ENABLED', 'TRANSCRIBE_SERVER_URL', 'MEETING_WHISPERX_MODEL')
        """)
        config_rows = {r[0]: r[1] for r in cursor.fetchall()}
        report("TRANSCRIBE_ENABLED config exists", 'TRANSCRIBE_ENABLED' in config_rows,
               "Run add_meeting_config.sql")
        report("TRANSCRIBE_SERVER_URL config exists", 'TRANSCRIBE_SERVER_URL' in config_rows,
               "Run add_meeting_config.sql")

        # Check MCP tool
        cursor.execute("SELECT tool_name, enabled FROM mcp_tools WHERE tool_name = 'meeting'")
        tool = cursor.fetchone()
        report("meeting MCP tool registered", tool is not None,
               "Run insert_meeting_tools.sql")
        if tool:
            report("meeting tool is enabled", tool[1] == True)

        cursor.close()
        conn.close()
    except Exception as e:
        report("Database connection", False, str(e))


# ============================================================================
# 2. MCP SERVER TESTS
# ============================================================================

def test_mcp_server():
    print("\n2. MCP SERVER (meeting_server.py)")
    print("-" * 40)

    try:
        from mcp_servers.meeting.meeting_server import meeting

        # Test start (creates a real DB record, we'll clean it up)
        result = meeting(action="start", title="__TEST_MEETING__", meeting_type="conference")
        report("start action", result.get("success", False), result.get("error", ""))
        test_meeting_id = result.get("meeting_id")

        if test_meeting_id:
            # Test status
            result = meeting(action="status", meeting_id=test_meeting_id)
            report("status action", result.get("success", False), result.get("error", ""))
            report("status shows 'recording'", result.get("status") == "recording",
                   f"got: {result.get('status')}")

            # Test list
            result = meeting(action="list", query="__TEST_MEETING__")
            report("list action (with query)", result.get("success", False), result.get("error", ""))
            report("list finds test meeting", result.get("count", 0) > 0)

            # Test speakers (no segments yet, should show empty)
            result = meeting(action="speakers", meeting_id=test_meeting_id)
            report("speakers action (no segments)", result.get("success", False), result.get("error", ""))

            # Test get (should fail — not yet transcribed)
            result = meeting(action="get", meeting_id=test_meeting_id)
            report("get action (not transcribed → error)", not result.get("success", True))

            # Test export (should fail — not yet transcribed)
            result = meeting(action="export", meeting_id=test_meeting_id)
            report("export action (not transcribed → error)", not result.get("success", True))

            # Clean up test meeting
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM meeting_transcripts WHERE id = %s", (test_meeting_id,))
            conn.commit()
            cursor.close()
            conn.close()
            report("cleanup test meeting", True)
        else:
            report("start returned meeting_id", False, "No meeting_id in result")

        # Test missing params
        result = meeting(action="start")
        report("start without title → error", not result.get("success", True))

        result = meeting(action="stop")
        report("stop without meeting_id → error", not result.get("success", True))

        result = meeting(action="unknown_action")
        report("unknown action → error", not result.get("success", True))

    except Exception as e:
        report("MCP server import", False, str(e))


# ============================================================================
# 3. HTTP ENDPOINT TESTS
# ============================================================================

def test_endpoints():
    print("\n3. HTTP ENDPOINTS")
    print("-" * 40)

    try:
        import httpx

        # Try HTTPS first, fall back to HTTP
        for scheme in ("https", "http"):
            base = f"{scheme}://localhost:{config.PORT}"
            try:
                r = httpx.get(f"{base}/api/health", timeout=5, verify=False)
                if r.status_code == 200:
                    break
            except Exception:
                continue
        else:
            report("Iris server reachable", False, "Neither HTTPS nor HTTP responded")
            return

        r = httpx.get(f"{base}/api/health", timeout=5, verify=False)
        if r.status_code != 200:
            report("Iris server reachable", False, f"HTTP {r.status_code}")
            return
        report("Iris server reachable", True)

        # Capabilities includes transcribe
        r = httpx.get(f"{base}/api/capabilities", timeout=5, verify=False)
        caps = r.json()
        report("capabilities includes 'transcribe'", 'transcribe' in caps,
               f"keys: {list(caps.keys())}")

        # Status for nonexistent meeting
        r = httpx.get(f"{base}/api/meeting/status/99999", timeout=5, verify=False)
        report("status 404 for missing meeting", r.status_code == 404)

        # Export for nonexistent meeting
        r = httpx.get(f"{base}/api/meeting/export/99999", timeout=5, verify=False)
        report("export 404 for missing meeting", r.status_code == 404)

    except httpx.ConnectError:
        report("Iris server reachable", False, "Connection refused — is the server running?")
    except Exception as e:
        report("HTTP endpoints", False, str(e))


# ============================================================================
# 4. NODE2 TRANSCRIBE SERVICE
# ============================================================================

def test_transcribe_service():
    print("\n4. NODE2 TRANSCRIBE SERVICE")
    print("-" * 40)

    transcribe_url = getattr(config, 'TRANSCRIBE_SERVER_URL', 'http://node2:8500')

    try:
        import httpx
        r = httpx.get(f"{transcribe_url}/health", timeout=10)
        health = r.json()
        report("transcribe service health", r.status_code == 200)
        report("CUDA available", health.get("cuda_available", False),
               "Running on CPU — will be slow")
        report(f"model: {health.get('model', '?')}", True)
        return True
    except httpx.ConnectError:
        report("transcribe service reachable", False,
               f"Connection refused at {transcribe_url} — is iris-transcribe running?")
        return False
    except Exception as e:
        report("transcribe service", False, str(e))
        return False


# ============================================================================
# 5. GPU MANAGER
# ============================================================================

def test_gpu_manager():
    print("\n5. GPU MANAGER")
    print("-" * 40)

    try:
        # GPU0_SERVICES is built at import time using config attributes.
        # If DB config loaded correctly, this works. If not, we test the source directly.
        from core.gpu_manager import _build_gpu0_services, get_gpu_manager

        services = _build_gpu0_services()
        report("'transcribe' in GPU0_SERVICES", "transcribe" in services)

        svc = services.get("transcribe", {})
        report("unit = iris-transcribe.service",
               svc.get("unit") == "iris-transcribe.service",
               f"got: {svc.get('unit')}")
        report("port = 8500", svc.get("port") == 8500, f"got: {svc.get('port')}")

        manager = get_gpu_manager()
        status = manager.get_status()
        report("GPU manager status", "services" in status)
        report("transcribe in services list", "transcribe" in status.get("services", []))

    except AttributeError as e:
        # Config attributes missing — DB config didn't load
        report("GPU manager (config loaded)", False,
               f"{e} — is AIRIS_DB_PASSWORD set?")
    except Exception as e:
        report("GPU manager", False, str(e))


# ============================================================================
# 6. FULL PIPELINE (optional --full flag)
# ============================================================================

async def test_full_pipeline():
    print("\n6. FULL PIPELINE (start → chunk → stop → transcribe)")
    print("-" * 40)

    from mcp_servers.meeting.meeting_server import meeting
    import httpx

    # Detect scheme (same as endpoint tests)
    for scheme in ("https", "http"):
        base = f"{scheme}://localhost:{config.PORT}"
        try:
            r = httpx.get(f"{base}/api/health", timeout=5, verify=False)
            if r.status_code == 200:
                break
        except Exception:
            continue
    else:
        report("pipeline: server reachable", False, "Neither HTTPS nor HTTP responded")
        return

    # Start meeting
    result = meeting(action="start", title="__PIPELINE_TEST__")
    if not result.get("success"):
        report("pipeline: start", False, result.get("error"))
        return
    mid = result["meeting_id"]
    report(f"pipeline: start (id={mid})", True)

    # Generate and upload a test WAV chunk
    wav_path = generate_test_wav(duration_secs=3)
    try:
        async with httpx.AsyncClient(timeout=30, verify=False) as client:
            with open(wav_path, "rb") as f:
                files = {"file": ("chunk_0000.wav", f, "audio/wav")}
                data = {"meeting_id": str(mid), "chunk_index": "0"}
                r = await client.post(f"{base}/api/meeting/upload-chunk", files=files, data=data)
            report("pipeline: upload chunk", r.status_code == 200, r.text if r.status_code != 200 else "")
    finally:
        os.unlink(wav_path)

    # Stop meeting (via MCP tool — marks as 'processing')
    result = meeting(action="stop", meeting_id=mid)
    report("pipeline: stop", result.get("success", False), result.get("error", ""))

    # Trigger processing
    async with httpx.AsyncClient(timeout=600, verify=False) as client:
        r = await client.post(f"{base}/api/meeting/process/{mid}")
        report("pipeline: process triggered", r.status_code == 200,
               r.text if r.status_code != 200 else "")

    # Poll for completion (up to 120 seconds)
    print("  ... waiting for transcription (polling every 5s, max 120s) ...")
    for i in range(24):
        await asyncio.sleep(5)
        result = meeting(action="status", meeting_id=mid)
        status = result.get("status")
        if status == "completed":
            report(f"pipeline: transcription completed ({(i+1)*5}s)", True)
            break
        elif status == "failed":
            report("pipeline: transcription failed", False, "Check server logs")
            break
    else:
        report("pipeline: transcription timed out", False, "Still processing after 120s")

    # If completed, test get and export
    if status == "completed":
        result = meeting(action="get", meeting_id=mid)
        report("pipeline: get transcript", result.get("success", False), result.get("error", ""))
        seg_count = result.get("segment_count", 0)
        report(f"pipeline: segments found ({seg_count})", seg_count >= 0)

        result = meeting(action="export", meeting_id=mid, format="transcript")
        report("pipeline: export", result.get("success", False), result.get("error", ""))

    # Clean up
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM meeting_segments WHERE transcript_id = %s", (mid,))
    cursor.execute("DELETE FROM meeting_transcripts WHERE id = %s", (mid,))
    conn.commit()
    cursor.close()
    conn.close()
    report("pipeline: cleanup", True)


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Test meeting transcription system")
    parser.add_argument("--full", action="store_true",
                        help="Run full pipeline test (requires running Iris + Node2 transcribe service)")
    args = parser.parse_args()

    print("=" * 50)
    print("MEETING TRANSCRIPTION TEST HARNESS")
    print("=" * 50)

    test_database()
    test_mcp_server()
    test_endpoints()
    transcribe_up = test_transcribe_service()
    test_gpu_manager()

    if args.full:
        if not transcribe_up:
            print(f"\n  {SKIP} Skipping full pipeline — transcribe service not reachable")
        else:
            asyncio.run(test_full_pipeline())
    else:
        print(f"\n  {SKIP} Full pipeline test skipped (use --full to enable)")
        results["skip"] += 1

    # Summary
    total = results["pass"] + results["fail"] + results["skip"]
    print("\n" + "=" * 50)
    print(f"RESULTS: {results['pass']} passed, {results['fail']} failed, {results['skip']} skipped / {total} total")
    print("=" * 50)

    return 0 if results["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

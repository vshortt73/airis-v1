"""
Database persistence for Iris v3
Handles session management and message storage with token-aware loading
"""
from colorama import Fore, Back, Style, init
init(autoreset=True) # Resets styles after each print statement

import psycopg2
from typing import List, Dict, Optional
from datetime import datetime
import uuid
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from app import config
from core.token_counter import TokenCounter
from core.embeddings import generate_embedding

def get_db_connection():
    """Create database connection"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)

    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER
    }

    if password:
        conn_params['password'] = password

    return psycopg2.connect(**conn_params)

def get_current_chat_table() -> str:
    """
    Get the current chat history table based on active protocol

    Returns:
        'chat_history' or 'chat_history_generic'
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT current_chat_table
            FROM active_protocol
            LIMIT 1
        """)

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result and result[0]:
            return result[0]
        return 'chat_history'  # Default fallback

    except Exception as e:
        print(f"[persistence.py][get_current_chat_table] Error: {e}, using default")
        return 'chat_history'

def get_last_message_info() -> Optional[Dict]:
    """
    Get timestamp and session_id of the most recent message

    Returns:
        Dict with 'timestamp' and 'session_id', or None if no messages
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Use dynamic chat table based on active protocol
        chat_table = get_current_chat_table()

        cursor.execute(f"""
            SELECT c_timestamp, session_id
            FROM {chat_table}
            ORDER BY c_timestamp DESC
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if result:
            return {
                'timestamp': result[0],
                'session_id': str(result[1]) if result[1] else None
            }
        return None
        
    except Exception as e:
        print(f"[persistence.py][get_last_message_info] Error: {e}")
        return None

def get_or_create_session() -> str:
    """
    Get existing session if recent, or create new one based on time threshold
    
    NOTE: Session ID is for analytics/memory creation only!
    It does NOT affect conversation loading - Iris remembers across sessions.
    
    Returns:
        session_id (UUID as string)
    """
    try:
        last_msg = get_last_message_info()
        
        if last_msg and last_msg['session_id']:
            # Calculate time since last message
            time_diff = datetime.now() - last_msg['timestamp']
            minutes_since = time_diff.total_seconds() / 60
            
            if minutes_since < config.SESSION_TIMEOUT_MINUTES:
                # Continue existing session
                session_id = last_msg['session_id']
                print(f"[persistence.py][get_or_create_session] Continuing session {session_id[:8]}... (gap: {minutes_since:.1f} min)")
                return session_id
            else:
                # Time gap too large, create new session
                print(f"[persistence.py][get_or_create_session] Time gap {minutes_since:.1f} min exceeds threshold {config.SESSION_TIMEOUT_MINUTES} min - new session")
                return create_new_session()
        else:
            # No previous messages or no session_id, create new
            print(f"[persistence.py][get_or_create_session] No previous session found - creating first session")
            return create_new_session()
            
    except Exception as e:
        print(f"[persistence.py][get_or_create_session] Error determining session: {e}")
        return create_new_session()

def create_new_session() -> str:
    """Create a new session in the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        session_id = str(uuid.uuid4())
        
        cursor.execute("""
            INSERT INTO chat_sessions (session_id, start_time, end_time, message_count)
            VALUES (%s, %s, %s, %s)
        """, (session_id, datetime.now(), datetime.now(), 0))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"[persistence.py][create_new_session] Created session {session_id[:8]}...")
        return session_id
        
    except Exception as e:
        print(f"[persistence.py][create_new_session] Error creating session: {e}")
        return str(uuid.uuid4())

def save_message(session_id: str, role: str, message: str, tool_calls=None, tool_call_id=None, tool_name=None, attachments=None, sender: str = 'user') -> bool:
    """
    Save a single message to the database

    Args:
        session_id: Session UUID
        role: user, assistant, or tool
        message: Message text
        tool_calls: Optional tool calls JSONB
        tool_call_id: Optional tool call ID
        tool_name: Optional tool name
        attachments: Optional list of attachment metadata dicts or JSON string
        sender: Message sender identifier ('user', 'claude_code', 'system', etc.)

    Returns:
        True if successful
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Convert attachments list to JSON string if needed
        attachments_json = None
        if attachments:
            if isinstance(attachments, str):
                attachments_json = attachments
            elif isinstance(attachments, list):
                import json
                attachments_json = json.dumps(attachments)

        # Convert tool_calls to JSON string if needed
        tool_calls_json = None
        if tool_calls:
            if isinstance(tool_calls, str):
                tool_calls_json = tool_calls
            elif isinstance(tool_calls, (dict, list)):
                import json
                tool_calls_json = json.dumps(tool_calls)
                print(f"[persistence.py][save_message] ✓ Serialized tool_calls to JSON ({len(tool_calls_json)} chars)")

        # Generate embedding for the message
        embedding = None
        if message and message.strip():
            try:
                embedding = generate_embedding(message)
                if embedding:
                    print(f"[persistence.py][save_message] ✓ Generated embedding ({len(embedding)} dimensions)")
            except Exception as e:
                print(f"[persistence.py][save_message] ✗ Error generating embedding: {e}")

        # Use dynamic chat table based on active protocol
        chat_table = get_current_chat_table()

        cursor.execute(f"""
            INSERT INTO {chat_table} (
                role, message, c_timestamp, session_id, system_version,
                tool_calls, tool_call_id, tool_name, attachments, emb_message, sender
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (role, message, datetime.now(), session_id, '3.0', tool_calls_json, tool_call_id, tool_name, attachments_json, embedding, sender))
        
        cursor.execute("""
            UPDATE chat_sessions
            SET message_count = message_count + 1,
                end_time = %s
            WHERE session_id = %s
        """, (datetime.now(), session_id))
        
        conn.commit()
        cursor.close()
        conn.close()

        # Enhanced logging for tool-related messages
        log_details = f"{role} message ({len(message)} chars)"
        if tool_calls_json:
            log_details += f" with tool_calls"
        if tool_name:
            log_details += f" [tool: {tool_name}]"
        if tool_call_id:
            log_details += f" [call_id: {tool_call_id}]"

        print(f"[persistence.py][save_message] ✓ Saved {log_details} to session {session_id[:8]}...")

        return True

    except Exception as e:
        print(f"[persistence.py][save_message] ✗ Error saving message: {e}")
        return False


def save_summary(message_id: int, summary: str) -> bool:
    """
    Save a summary for an existing message.

    Args:
        message_id: The message ID in chat_history
        summary: The generated summary text

    Returns:
        True if successful
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        chat_table = get_current_chat_table()

        cursor.execute(f"""
            UPDATE {chat_table}
            SET summary = %s,
                summary_generated_at = %s
            WHERE id = %s
        """, (summary, datetime.now(), message_id))

        conn.commit()
        rows_updated = cursor.rowcount
        cursor.close()
        conn.close()

        if rows_updated > 0:
            print(f"[persistence.py][save_summary] ✓ Saved summary for message {message_id}")
            return True
        else:
            print(f"[persistence.py][save_summary] ✗ Message {message_id} not found")
            return False

    except Exception as e:
        print(f"[persistence.py][save_summary] ✗ Error saving summary: {e}")
        return False


async def generate_and_save_summary(message_id: int, content: str, role: str) -> Optional[str]:
    """
    Generate a summary for a message and save it to the database.

    Args:
        message_id: The message ID in chat_history
        content: The message content to summarize
        role: The message role ('user' or 'assistant')

    Returns:
        The generated summary, or None if generation failed
    """
    try:
        from core.summary_generator import generate_summary

        summary = await generate_summary(content, role)

        if summary:
            save_summary(message_id, summary)
            return summary

        return None

    except Exception as e:
        print(f"[persistence.py][generate_and_save_summary] ✗ Error: {e}")
        return None


def get_last_message_id() -> Optional[int]:
    """
    Get the ID of the most recently saved message.

    Returns:
        Message ID or None
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        chat_table = get_current_chat_table()

        cursor.execute(f"""
            SELECT id FROM {chat_table}
            ORDER BY c_timestamp DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        return row[0] if row else None

    except Exception as e:
        print(f"[persistence.py][get_last_message_id] ✗ Error: {e}")
        return None


def get_messages_needing_summaries(limit: int = 100) -> List[Dict]:
    """
    Get messages that need summaries generated.

    Args:
        limit: Maximum messages to return

    Returns:
        List of message dicts with id, content, role
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        chat_table = get_current_chat_table()
        min_length = getattr(config, 'SUMMARY_MIN_LENGTH', 50)

        cursor.execute(f"""
            SELECT id, message, role
            FROM {chat_table}
            WHERE summary IS NULL
              AND role IN ('user', 'assistant')
              AND LENGTH(message) >= %s
            ORDER BY c_timestamp DESC
            LIMIT %s
        """, (min_length, limit))

        messages = []
        for row in cursor.fetchall():
            messages.append({
                'id': row[0],
                'content': row[1],
                'role': row[2]
            })

        cursor.close()
        conn.close()

        return messages

    except Exception as e:
        print(f"[persistence.py][get_messages_needing_summaries] ✗ Error: {e}")
        return []


def load_recent_conversation(
    max_turns: int = None,
    max_tokens: int = None,
    max_messages: int = None,
    verbose_budget: int = None,
    summary_budget: int = None,
    headroom_tokens: int = 0
) -> List[Dict[str, str]]:
    """
    Load recent conversation history for context with TIERED token budgeting.

    CRITICAL: This loads across ALL sessions! Session boundaries don't limit memory.

    TIERED STRATEGY:
    1. Load recent messages in FULL (verbose) up to verbose_budget
    2. Load older messages as SUMMARIES up to summary_budget
    3. This effectively doubles usable context while keeping recent detail

    Args:
        max_turns: Ignored (kept for compatibility)
        max_tokens: Total token budget (fallback if verbose/summary not specified)
        max_messages: Max total messages (safety brake)
        verbose_budget: Token budget for recent full messages (uses VERBOSE_TOKEN_BUDGET config)
        summary_budget: Token budget for older summarized messages (uses SUMMARY_TOKEN_BUDGET config)
        headroom_tokens: Tokens to reserve for batch trim snapshot growth (reduces summary_budget)

    Returns:
        List of message dicts with 'role' and 'content'
    """
    print(f"[persistence.py][load_recent_conversation] ┌── TIERED CONVERSATION LOADING ──┐")

    # Get tiered budgets from config if not provided
    if verbose_budget is None:
        verbose_budget = getattr(config, 'VERBOSE_TOKEN_BUDGET', 18000)
    if summary_budget is None:
        summary_budget = getattr(config, 'SUMMARY_TOKEN_BUDGET', 17000)

    # Fallback to old behavior if max_tokens specified but not tiered budgets
    if max_tokens is not None and verbose_budget == 18000 and summary_budget == 17000:
        # Old-style call, use max_tokens as total
        verbose_budget = max_tokens
        summary_budget = 0
        print(f"[persistence.py] Legacy mode: {max_tokens:,} tokens (no summaries)")
    else:
        print(f"[persistence.py] Tiered budgets: {verbose_budget:,} verbose + {summary_budget:,} summary")

    # Apply headroom reduction for batch trim snapshot
    if headroom_tokens > 0:
        summary_budget = max(1000, summary_budget - headroom_tokens)
        print(f"[persistence.py] Batch trim headroom: -{headroom_tokens:,} tokens → summary_budget now {summary_budget:,}")

    if max_messages is None:
        max_messages = getattr(config, 'MAX_TOTAL_MESSAGES', 50)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Use dynamic chat table based on active protocol
        chat_table = get_current_chat_table()
        print(f"[persistence.py] Using chat table: {chat_table}")

        # TIERED LOADING: Load large batch with summaries
        batch_size = max_messages * 3  # Load more since summaries compress well

        # Load messages in DESC order (newest first) with summary column
        if chat_table == 'chat_history':
            cursor.execute("""
                SELECT ch.role, ch.message, ch.tool_calls, ch.tool_call_id, ch.tool_name,
                       ct.temporal_description, ch.attachments, ct.emotion_bias, ct.display_priority,
                       ch.c_timestamp, ch.summary, ch.sender
                FROM chat_history ch
                LEFT JOIN chat_history_with_temporal ct ON ct.id = ch.id
                ORDER BY ch.c_timestamp DESC
                LIMIT %s
            """, (batch_size,))
        else:
            # chat_history_generic - no temporal data
            cursor.execute(f"""
                SELECT role, message, tool_calls, tool_call_id, tool_name,
                       NULL as temporal_description, attachments, NULL as emotion_bias, NULL as display_priority,
                       c_timestamp, summary, sender
                FROM {chat_table}
                ORDER BY c_timestamp DESC
                LIMIT %s
            """, (batch_size,))

        all_messages = cursor.fetchall()
        cursor.close()
        conn.close()

        if not all_messages:
            print(f"[persistence.py] No conversation history found")
            return []

        print(f"[persistence.py] Fetched {len(all_messages)} recent messages from DB")

        # TIERED LOADING: Phase 1 - Verbose (full messages)
        # Phase 2 - Summaries (older messages as summaries)
        verbose_messages = []
        summary_messages = []
        verbose_tokens = 0
        summary_tokens = 0
        verbose_phase = True  # Start with verbose phase

        # SMART TRUNCATION: Tool-specific limits
        TOOL_CONTENT_LIMITS = {
            "web_search": 20000,
            "document_search": 30000,
            "pubmed_search": 20000,
            "arxiv_search": 30000,
            "url_fetch": 20000,
            "news_headlines": 15000,
            "comfyui_render": 2000,
            "vision_analysis": 5000,
        }
        DEFAULT_TOOL_CONTENT_LIMIT = 1000

        # Drive message limiting: only keep the most recent N drive messages
        MAX_DRIVE_MESSAGES = 2
        drive_count = 0

        for row in all_messages:
            role, content, tool_calls, tool_call_id, tool_name, temporal_description, attachments_json, emotion_bias, display_priority, c_timestamp, summary, sender = row

            # Limit autonomous drive system messages to prevent context flooding
            if role == "system" and content and "[AUTONOMOUS DRIVE" in content:
                drive_count += 1
                if drive_count > MAX_DRIVE_MESSAGES:
                    continue  # Skip older drive messages

            # Apply tool content limits
            if role == "tool" and content and tool_name:
                max_length = TOOL_CONTENT_LIMITS.get(tool_name, DEFAULT_TOOL_CONTENT_LIMIT)
                if len(content) > max_length:
                    original_length = len(content)
                    content = content[:max_length] + f"\n\n[...truncated {original_length - max_length} chars]"

            # Build message dict
            msg = {
                "role": role,
                "content": content or "",
                "timeframe": temporal_description or "",
                "timestamp": c_timestamp.isoformat() if c_timestamp else ""
            }

            # Add sender field if present (for contact messages, etc.)
            if sender:
                msg["sender"] = sender

            if role == "assistant" and tool_calls:
                msg["tool_calls"] = tool_calls
            elif role == "tool":
                if tool_name:
                    msg["tool_name"] = tool_name
                if tool_call_id:
                    msg["tool_call_id"] = tool_call_id

            if attachments_json:
                msg["attachments"] = attachments_json

            # Count tokens for full message
            msg_tokens = TokenCounter.count_message_tokens([msg])

            # PHASE 1: Fill verbose budget with full messages
            if verbose_phase:
                if verbose_tokens + msg_tokens <= verbose_budget:
                    verbose_messages.insert(0, msg)
                    verbose_tokens += msg_tokens
                elif verbose_tokens == 0 and msg_tokens > verbose_budget:
                    # First message exceeds entire budget — skip it, don't kill verbose phase
                    # (e.g. a huge tool result shouldn't push all real messages to summaries)
                    print(f"[persistence.py] Skipping oversized message ({msg_tokens:,} tokens > {verbose_budget:,} budget) — role={role}, continuing verbose phase")
                    continue
                else:
                    # Verbose budget genuinely full with real content, switch to summary phase
                    verbose_phase = False
                    print(f"[persistence.py] Verbose budget filled: {verbose_tokens:,}/{verbose_budget:,} tokens, {len(verbose_messages)} messages")

            # PHASE 2: Fill summary budget with summarized messages
            if not verbose_phase and summary_budget > 0:
                # Skip tool messages in summary phase (they don't have summaries)
                if role == "tool":
                    continue

                # Use summary if available, otherwise skip (or use truncated content)
                if summary:
                    summary_msg = {
                        "role": role,
                        "content": f"[Earlier] {summary}",
                        "timeframe": temporal_description or "",
                        "timestamp": c_timestamp.isoformat() if c_timestamp else "",
                        "is_summary": True
                    }
                    summary_msg_tokens = TokenCounter.count_message_tokens([summary_msg])

                    if summary_tokens + summary_msg_tokens <= summary_budget:
                        summary_messages.insert(0, summary_msg)
                        summary_tokens += summary_msg_tokens
                    else:
                        # Summary budget exhausted
                        print(f"[persistence.py] Summary budget exhausted ({summary_tokens:,}/{summary_budget:,} tokens)")
                        break

            # Safety brake
            total_messages = len(verbose_messages) + len(summary_messages)
            if total_messages >= max_messages:
                print(f"[persistence.py] Hit safety limit: {max_messages} messages")
                break

        # Combine: summaries first (older), then verbose (recent)
        selected_messages = summary_messages + verbose_messages
        total_tokens = verbose_tokens + summary_tokens

        print(f"[persistence.py] └── LOADED: {len(verbose_messages)} verbose ({verbose_tokens:,} tokens) + {len(summary_messages)} summaries ({summary_tokens:,} tokens)")
        print(f"[persistence.py]     TOTAL: {len(selected_messages)} messages, {total_tokens:,} tokens")

        return selected_messages
        
    except Exception as e:
        print(f"[persistence.py][load_recent_conversation] ✗ Error: {e}")
        return []

def get_recent_sessions(limit: int = 10) -> List[Dict]:
    """Get list of recent sessions (for analytics/UI)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT session_id, start_time, end_time, message_count, summary
            FROM chat_sessions
            WHERE system_version = '3.0' OR system_version IS NULL
            ORDER BY start_time DESC
            LIMIT %s
        """, (limit,))
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        sessions = []
        for row in results:
            sessions.append({
                'session_id': str(row[0]),
                'start_time': row[1].isoformat() if row[1] else None,
                'end_time': row[2].isoformat() if row[2] else None,
                'message_count': row[3],
                'summary': row[4]
            })
        
        return sessions
        
    except Exception as e:
        print(f"[persistence.py][get_recent_sessions] Error: {e}")
        return []

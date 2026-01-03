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

def load_recent_conversation(
    max_turns: int = None,
    max_tokens: int = None,
    max_messages: int = None
) -> List[Dict[str, str]]:
    """
    Load recent conversation history for context with DYNAMIC token budgeting

    CRITICAL: This loads across ALL sessions! Session boundaries don't limit memory.

    NEW Strategy (Dynamic):
    1. Load a large batch of recent messages (ignores turn limits)
    2. Work backwards from newest, counting tokens as we go
    3. Stop when token budget exhausted
    4. This maximizes context utilization regardless of turn count

    Args:
        max_turns: Ignored (kept for compatibility) - token budget controls loading now
        max_tokens: Token budget to fill (REQUIRED for dynamic loading)
        max_messages: Max total messages (safety brake, defaults to config.MAX_TOTAL_MESSAGES)

    Returns:
        List of message dicts with 'role' and 'content'
    """
    print(f"[persistence.py][load_recent_conversation] ┌── DYNAMIC CONVERSATION LOADING ──┐")

    if max_tokens is None:
        max_tokens = config.MAX_CONTEXT_TOKENS
        print(f"[persistence.py] WARNING: No token budget provided, using default: {max_tokens:,}")
    else:
        print(f"[persistence.py] Token budget: {max_tokens:,}")

    if max_messages is None:
        max_messages = config.MAX_TOTAL_MESSAGES

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Use dynamic chat table based on active protocol
        chat_table = get_current_chat_table()
        print(f"[persistence.py] Using chat table: {chat_table}")

        # DYNAMIC LOADING: Load large batch of recent messages (across ALL sessions)
        # We'll truncate by tokens, not turn count
        batch_size = max_messages * 2  # Load plenty of messages, we'll truncate by tokens

        # Load messages in DESC order (newest first) so we can work backwards
        if chat_table == 'chat_history':
            cursor.execute("""
                SELECT ch.role, ch.message, ch.tool_calls, ch.tool_call_id, ch.tool_name,
                       ct.temporal_description, ch.attachments, ct.emotion_bias, ct.display_priority,
                       ch.c_timestamp
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
                       c_timestamp
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

        # DYNAMIC LOADING: Work backwards from newest, counting tokens
        # Stop when we hit the token budget
        selected_messages = []
        current_tokens = 0

        for row in all_messages:
            role, content, tool_calls, tool_call_id, tool_name, temporal_description, attachments_json, emotion_bias, display_priority, c_timestamp = row

            # CRITICAL FIX: Truncate tool message content to prevent budget bloat
            # Tool results can be 600KB+, which poisons context loading
            # Keep first 1000 chars so Iris can learn from examples without consuming huge token budget
            MAX_TOOL_CONTENT_LENGTH = 1000
            if role == "tool" and content and len(content) > MAX_TOOL_CONTENT_LENGTH:
                original_length = len(content)
                content = content[:MAX_TOOL_CONTENT_LENGTH] + f"\n\n[...truncated {original_length - MAX_TOOL_CONTENT_LENGTH} chars for context efficiency]"

            # Build message dict
            msg = {
                "role": role,
                "content": content or "",
                "timeframe": temporal_description or "",
                "timestamp": c_timestamp.isoformat() if c_timestamp else ""
            }

            if role == "assistant" and tool_calls:
                msg["tool_calls"] = tool_calls
            elif role == "tool":
                if tool_name:
                    msg["tool_name"] = tool_name
                if tool_call_id:
                    msg["tool_call_id"] = tool_call_id

            if attachments_json:
                msg["attachments"] = attachments_json

            # Count tokens for this message
            msg_tokens = TokenCounter.count_message_tokens([msg])

            # Check if adding this message would exceed budget
            if current_tokens + msg_tokens > max_tokens and selected_messages:
                # Budget exhausted, stop loading
                print(f"[persistence.py] Token budget exhausted ({current_tokens:,}/{max_tokens:,} tokens)")
                break

            # Add message to selection (prepend since we're working backwards)
            selected_messages.insert(0, msg)
            current_tokens += msg_tokens

            # Safety brake: don't exceed max message count
            if len(selected_messages) >= max_messages:
                print(f"[persistence.py] Hit safety limit: {max_messages} messages")
                break

        print(f"[persistence.py] └── LOADED: {len(selected_messages)} messages, {current_tokens:,} tokens")

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
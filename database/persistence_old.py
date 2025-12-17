"""
Database persistence for Iris v3
Handles session management and message storage with token-aware loading
"""

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

def get_last_message_info() -> Optional[Dict]:
    """
    Get timestamp and session_id of the most recent message
    
    Returns:
        Dict with 'timestamp' and 'session_id', or None if no messages
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT c_timestamp, session_id
            FROM chat_history
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

def save_message(session_id: str, role: str, message: str, tool_calls=None, tool_call_id=None, tool_name=None) -> bool:
    """Save a single message to the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO chat_history (
                role, message, c_timestamp, session_id, system_version,
                tool_calls, tool_call_id, tool_name
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (role, message, datetime.now(), session_id, '3.0', tool_calls, tool_call_id, tool_name))
        
        cursor.execute("""
            UPDATE chat_sessions
            SET message_count = message_count + 1,
                end_time = %s
            WHERE session_id = %s
        """, (datetime.now(), session_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"[persistence.py][save_message] ✓ Saved {role} message ({len(message)} chars) to session {session_id[:8]}...")
        
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
    Load recent conversation history for context
    
    CRITICAL: This loads across ALL sessions! Session boundaries don't limit memory.
    
    Strategy:
    1. Load last N conversation turns (user+assistant pairs) from entire history
    2. Include all tool messages within those turns
    3. Apply token limit (truncate if exceeds limit)
    4. Apply message count limit (safety brake)
    
    Args:
        max_turns: Max conversation turns (defaults to config.MAX_CONVERSATION_TURNS)
        max_tokens: Max tokens (defaults to config.MAX_CONTEXT_TOKENS)
        max_messages: Max total messages (defaults to config.MAX_TOTAL_MESSAGES)
        
    Returns:
        List of message dicts with 'role' and 'content'
    """
    print(f"[persistence.py][load_recent_conversation] Loading conversation history...")
    
    if max_turns is None:
        max_turns = config.MAX_CONVERSATION_TURNS
    if max_tokens is None:
        max_tokens = config.MAX_CONTEXT_TOKENS
    if max_messages is None:
        max_messages = config.MAX_TOTAL_MESSAGES
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Step 1: Get timestamps of last N user+assistant messages (ACROSS ALL SESSIONS!)
        cursor.execute("""
            SELECT c_timestamp
            FROM chat_history
            WHERE role IN ('user', 'assistant')
            ORDER BY c_timestamp DESC
            LIMIT %s
        """, (max_turns * 2,))  # *2 for user+assistant pairs, NO session_id filter!
        
        results = cursor.fetchall()
        
        if not results:
            cursor.close()
            conn.close()
            print(f"[persistence.py][load_recent_conversation] No conversation history found")
            return []
        
        # Get oldest timestamp from those messages
        oldest_timestamp = results[-1][0]
        
        # Step 2: Load ALL messages (including tools) since that timestamp
        cursor.execute("""
             SELECT ch.role, ch.message, ch.tool_calls, ch.tool_call_id, ch.tool_name, ct.temporal_description
            FROM chat_history ch
            left join chat_history_with_temporal ct on ct.id = ch.id
            WHERE ch.c_timestamp >= %s
            ORDER BY ch.c_timestamp ASC
        """, (oldest_timestamp,))  # Still NO session_id filter!
        
        all_messages = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Step 3: Build message list with proper Ollama format
        messages = []
        for row in all_messages:
            role, content, tool_calls, tool_call_id, tool_name, temporal_description = row
            
            msg = {
                "role": role,
                "content": content or "",
                "timeframe" : temporal_description or "",
            }
            
            if role == "assistant" and tool_calls:
                msg["tool_calls"] = tool_calls
            elif role == "tool":
                if tool_name:
                    msg["tool_name"] = tool_name
                if tool_call_id:
                    msg["tool_call_id"] = tool_call_id
            
            messages.append(msg)
        
        # Step 4: Apply message count limit
        if len(messages) > max_messages:
            print(f"[persistence.py][load_recent_conversation] Truncating {len(messages)} to {max_messages} messages (safety limit)")
            messages = messages[-max_messages:]
        
        # Step 5: Apply token limit
        total_tokens = TokenCounter.count_message_tokens(messages)
        
        if total_tokens > max_tokens:
            print(f"[persistence.py][load_recent_conversation] Truncating {total_tokens} tokens to {max_tokens} token limit")
            
            while total_tokens > max_tokens and len(messages) > 1:
                messages.pop(0)
                total_tokens = TokenCounter.count_message_tokens(messages)
        
        print(f"[persistence.py][load_recent_conversation] ✓ Loaded {len(messages)} messages, {total_tokens} tokens")
        
        return messages
        
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
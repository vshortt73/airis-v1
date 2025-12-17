"""
Conversation history management for Iris v3
In-memory representation of recent conversation loaded from database
"""

from typing import List, Dict, Optional
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from app import config
from database import persistence

class ConversationHistory:
    """Manages conversation history with database persistence"""
    
    def __init__(self, enable_persistence: bool = True):
        """
        Initialize conversation history
        
        Loads recent conversation from database (across all sessions!)
        
        Args:
            enable_persistence: If True, save/load from database
        """
        self.messages: List[Dict[str, str]] = []
        self.enable_persistence = enable_persistence
        
        if enable_persistence:
            # Get/create session (for analytics, not for loading!)
            self.session_id = persistence.get_or_create_session()
            
            # Load recent conversation (ACROSS ALL SESSIONS!)
            self.messages = persistence.load_recent_conversation()
            
            if self.messages:
                print(f"[conversation.py][__init__] ✓ Loaded {len(self.messages)} messages into working memory")
            else:
                print(f"[conversation.py][__init__] ✓ Starting fresh conversation")
        else:
            self.session_id = None
            print(f"[conversation.py][__init__] In-memory only (no persistence)")
    
    def add_user_message(self, content: str) -> None:
        """Add a user message to history"""
        self.messages.append({
            "role": "user",
            "content": content
        })
        
        print(f"[conversation.py][add_user_message] ✓ Added user message ({len(content)} chars)")
        
        if self.enable_persistence and self.session_id:
            persistence.save_message(self.session_id, "user", content)
    
    def add_assistant_message(self, content: str, tool_calls=None) -> None:
        """Add an assistant message to history"""
        msg = {
            "role": "assistant",
            "content": content
        }
        
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        self.messages.append(msg)
        
        print(f"[conversation.py][add_assistant_message] ✓ Added assistant message ({len(content)} chars)")
        
        if self.enable_persistence and self.session_id:
            persistence.save_message(self.session_id, "assistant", content, tool_calls=tool_calls)
    
    def add_tool_message(self, content: str, tool_name: str, tool_call_id: str = None) -> None:
        """Add a tool result message to history"""
        msg = {
            "role": "tool",
            "content": content,
            "tool_name": tool_name
        }
        
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        
        self.messages.append(msg)
        
        print(f"[conversation.py][add_tool_message] ✓ Added tool message from {tool_name} ({len(content)} chars)")
        
        if self.enable_persistence and self.session_id:
            persistence.save_message(
                self.session_id, 
                "tool", 
                content, 
                tool_call_id=tool_call_id,
                tool_name=tool_name
            )
    
    def get_messages(self) -> List[Dict[str, str]]:
        """Get all messages in working memory"""
        return self.messages.copy()
    
    def reload_from_database(self) -> None:
        """Reload conversation history from database"""
        if self.enable_persistence:
            self.messages = persistence.load_recent_conversation()
            print(f"[conversation.py][reload_from_database] ✓ Reloaded {len(self.messages)} messages")
    
    def get_message_count(self) -> int:
        """Get number of messages in working memory"""
        return len(self.messages)
    
    def get_session_id(self) -> Optional[str]:
        """Get current session ID (for analytics only)"""
        return self.session_id
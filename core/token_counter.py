"""
Token counting for Iris v3
Uses tiktoken for fast, accurate token estimation
"""

import json
import tiktoken
from typing import List, Dict

class TokenCounter:
    """Fast token counting using tiktoken"""
    
    _encoder = None
    
    @classmethod
    def get_encoder(cls):
        """Lazy load encoder (only once)"""
        if cls._encoder is None:
            print(f"[token_counter.py][get_encoder] Loading tiktoken encoder")
            cls._encoder = tiktoken.get_encoding("cl100k_base")
        return cls._encoder
    
    @classmethod
    def count_tokens(cls, text: str) -> int:
        """
        Count tokens in text
        
        Args:
            text: String to count tokens for
            
        Returns:
            Token count
        """
        if not text:
            return 0
        encoder = cls.get_encoder()
        return len(encoder.encode(text, disallowed_special=()))
    
    @classmethod
    def count_message_tokens(cls, messages: List[Dict[str, str]]) -> int:
        """
        Count tokens for a list of messages.
        Counts ALL fields the LLM will see: content, tool_calls, tool_call_id, tool_name.

        Args:
            messages: List of message dicts

        Returns:
            Total token count including formatting overhead
        """
        total = 0
        for msg in messages:
            content = msg.get('content') or ''
            formatted = f"{msg.get('role', 'user')}: {content}\n"
            total += cls.count_tokens(formatted)

            # Count tool_calls JSON (assistant messages requesting tool use)
            if 'tool_calls' in msg and msg['tool_calls']:
                try:
                    tc = msg['tool_calls']
                    tc_str = json.dumps(tc) if not isinstance(tc, str) else tc
                    total += cls.count_tokens(tc_str)
                except (TypeError, ValueError):
                    total += 50  # conservative estimate on serialization failure

            # Count tool_call_id and tool_name (tool result messages)
            if 'tool_call_id' in msg:
                total += cls.count_tokens(str(msg['tool_call_id']))
            if 'tool_name' in msg:
                total += cls.count_tokens(str(msg['tool_name']))

        # Per-message chat formatting overhead
        total += len(messages) * 3

        return total
    
    @classmethod
    def count_tokens_by_role(cls, messages: List[Dict[str, str]]) -> Dict[str, int]:
        """
        Count tokens grouped by role
        
        Args:
            messages: List of message dicts
            
        Returns:
            Dict mapping role -> token count
        """
        role_tokens = {}
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            tokens = cls.count_tokens(content)
            role_tokens[role] = role_tokens.get(role, 0) + tokens
        return role_tokens

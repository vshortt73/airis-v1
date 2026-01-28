"""
Conversation history management for Iris v3
In-memory representation of recent conversation loaded from database
"""

from typing import List, Dict, Optional
import os
import sys
import re
import time
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
from app import config
from database import persistence
from core import attachments


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

        # System component cache for performance optimization
        # Caches system prompt components that don't change during a conversation
        self.system_cache = {
            'protocol': None,
            'instructions': None,
            'traits': None,
            'facts': None,
            'dreams': None,
            'dream_truths': None,
            'last_refresh': None
        }
        self.cache_ttl = 300  # 5 minutes TTL for system components

        # Fast reactive memory cache (per-turn)
        # Prevents re-running expensive embedding generation within same turn
        self.fast_memory_cache = {}
        self.turn_id = 0  # Increment on each user message to invalidate cache

        # Prompt Snapshot for KV cache optimization (batch trim)
        # Freezes the assembled messages list for N turns so the LLM prefix stays byte-identical
        self.snapshot = None              # Frozen List[Dict] — complete messages list sent to LLM
        self.snapshot_turn_base = 0       # turn_id when snapshot was created
        self.snapshot_token_count = 0     # Running token count of snapshot
        self.snapshot_spoiled = False     # Set True by spoiler events (e.g., trait modify)
        self.snapshot_budget = None       # Budget report dict from snapshot creation
        
        if enable_persistence:
            # Get/create session (for analytics, not for loading!)
            self.session_id = persistence.get_or_create_session()

            # Load recent conversation (ACROSS ALL SESSIONS!)
            # Use tiered loading: verbose (recent) + summaries (older)
            from app import config
            verbose_budget = getattr(config, 'VERBOSE_TOKEN_BUDGET', 3000)
            summary_budget = getattr(config, 'SUMMARY_TOKEN_BUDGET', 17000)
            max_messages = getattr(config, 'MAX_TOTAL_MESSAGES', 50)

            self.messages = persistence.load_recent_conversation(
                verbose_budget=verbose_budget,
                summary_budget=summary_budget,
                max_messages=max_messages
            )

            if self.messages:
                print(f"[conversation.py][__init__] ✓ Loaded {len(self.messages)} messages into working memory")
            else:
                print(f"[conversation.py][__init__] ✓ Starting fresh conversation")
        else:
            self.session_id = None
            print(f"[conversation.py][__init__] In-memory only (no persistence)")
    
    def add_user_message(self, content: str, images: Optional[List[str]] = None, sender: str = 'user') -> None:
        """
        Add a user message to history

        Args:
            content: Message text
            images: Optional list of base64-encoded images (with or without data URI)
            sender: Message sender identifier ('user' for Victor, 'claude_code' for Claude, etc.)
        """
        # Increment turn ID to invalidate fast memory cache
        self.turn_id += 1
        self.fast_memory_cache = {}

        msg = {
            "role": "user",
            "content": content
        }

        # Handle image attachments
        attachment_metadata = []
        if images and self.session_id:
            print(f"[conversation.py][add_user_message] Processing {len(images)} image(s)...")
            for idx, image_base64 in enumerate(images):
                try:
                    # Save image to disk and get metadata
                    metadata = attachments.save_base64_image(
                        session_id=self.session_id,
                        base64_string=image_base64,
                        is_user_upload=True,
                        filename=f"user_upload_{idx}.png"
                    )
                    attachment_metadata.append(metadata)
                    print(f"[conversation.py][add_user_message]   ✓ Saved image {idx+1}: {metadata['path']}")
                except Exception as e:
                    print(f"[conversation.py][add_user_message]   ✗ Error saving image {idx+1}: {e}")

            # Add attachment info to message for in-memory storage
            if attachment_metadata:
                msg["attachments"] = attachments.serialize_attachments(attachment_metadata)

        # Add message to in-memory conversation
        self.messages.append(msg)

        image_info = f" with {len(images)} image(s)" if images else ""
        print(f"[conversation.py][add_user_message] ✓ Added user message ({len(content)} chars{image_info})")

        # Save to database
        if self.enable_persistence and self.session_id:
            persistence.save_message(
                self.session_id,
                "user",
                content,
                attachments=attachment_metadata if attachment_metadata else None,
                sender=sender
            )

            # Trigger background summary generation for long messages
            self._trigger_summary_generation(content, "user")

    def add_assistant_message(self, content: str, tool_calls=None, images: Optional[List[str]] = None, sender: str = 'assistant') -> None:
        """
        Add an assistant message to history

        Args:
            content: Message text
            tool_calls: Optional tool calls JSONB
            images: Optional list of base64-encoded images (generated by tools)
            sender: Message sender identifier (default 'assistant' for Iris)
        """
        msg = {
            "role": "assistant",
            "content": content
        }

        if tool_calls:
            msg["tool_calls"] = tool_calls

        # Handle generated image attachments
        attachment_metadata = []
        if images and self.session_id:
            print(f"[conversation.py][add_assistant_message] Processing {len(images)} generated image(s)...")
            for idx, image_base64 in enumerate(images):
                try:
                    metadata = attachments.save_base64_image(
                        session_id=self.session_id,
                        base64_string=image_base64,
                        is_user_upload=False,  # This is generated content
                        filename=f"generated_{idx}.png"
                    )
                    attachment_metadata.append(metadata)
                    print(f"[conversation.py][add_assistant_message]   ✓ Saved generated image {idx+1}: {metadata['path']}")
                except Exception as e:
                    print(f"[conversation.py][add_assistant_message]   ✗ Error saving image {idx+1}: {e}")

            if attachment_metadata:
                msg["attachments"] = attachments.serialize_attachments(attachment_metadata)

        self.messages.append(msg)

        image_info = f" with {len(images)} image(s)" if images else ""
        print(f"[conversation.py][add_assistant_message] ✓ Added assistant message ({len(content)} chars{image_info})")

        if self.enable_persistence and self.session_id:
            persistence.save_message(
                self.session_id,
                "assistant",
                content,
                tool_calls=tool_calls,
                attachments=attachment_metadata if attachment_metadata else None,
                sender=sender
            )

            # Trigger background summary generation for long messages
            self._trigger_summary_generation(content, "assistant")

    def _trigger_summary_generation(self, content: str, role: str) -> None:
        """
        Trigger async summary generation in the background.
        Does not block - summary is generated asynchronously.
        """
        try:
            min_length = getattr(persistence.config, 'SUMMARY_MIN_LENGTH', 50)
            if not content or len(content) < min_length:
                return

            # Get the message ID we just saved
            message_id = persistence.get_last_message_id()
            if not message_id:
                return

            # Spawn background task for summary generation
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # If we're in an async context, create a task
                loop.create_task(self._generate_summary_async(message_id, content, role))
                print(f"[conversation.py] Spawned summary generation for message {message_id}")
            except RuntimeError:
                # No running loop - we're in sync context, skip for now
                # Summaries will be backfilled later
                pass

        except Exception as e:
            # Don't let summary generation errors affect the main flow
            print(f"[conversation.py] Summary generation trigger error (non-fatal): {e}")

    async def _generate_summary_async(self, message_id: int, content: str, role: str) -> None:
        """Generate summary asynchronously"""
        try:
            await persistence.generate_and_save_summary(message_id, content, role)
        except Exception as e:
            print(f"[conversation.py] Background summary generation error: {e}")

    def add_tool_message(self, content: str, tool_name: str, tool_call_id: str = None, images: Optional[List[str]] = None) -> None:
        """
        Add a tool result message to history

        Args:
            content: Tool result text
            tool_name: Name of tool that was called
            tool_call_id: Optional call ID for correlation
            images: Optional list of base64-encoded images (tool outputs like ComfyUI)
        """
        msg = {
            "role": "tool",
            "content": content,
            "tool_name": tool_name
        }

        if tool_call_id:
            msg["tool_call_id"] = tool_call_id

        # Handle tool-generated image attachments (e.g., ComfyUI output)
        attachment_metadata = []
        if images and self.session_id:
            print(f"[conversation.py][add_tool_message] Processing {len(images)} tool output image(s)...")
            for idx, image_base64 in enumerate(images):
                try:
                    metadata = attachments.save_base64_image(
                        session_id=self.session_id,
                        base64_string=image_base64,
                        is_user_upload=False,
                        filename=f"{tool_name}_{idx}.png"
                    )
                    attachment_metadata.append(metadata)
                    print(f"[conversation.py][add_tool_message]   ✓ Saved {tool_name} output {idx+1}: {metadata['path']}")
                except Exception as e:
                    print(f"[conversation.py][add_tool_message]   ✗ Error saving image {idx+1}: {e}")

            if attachment_metadata:
                msg["attachments"] = attachments.serialize_attachments(attachment_metadata)

        self.messages.append(msg)

        image_info = f" with {len(images)} image(s)" if images else ""
        print(f"[conversation.py][add_tool_message] ✓ Added tool message from {tool_name} ({len(content)} chars{image_info}) \n {content}")

        if self.enable_persistence and self.session_id:
            persistence.save_message(
                self.session_id,
                "tool",
                content,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                attachments=attachment_metadata if attachment_metadata else None
            )
    
    def get_messages(self) -> List[Dict[str, str]]:
        """Get all messages in working memory"""
        return self.messages.copy()
    
    def reload_from_database(self) -> None:
        """Reload conversation history from database"""
        if self.enable_persistence:
            from app import config
            verbose_budget = getattr(config, 'VERBOSE_TOKEN_BUDGET', 3000)
            summary_budget = getattr(config, 'SUMMARY_TOKEN_BUDGET', 17000)
            max_messages = getattr(config, 'MAX_TOTAL_MESSAGES', 50)

            self.messages = persistence.load_recent_conversation(
                verbose_budget=verbose_budget,
                summary_budget=summary_budget,
                max_messages=max_messages
            )
            print(f"[conversation.py][reload_from_database] ✓ Reloaded {len(self.messages)} messages")
    
    def get_message_count(self) -> int:
        """Get number of messages in working memory"""
        return len(self.messages)
    
    def get_session_id(self) -> Optional[str]:
        """Get current session ID (for analytics only)"""
        return self.session_id

    # ── Prompt Snapshot (KV Cache Batch Trim) ──────────────────────────

    def should_rebuild_snapshot(self) -> bool:
        """
        Determine if the prompt snapshot needs a full rebuild.

        Returns True when:
        - Feature disabled (legacy behavior)
        - No snapshot exists yet
        - Spoiler event fired (e.g., trait modification)
        - N user turns have elapsed since snapshot creation
        - Token headroom exhausted
        """
        from app import config

        if not getattr(config, 'BATCH_TRIM_ENABLED', False):
            return True

        if self.snapshot is None:
            return True

        if self.snapshot_spoiled:
            print(f"[conversation.py][snapshot] Snapshot spoiled — forcing rebuild")
            return True

        batch_size = getattr(config, 'BATCH_TRIM_SIZE', 5)
        turns_since = self.turn_id - self.snapshot_turn_base
        if turns_since >= batch_size:
            print(f"[conversation.py][snapshot] Batch size reached ({turns_since}/{batch_size}) — rebuilding")
            return True

        max_context = getattr(config, 'OLLAMA_CONTEXT_WINDOW', 32768)
        response_budget = getattr(config, 'RESPONSE_GENERATION_BUDGET', 2500)
        if self.snapshot_token_count >= (max_context - response_budget):
            print(f"[conversation.py][snapshot] Token headroom exhausted ({self.snapshot_token_count:,}/{max_context:,}) — rebuilding")
            return True

        return False

    def append_to_snapshot(self, msg: Dict) -> None:
        """
        Append a formatted message to the active snapshot and update token count.

        Args:
            msg: Message dict matching assemble_full_context() format
                 (role, content, and optional tool_calls/tool_name/tool_call_id)
        """
        if self.snapshot is not None:
            self.snapshot.append(msg)
            from core.token_counter import TokenCounter
            msg_tokens = TokenCounter.count_message_tokens([msg])
            self.snapshot_token_count += msg_tokens

    def invalidate_snapshot(self, reason: str = "unknown") -> None:
        """
        Mark the snapshot as spoiled so it will be rebuilt on the next turn.

        Args:
            reason: Human-readable reason for invalidation (for logging)
        """
        self.snapshot_spoiled = True
        print(f"[conversation.py][snapshot] SPOILED: {reason} — will rebuild on next context assembly")

    # ── End Prompt Snapshot ─────────────────────────────────────────────

    def get_system_components(self, force_refresh: bool = False) -> Dict:
        """
        Get cached system prompt components or refresh if needed

        Caches components that don't change frequently:
        - Protocol settings
        - System instructions
        - Character traits
        - Short-term facts
        - Dreams
        - Dream truths

        Args:
            force_refresh: Force reload from database

        Returns:
            Dictionary with cached system components
        """
        now = time.time()
        cache_expired = (
            force_refresh or
            not self.system_cache['last_refresh'] or
            (now - self.system_cache['last_refresh']) > self.cache_ttl
        )

        if cache_expired:
            print(f"[conversation.py][get_system_components] Refreshing system component cache...")
            # Import here to avoid circular dependency
            from core.system_prompt import (
                get_active_protocol,
                get_system_prompt,
                get_trait_list,
                get_short_term_facts,
                get_latest_dream,
                get_dream_truths
            )

            self.system_cache = {
                'protocol': get_active_protocol(),
                'instructions': None,  # Will be loaded with protocol
                'traits': get_trait_list(),
                'facts': get_short_term_facts(limit=15),
                'dreams': get_latest_dream(),
                'dream_truths': get_dream_truths(limit=5, max_days=7),
                'last_refresh': now
            }

            # Load instructions with the cached protocol
            self.system_cache['instructions'] = get_system_prompt(self.system_cache['protocol'])

            print(f"[conversation.py][get_system_components] ✓ System cache refreshed")
        else:
            cache_age = int(now - self.system_cache['last_refresh'])
            print(f"[conversation.py][get_system_components] Using cached system components (age: {cache_age}s)")

        return self.system_cache

    def get_fast_memory_cache(self, key: str) -> Optional[str]:
        """
        Get cached fast reactive memory result for this turn

        Args:
            key: Cache key (typically the user message)

        Returns:
            Cached context string or None
        """
        return self.fast_memory_cache.get(key)

    def set_fast_memory_cache(self, key: str, value: str) -> None:
        """
        Cache fast reactive memory result for this turn

        Args:
            key: Cache key (typically the user message)
            value: Context string to cache
        """
        self.fast_memory_cache[key] = value


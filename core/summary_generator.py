"""
Summary Generator Service

Generates concise summaries of conversation messages using a small, fast model
(Mistral 7B on node2) for tiered context loading.

This allows the system to load more conversation history by using summaries
for older messages while keeping recent messages in full detail.
"""

import os
import sys
import asyncio
import httpx
from typing import Optional, Dict, Any
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config

# Mistral endpoint on node2 (same as sentiment analysis)
MISTRAL_URL = getattr(config, 'MISTRAL_URL', 'http://node2:11437/v1/chat/completions')

# Summary generation prompt
SUMMARY_SYSTEM_PROMPT = """You are a concise summarizer. Summarize the given message in approximately 50 tokens.
Write in first person natural prose, no bullets or emoji.
Preserve: key facts discussed, decisions or recommendations made, questions asked, and emotional tone.
Be as concise as possible while retaining essential meaning."""

# Minimum message length to generate summary (shorter messages don't need summarization)
DEFAULT_MIN_LENGTH = 50


class SummaryGenerator:
    """
    Generates summaries for conversation messages using Mistral 7B.

    Usage:
        generator = SummaryGenerator()
        summary = await generator.generate_summary("Long message content here...")
    """

    def __init__(self, mistral_url: str = None, min_length: int = None):
        self.mistral_url = mistral_url or MISTRAL_URL
        self.min_length = min_length or getattr(config, 'SUMMARY_MIN_LENGTH', DEFAULT_MIN_LENGTH)
        self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        """Close the HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def should_summarize(self, content: str) -> bool:
        """
        Check if content should be summarized.

        Short messages don't benefit from summarization.
        """
        if not content:
            return False
        return len(content.strip()) >= self.min_length

    async def generate_summary(self, content: str, role: str = "assistant") -> Optional[str]:
        """
        Generate a summary for the given message content.

        Args:
            content: The message content to summarize
            role: The role of the message ("user" or "assistant")

        Returns:
            Summary string, or None if summarization failed or wasn't needed
        """
        if not self.should_summarize(content):
            return None

        try:
            client = await self._get_client()

            # Truncate very long content to fit within Mistral's context window
            # With 8192 ctx, reserve ~300 tokens for system prompt + response
            # ~4 chars per token = ~31,000 chars max
            max_content_chars = 30000
            if len(content) > max_content_chars:
                content = content[:max_content_chars] + "... [truncated for summarization]"

            # Adjust prompt based on role
            if role == "user":
                user_prompt = f"Summarize what the user said:\n\n{content}"
            else:
                user_prompt = f"Summarize what I (the assistant) said:\n\n{content}"

            request_body = {
                "messages": [
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": 100,  # ~50 tokens for summary + some buffer
                "temperature": 0.3,  # Low temperature for consistent summaries
                "stream": False
            }

            response = await client.post(
                self.mistral_url,
                json=request_body
            )

            if response.status_code != 200:
                print(f"[summary_generator] ✗ Mistral error: {response.status_code}")
                return None

            data = response.json()
            summary = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            if summary:
                # Clean up the summary
                summary = summary.strip()
                # Remove any leading "Summary:" or similar prefixes
                for prefix in ["Summary:", "Summary -", "I "]:
                    if summary.startswith(prefix) and prefix != "I ":
                        summary = summary[len(prefix):].strip()

                print(f"[summary_generator] ✓ Generated summary ({len(summary)} chars) for {len(content)} char message")
                return summary

            return None

        except httpx.RequestError as e:
            print(f"[summary_generator] ✗ Connection error: {e}")
            return None
        except Exception as e:
            print(f"[summary_generator] ✗ Error: {e}")
            return None

    async def generate_summaries_batch(self, messages: list) -> Dict[int, str]:
        """
        Generate summaries for multiple messages in parallel.

        Args:
            messages: List of dicts with 'id', 'content', 'role' keys

        Returns:
            Dict mapping message ID to summary
        """
        results = {}

        # Filter messages that need summarization
        to_summarize = [
            msg for msg in messages
            if self.should_summarize(msg.get('content', ''))
        ]

        if not to_summarize:
            return results

        print(f"[summary_generator] Generating {len(to_summarize)} summaries...")

        # Process in parallel with semaphore to limit concurrency
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests

        async def summarize_with_limit(msg):
            async with semaphore:
                summary = await self.generate_summary(
                    msg.get('content', ''),
                    msg.get('role', 'assistant')
                )
                return msg.get('id'), summary

        tasks = [summarize_with_limit(msg) for msg in to_summarize]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for result in completed:
            if isinstance(result, Exception):
                print(f"[summary_generator] ✗ Batch error: {result}")
                continue
            msg_id, summary = result
            if summary:
                results[msg_id] = summary

        print(f"[summary_generator] ✓ Generated {len(results)}/{len(to_summarize)} summaries")
        return results


# Singleton instance
_generator = None


def get_summary_generator() -> SummaryGenerator:
    """Get the singleton summary generator instance"""
    global _generator
    if _generator is None:
        _generator = SummaryGenerator()
    return _generator


async def generate_summary(content: str, role: str = "assistant") -> Optional[str]:
    """
    Convenience function to generate a summary.

    Args:
        content: Message content to summarize
        role: Message role ("user" or "assistant")

    Returns:
        Summary string or None
    """
    generator = get_summary_generator()
    return await generator.generate_summary(content, role)


# ============================================================================
# CLI for testing
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test summary generation")
    parser.add_argument("--text", type=str, help="Text to summarize")
    parser.add_argument("--role", type=str, default="assistant", help="Message role")
    args = parser.parse_args()

    async def test():
        generator = SummaryGenerator()

        if args.text:
            text = args.text
        else:
            # Default test text
            text = """I've been thinking about how we could improve the memory system.
            The current approach loads all messages verbatim, which limits how much history
            we can include in the context window. I think we should implement a tiered
            approach where recent messages are kept in full detail, but older messages
            are stored as summaries. This would effectively double our usable context
            while maintaining the most important information from past conversations.
            What do you think about this approach?"""

        print(f"\nOriginal ({len(text)} chars):")
        print(text)
        print()

        summary = await generator.generate_summary(text, args.role)

        if summary:
            print(f"Summary ({len(summary)} chars):")
            print(summary)
        else:
            print("Failed to generate summary")

        await generator.close()

    asyncio.run(test())

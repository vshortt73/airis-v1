"""
Server-side sentence extraction and batching for TTS/video routing.

Ports the browser's TTSQueue sentence extraction logic to Python for server-side
processing. This eliminates the wasteful round-trip where text goes:
  Server → Browser → Server → XTTS/FLOAT → Browser

Now it's:
  Server → XTTS/FLOAT → Browser (audio/video)
  Server → Browser (text only)
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

from app.api.tts_normalizer import normalize_for_tts


class OutputMode(Enum):
    """Output mode for TTS/video routing"""
    TEXT = "text"      # No TTS, just text
    AUDIO = "audio"    # TTS audio only
    VIDEO = "video"    # Full video with lip-sync


@dataclass
class TextBatch:
    """A batch of text ready for TTS/video processing"""
    text: str
    token_estimate: int
    sentence_count: int
    batch_index: int


class SentenceProcessor:
    """
    Server-side sentence extraction and batching.

    Mirrors the browser's TTSQueue logic for extracting complete sentences
    from streaming text and batching them for efficient TTS processing.

    Usage:
        processor = SentenceProcessor()

        # Feed chunks as they stream from LLM
        for chunk in llm_stream:
            batches = processor.add_chunk(chunk, is_video_mode=False)
            for batch in batches:
                await send_to_tts(batch.text)

        # Flush remaining text at end of stream
        final_batches = processor.finalize(is_video_mode=False)
        for batch in final_batches:
            await send_to_tts(batch.text)
    """

    # Batch size thresholds
    MAX_TOKENS = 375          # XTTS max is 400, use 375 for safety
    AUDIO_FLUSH_TOKENS = 75   # Flush early for faster first-audio
    AUDIO_FLUSH_SENTENCES = 2 # Flush after 2 sentences for responsiveness

    # Video adaptive batching - start small, ramp up as buffer builds
    # FLOAT renders 2-3x faster than real-time, so:
    # - Chunk 0: ~3 sec video, renders in ~1-1.5s, gives fast first-video
    # - Chunk 1: ~5-6 sec video, renders in ~2-3s, we have 3s buffer from chunk 0
    # - Chunk 2+: ~10+ sec video, renders in ~4-5s, we have 8+ sec buffer
    VIDEO_FLUSH_TOKENS_RAMP = [
        40,   # Chunk 0: ~30 words, ~3 seconds of speech
        80,   # Chunk 1: ~60 words, ~5-6 seconds
        120,  # Chunk 2: ~90 words, ~8-9 seconds
        200,  # Chunk 3+: ~150 words, ~12-15 seconds (capped by MAX_TOKENS)
    ]
    VIDEO_FLUSH_SENTENCES_RAMP = [
        1,    # Chunk 0: Just 1 sentence for speed
        2,    # Chunk 1: 2 sentences
        3,    # Chunk 2: 3 sentences
        5,    # Chunk 3+: Up to 5 sentences
    ]

    def __init__(self):
        self.partial_sentence = ''    # Buffer for incomplete sentences
        self.processed_text = ''      # Track what we've already processed
        self.sentence_batch: List[str] = []  # Batch sentences before sending
        self.batch_index = 0          # Track batch number for sequencing

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Uses words * 1.3 as a reasonable approximation.
        This matches the browser's estimation for consistency.
        """
        words = len(text.strip().split())
        return int(words * 1.3)

    def clean_markdown(self, text: str) -> str:
        """
        Clean markdown formatting from text before TTS.

        Removes:
        - Bold/italic markers
        - Headers
        - Links (keeps text)
        - Code blocks
        - Inline code
        - List markers
        - Emojis
        - IP addresses (converts to spoken format)
        """
        # Remove markdown bold/italic
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)  # ***bold italic***
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)      # **bold**
        text = re.sub(r'\*(.+?)\*', r'\1', text)          # *italic*
        text = re.sub(r'__(.+?)__', r'\1', text)          # __bold__
        text = re.sub(r'_(.+?)_', r'\1', text)            # _italic_

        # Remove markdown headers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

        # Remove markdown horizontal rules
        text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\*\*\*+$', '', text, flags=re.MULTILINE)

        # Remove markdown links but keep text
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

        # Replace markdown code blocks with a spoken indicator
        text = re.sub(r'```[\s\S]*?```', ' - you can see the code in our conversation - ', text)

        # Remove inline code (don't speak variable names)
        text = re.sub(r'`[^`]+`', '', text)

        # Remove markdown list markers
        text = re.sub(r'^[\*\-\+]\s+', '', text, flags=re.MULTILINE)

        # Remove Unicode emojis (they don't speak well)
        # Matches emoji ranges
        text = re.sub(r'[\U0001F300-\U0001F9FF]', '', text)

        # Remove text-based emoticons
        text = re.sub(r'[:\;]-?[\)\(DPpOo\[\]\/\\|3<>]|<3|XD|xD', '', text)

        # Replace IP addresses with spoken format
        text = re.sub(
            r'\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b',
            r'\1 dot \2 dot \3 dot \4',
            text
        )

        return text

    def clean_text_for_tts(self, text: str) -> str:
        """
        Final cleaning pass for text going to TTS.

        Removes remaining markdown artifacts, normalizes whitespace,
        and converts technical terms for proper pronunciation.
        """
        text = text.replace('**', '')        # Bold
        text = text.replace('*', '')         # Italic
        text = text.replace('_', ' ')        # Underscores to spaces
        text = text.replace('`', '')         # Code backticks
        text = re.sub(r'#+', '', text)       # Hash marks
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Links - keep text
        text = re.sub(r'[\s\n]+', ' ', text)  # Collapse whitespace
        text = text.strip()

        # Normalize technical terms for proper pronunciation
        # (GPU names, acronyms, storage units, etc.)
        text = normalize_for_tts(text)

        return text

    def extract_sentences(self, text: str) -> List[str]:
        """
        Extract complete sentences from text.

        Uses improved sentence detection that avoids splitting on:
        - Numbers in lists (1., 2., 3.)
        - Decimals (3.14, 2.0)
        - Abbreviations (Dr., Mr., etc.)

        Only splits on sentence-ending punctuation followed by space + capital letter.
        """
        # Clean markdown first
        text = self.clean_markdown(text)

        sentences = []

        # Split on . ! ? but be smart about it
        # Match sentence ending punctuation followed by space and capital letter, or end of string
        parts = re.split(r'([.!?]+(?:\s+(?=[A-Z])|$))', text)

        current_sentence = ''
        for part in parts:
            if not part:
                continue

            current_sentence += part

            # If this part ends with sentence punctuation, consider it complete
            if re.search(r'[.!?]+$', part.strip()):
                trimmed = current_sentence.strip()
                # Ignore very short "sentences" like just numbers
                if len(trimmed) > 2 and not re.match(r'^\d+\.?$', trimmed):
                    sentences.append(trimmed)
                current_sentence = ''

        # Add any remaining text
        if len(current_sentence.strip()) > 2:
            sentences.append(current_sentence.strip())

        return [s for s in sentences if s]

    def add_chunk(self, chunk: str, is_video_mode: bool = False) -> List[TextBatch]:
        """
        Add a text chunk and extract/queue sentences.

        Args:
            chunk: New text chunk from LLM stream
            is_video_mode: If True, use smaller batch sizes for smooth video

        Returns:
            List of TextBatch objects ready for TTS/video processing
        """
        batches = []

        # Accumulate the chunk
        self.partial_sentence += chunk

        # Find the last sentence terminator followed by space or end of string
        # This gives us the boundary between complete and incomplete text
        # Match: .!? followed by space(s) and capital letter, or .!? at end
        match = None
        for m in re.finditer(r'[.!?]+(?:\s+(?=[A-Z])|\s*$)', self.partial_sentence):
            match = m

        if match:
            # We have at least one complete sentence
            complete_part = self.partial_sentence[:match.end()]
            remaining_part = self.partial_sentence[match.end():]

            # Extract and queue complete sentences
            sentences = self.extract_sentences(complete_part)
            for sentence in sentences:
                trimmed = sentence.strip()
                if trimmed and trimmed not in self.processed_text:
                    batch = self._queue_sentence(trimmed, is_video_mode)
                    if batch:
                        batches.append(batch)
                    self.processed_text += ' ' + trimmed

            # Keep the remaining (incomplete) part in the buffer
            # This preserves the original spacing
            self.partial_sentence = remaining_part

        return batches

    def _get_video_thresholds(self) -> tuple:
        """
        Get adaptive video thresholds based on current batch index.

        Returns (flush_tokens, flush_sentences) for the current batch.
        Starts small for fast first-video, ramps up as buffer builds.
        """
        idx = min(self.batch_index, len(self.VIDEO_FLUSH_TOKENS_RAMP) - 1)
        return (
            self.VIDEO_FLUSH_TOKENS_RAMP[idx],
            self.VIDEO_FLUSH_SENTENCES_RAMP[idx]
        )

    def _queue_sentence(self, sentence: str, is_video_mode: bool) -> Optional[TextBatch]:
        """
        Add sentence to batch, flush when ready.

        Returns a TextBatch if the batch is ready to be flushed, None otherwise.
        """
        self.sentence_batch.append(sentence)

        # Calculate current batch tokens
        batch_text = ' '.join(self.sentence_batch)
        token_count = self.estimate_tokens(batch_text)

        # Flush conditions vary based on mode
        if token_count >= self.MAX_TOKENS:
            # Remove the last sentence that pushed us over
            last_sentence = self.sentence_batch.pop()

            # Flush the batch without the last sentence
            batch = self._flush_batch()

            # Start new batch with the sentence that didn't fit
            if last_sentence:
                self.sentence_batch = [last_sentence]

            return batch
        elif is_video_mode:
            # VIDEO MODE: Adaptive thresholds - start small, ramp up
            flush_tokens, flush_sentences = self._get_video_thresholds()
            if token_count >= flush_tokens or len(self.sentence_batch) >= flush_sentences:
                print(f"[SentenceProcessor] VIDEO batch {self.batch_index}: {token_count} tokens, "
                      f"{len(self.sentence_batch)} sentences (threshold: {flush_tokens}/{flush_sentences})")
                return self._flush_batch()
        elif token_count >= self.AUDIO_FLUSH_TOKENS or \
             len(self.sentence_batch) >= self.AUDIO_FLUSH_SENTENCES:
            # AUDIO MODE: Normal flush at comfortable batch size
            return self._flush_batch()

        return None

    def _flush_batch(self) -> Optional[TextBatch]:
        """
        Flush current batch and return as TextBatch.
        """
        if not self.sentence_batch:
            return None

        raw_batch_text = ' '.join(self.sentence_batch)
        batch_text = self.clean_text_for_tts(raw_batch_text)
        token_count = self.estimate_tokens(batch_text)

        # Skip if cleaned text is empty
        if not batch_text:
            self.sentence_batch = []
            return None

        batch = TextBatch(
            text=batch_text,
            token_estimate=token_count,
            sentence_count=len(self.sentence_batch),
            batch_index=self.batch_index
        )

        self.batch_index += 1
        self.sentence_batch = []

        return batch

    def finalize(self, is_video_mode: bool = False) -> List[TextBatch]:
        """
        Called when streaming is complete to flush any remaining text.

        Args:
            is_video_mode: If True, use smaller batch sizes

        Returns:
            List of remaining TextBatch objects
        """
        batches = []

        # Queue any remaining partial sentence
        if self.partial_sentence.strip():
            remaining = self.partial_sentence.strip()
            if remaining not in self.processed_text:
                batch = self._queue_sentence(remaining, is_video_mode)
                if batch:
                    batches.append(batch)
                self.processed_text += ' ' + remaining

        # Flush any remaining batched sentences
        final_batch = self._flush_batch()
        if final_batch:
            batches.append(final_batch)

        self.partial_sentence = ''

        return batches

    def reset(self):
        """Reset for new message (clears all buffers)."""
        self.partial_sentence = ''
        self.processed_text = ''
        self.sentence_batch = []
        self.batch_index = 0

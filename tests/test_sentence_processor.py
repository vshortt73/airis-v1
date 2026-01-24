"""
Tests for server-side sentence processor.

Run with: python -m pytest tests/test_sentence_processor.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sentence_processor import SentenceProcessor, OutputMode, TextBatch


class TestSentenceExtraction:
    """Test sentence extraction accuracy"""

    def test_simple_sentences(self):
        """Basic sentence extraction"""
        processor = SentenceProcessor()
        batches = processor.add_chunk("Hello there. How are you? I'm doing great!", is_video_mode=False)

        # With default thresholds, this might not flush immediately
        # Finalize to get all batches
        final_batches = processor.finalize(is_video_mode=False)
        all_batches = batches + final_batches

        # Should have at least one batch
        assert len(all_batches) >= 1

        # Combine all text
        all_text = ' '.join(b.text for b in all_batches)
        assert 'Hello there' in all_text
        assert 'How are you' in all_text

    def test_partial_sentence_buffering(self):
        """Partial sentences should be buffered"""
        processor = SentenceProcessor()

        # First chunk - incomplete sentence
        batches1 = processor.add_chunk("This is the beginning", is_video_mode=False)

        # Should not flush incomplete sentence
        assert len(batches1) == 0

        # Complete the sentence
        batches2 = processor.add_chunk(" of a long sentence.", is_video_mode=False)

        # Check buffers
        final = processor.finalize(is_video_mode=False)
        all_batches = batches1 + batches2 + final

        all_text = ' '.join(b.text for b in all_batches)
        assert 'This is the beginning of a long sentence' in all_text

    def test_number_not_split(self):
        """Numbers like 3.14 shouldn't split sentences"""
        processor = SentenceProcessor()

        batches = processor.add_chunk("The value is 3.14 and that's final.", is_video_mode=False)
        final = processor.finalize(is_video_mode=False)
        all_batches = batches + final

        all_text = ' '.join(b.text for b in all_batches)
        # Should keep 3.14 together
        assert '3 dot 14' in all_text or '3.14' in all_text


class TestBatchSizes:
    """Test batch size thresholds"""

    def test_video_mode_smaller_batches(self):
        """Video mode should produce smaller batches"""
        # Create text with multiple sentences
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence."

        # Audio mode
        audio_processor = SentenceProcessor()
        audio_batches = audio_processor.add_chunk(text, is_video_mode=False)
        audio_final = audio_processor.finalize(is_video_mode=False)
        audio_all = audio_batches + audio_final

        # Video mode
        video_processor = SentenceProcessor()
        video_batches = video_processor.add_chunk(text, is_video_mode=True)
        video_final = video_processor.finalize(is_video_mode=True)
        video_all = video_batches + video_final

        # Video mode should produce more batches (smaller chunks)
        assert len(video_all) >= len(audio_all)


class TestMarkdownCleaning:
    """Test markdown cleaning"""

    def test_bold_italic_removal(self):
        """Bold and italic markers should be removed"""
        processor = SentenceProcessor()

        batches = processor.add_chunk("This is **bold** and *italic* text.", is_video_mode=False)
        final = processor.finalize(is_video_mode=False)
        all_batches = batches + final

        all_text = ' '.join(b.text for b in all_batches)
        assert '**' not in all_text
        assert '*' not in all_text
        assert 'bold' in all_text
        assert 'italic' in all_text

    def test_code_block_replacement(self):
        """Code blocks should be replaced with spoken indicator"""
        processor = SentenceProcessor()

        batches = processor.add_chunk("Here is code: ```python\nprint('hello')```", is_video_mode=False)
        final = processor.finalize(is_video_mode=False)
        all_batches = batches + final

        all_text = ' '.join(b.text for b in all_batches)
        assert '```' not in all_text
        assert 'code' in all_text.lower()

    def test_emoji_removal(self):
        """Emojis should be removed"""
        processor = SentenceProcessor()

        batches = processor.add_chunk("Hello there! 😀 How are you?", is_video_mode=False)
        final = processor.finalize(is_video_mode=False)
        all_batches = batches + final

        all_text = ' '.join(b.text for b in all_batches)
        # Should not contain the emoji
        assert '😀' not in all_text

    def test_ip_address_spoken(self):
        """IP addresses should be converted to spoken format"""
        processor = SentenceProcessor()

        batches = processor.add_chunk("The server is at 192.168.1.1 for now.", is_video_mode=False)
        final = processor.finalize(is_video_mode=False)
        all_batches = batches + final

        all_text = ' '.join(b.text for b in all_batches)
        assert '192 dot 168 dot 1 dot 1' in all_text


class TestStreamingBehavior:
    """Test streaming chunk handling"""

    def test_chunk_by_chunk(self):
        """Simulate streaming LLM output"""
        processor = SentenceProcessor()

        # Simulate streaming chunks
        chunks = ["This ", "is ", "a ", "test. ", "Another ", "sentence. ", "And ", "one ", "more."]

        all_batches = []
        for chunk in chunks:
            batches = processor.add_chunk(chunk, is_video_mode=False)
            all_batches.extend(batches)

        final = processor.finalize(is_video_mode=False)
        all_batches.extend(final)

        # Should have captured all text
        all_text = ' '.join(b.text for b in all_batches)
        assert 'This is a test' in all_text
        assert 'Another sentence' in all_text

    def test_reset_clears_buffers(self):
        """Reset should clear all buffers"""
        processor = SentenceProcessor()

        processor.add_chunk("Partial sentence without", is_video_mode=False)
        processor.reset()

        # After reset, should start fresh
        batches = processor.add_chunk("New sentence here.", is_video_mode=False)
        final = processor.finalize(is_video_mode=False)
        all_batches = batches + final

        all_text = ' '.join(b.text for b in all_batches)
        # Should not contain the pre-reset text
        assert 'Partial' not in all_text
        assert 'New sentence' in all_text


class TestTokenEstimation:
    """Test token estimation"""

    def test_token_estimate(self):
        """Token estimation should be reasonable"""
        processor = SentenceProcessor()

        # 10 words * 1.3 = 13 tokens
        estimate = processor.estimate_tokens("one two three four five six seven eight nine ten")
        assert 10 <= estimate <= 20

    def test_empty_text(self):
        """Empty text should have 0 tokens"""
        processor = SentenceProcessor()
        estimate = processor.estimate_tokens("")
        assert estimate == 0


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])

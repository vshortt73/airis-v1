"""
Document Chunker - Hybrid semantic chunking with token limits
Splits documents by natural boundaries while enforcing token constraints
"""

import os
import sys
from typing import List, Optional
from dataclasses import dataclass
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from core.token_counter import TokenCounter
from backend.knowledge.extractors import ExtractedDocument


@dataclass
class Chunk:
    """Document chunk with metadata"""
    text: str
    chunk_index: int
    token_count: int
    chunk_type: str  # 'text', 'code', 'heading', etc.
    section_title: Optional[str]
    language: Optional[str]
    line_start: Optional[int]
    line_end: Optional[int]
    char_start: int
    char_end: int


class DocumentChunker:
    """Handles hybrid semantic chunking"""

    def __init__(self):
        self.token_counter = TokenCounter()

    def chunk_document(
        self,
        document: ExtractedDocument,
        max_tokens: int = None,
        overlap_tokens: int = None,
        min_tokens: int = None
    ) -> List[Chunk]:
        """
        Chunk document using hybrid semantic approach

        Algorithm:
        1. Split by natural boundaries (headings, paragraphs, functions)
        2. If chunk > max_tokens: recursively split further
        3. Add overlap between chunks
        4. Filter chunks < min_tokens

        Args:
            document: ExtractedDocument to chunk
            max_tokens: Maximum tokens per chunk (default from config)
            overlap_tokens: Token overlap between chunks (default from config)
            min_tokens: Minimum chunk size (default from config)

        Returns:
            List of Chunk objects
        """
        max_tokens = max_tokens or config.KNOWLEDGE_MAX_CHUNK_TOKENS
        overlap_tokens = overlap_tokens or config.KNOWLEDGE_CHUNK_OVERLAP_TOKENS
        min_tokens = min_tokens or config.KNOWLEDGE_MIN_CHUNK_TOKENS

        # Determine chunking strategy based on file type
        file_type = document.metadata.get('file_type', 'text')

        if file_type == 'code':
            chunks = self._chunk_code(document, max_tokens, overlap_tokens)
        elif file_type == 'markdown':
            chunks = self._chunk_markdown(document, max_tokens, overlap_tokens)
        else:
            chunks = self._chunk_text(document, max_tokens, overlap_tokens)

        # Filter out chunks that are too small
        chunks = [c for c in chunks if c.token_count >= min_tokens]

        # Add chunk indices
        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i

        print(f"[chunker][chunk_document] ✓ Created {len(chunks)} chunks from {len(document.text)} chars")

        return chunks

    def _chunk_code(self, document: ExtractedDocument, max_tokens: int, overlap_tokens: int) -> List[Chunk]:
        """
        Chunk code files by logical boundaries

        Strategy: Try to keep functions/classes intact
        """
        chunks = []
        text = document.text
        sections = document.sections
        language = document.metadata.get('language', 'text')

        if not sections:
            # No sections found - fall back to paragraph chunking
            return self._chunk_text(document, max_tokens, overlap_tokens)

        # Try to chunk by sections (functions/classes)
        current_section_idx = 0
        char_pos = 0

        for i, section in enumerate(sections):
            # Find section boundaries
            if i + 1 < len(sections):
                next_section = sections[i + 1]
                # Estimate section end (simplified - could be improved with AST)
                section_text = text[char_pos:]
                # Take text until next section or end
                lines = text.split('\n')
                start_line = section.get('line_number', 1) - 1
                end_line = next_section.get('line_number', len(lines)) - 1
                section_text = '\n'.join(lines[start_line:end_line])
            else:
                section_text = text[char_pos:]

            # Check if section fits in one chunk
            token_count = self.token_counter.count_tokens(section_text)

            if token_count <= max_tokens:
                # Section fits - create single chunk
                chunk = Chunk(
                    text=section_text,
                    chunk_index=len(chunks),
                    token_count=token_count,
                    chunk_type='code',
                    section_title=section.get('title'),
                    language=language,
                    line_start=section.get('line_number'),
                    line_end=section.get('line_number', 1) + section_text.count('\n'),
                    char_start=char_pos,
                    char_end=char_pos + len(section_text)
                )
                chunks.append(chunk)
            else:
                # Section too large - split by statements/lines
                sub_chunks = self._split_large_text(
                    section_text,
                    max_tokens,
                    overlap_tokens,
                    chunk_type='code',
                    section_title=section.get('title'),
                    language=language,
                    char_offset=char_pos
                )
                chunks.extend(sub_chunks)

            char_pos += len(section_text)

        return chunks

    def _chunk_markdown(self, document: ExtractedDocument, max_tokens: int, overlap_tokens: int) -> List[Chunk]:
        """
        Chunk markdown by heading hierarchy

        Strategy: Keep sections under headings together
        """
        chunks = []
        text = document.text
        sections = document.sections

        if not sections:
            # No headings - fall back to paragraph chunking
            return self._chunk_text(document, max_tokens, overlap_tokens)

        # Split by sections
        lines = text.split('\n')

        for i, section in enumerate(sections):
            start_line = section.get('line_number', 1) - 1

            # Find end of section (next heading of same or higher level, or end of document)
            end_line = len(lines)
            if i + 1 < len(sections):
                next_section = sections[i + 1]
                next_level = next_section.get('level', 6)
                current_level = section.get('level', 1)

                if next_level <= current_level:
                    end_line = next_section.get('line_number', len(lines)) - 1

            # Extract section text
            section_text = '\n'.join(lines[start_line:end_line])
            token_count = self.token_counter.count_tokens(section_text)

            if token_count <= max_tokens:
                # Section fits
                chunk = Chunk(
                    text=section_text,
                    chunk_index=len(chunks),
                    token_count=token_count,
                    chunk_type='text',
                    section_title=section.get('title'),
                    language=None,
                    line_start=start_line + 1,
                    line_end=end_line,
                    char_start=sum(len(line) + 1 for line in lines[:start_line]),
                    char_end=sum(len(line) + 1 for line in lines[:end_line])
                )
                chunks.append(chunk)
            else:
                # Section too large - split by paragraphs
                char_offset = sum(len(line) + 1 for line in lines[:start_line])
                sub_chunks = self._split_large_text(
                    section_text,
                    max_tokens,
                    overlap_tokens,
                    chunk_type='text',
                    section_title=section.get('title'),
                    language=None,
                    char_offset=char_offset
                )
                chunks.extend(sub_chunks)

        return chunks

    def _chunk_text(self, document: ExtractedDocument, max_tokens: int, overlap_tokens: int) -> List[Chunk]:
        """
        Chunk plain text by paragraphs

        Strategy: Split on double newlines (paragraphs)
        """
        text = document.text

        # Split by paragraphs
        paragraphs = re.split(r'\n\s*\n', text)
        chunks = []
        current_text = ""
        current_tokens = 0
        char_pos = 0

        for paragraph in paragraphs:
            para_tokens = self.token_counter.count_tokens(paragraph)

            if para_tokens > max_tokens:
                # Single paragraph too large - split by sentences
                if current_text:
                    # Save accumulated text first
                    chunk = Chunk(
                        text=current_text,
                        chunk_index=len(chunks),
                        token_count=current_tokens,
                        chunk_type='text',
                        section_title=None,
                        language=None,
                        line_start=None,
                        line_end=None,
                        char_start=char_pos - len(current_text),
                        char_end=char_pos
                    )
                    chunks.append(chunk)
                    current_text = ""
                    current_tokens = 0

                # Split large paragraph
                sub_chunks = self._split_large_text(
                    paragraph,
                    max_tokens,
                    overlap_tokens,
                    chunk_type='text',
                    section_title=None,
                    language=None,
                    char_offset=char_pos
                )
                chunks.extend(sub_chunks)
                char_pos += len(paragraph) + 2  # +2 for \n\n

            elif current_tokens + para_tokens <= max_tokens:
                # Add to current chunk
                if current_text:
                    current_text += "\n\n" + paragraph
                else:
                    current_text = paragraph
                current_tokens += para_tokens
                char_pos += len(paragraph) + 2

            else:
                # Would exceed max - save current and start new
                if current_text:
                    chunk = Chunk(
                        text=current_text,
                        chunk_index=len(chunks),
                        token_count=current_tokens,
                        chunk_type='text',
                        section_title=None,
                        language=None,
                        line_start=None,
                        line_end=None,
                        char_start=char_pos - len(current_text),
                        char_end=char_pos
                    )
                    chunks.append(chunk)

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_text, overlap_tokens)
                current_text = overlap_text + "\n\n" + paragraph if overlap_text else paragraph
                current_tokens = self.token_counter.count_tokens(current_text)
                char_pos += len(paragraph) + 2

        # Add final chunk
        if current_text:
            chunk = Chunk(
                text=current_text,
                chunk_index=len(chunks),
                token_count=current_tokens,
                chunk_type='text',
                section_title=None,
                language=None,
                line_start=None,
                line_end=None,
                char_start=char_pos - len(current_text),
                char_end=char_pos
            )
            chunks.append(chunk)

        return chunks

    def _split_large_text(
        self,
        text: str,
        max_tokens: int,
        overlap_tokens: int,
        chunk_type: str,
        section_title: Optional[str],
        language: Optional[str],
        char_offset: int
    ) -> List[Chunk]:
        """
        Split large text that exceeds max_tokens

        Splits by sentences, then by words if needed
        """
        chunks = []

        # Split by sentences
        sentences = re.split(r'([.!?]+\s+)', text)
        # Rejoin sentence with its punctuation
        sentences = [''.join(sentences[i:i+2]) for i in range(0, len(sentences), 2)]

        current_text = ""
        current_tokens = 0
        current_char_start = char_offset

        for sentence in sentences:
            sent_tokens = self.token_counter.count_tokens(sentence)

            if sent_tokens > max_tokens:
                # Even single sentence too large - split by words (last resort)
                words = sentence.split()
                for word in words:
                    word_tokens = self.token_counter.count_tokens(word)

                    if current_tokens + word_tokens <= max_tokens:
                        current_text += word + " "
                        current_tokens += word_tokens
                    else:
                        # Save current chunk
                        if current_text:
                            chunk = Chunk(
                                text=current_text.strip(),
                                chunk_index=len(chunks),
                                token_count=current_tokens,
                                chunk_type=chunk_type,
                                section_title=section_title,
                                language=language,
                                line_start=None,
                                line_end=None,
                                char_start=current_char_start,
                                char_end=current_char_start + len(current_text)
                            )
                            chunks.append(chunk)

                        # Start new with overlap
                        overlap_text = self._get_overlap_text(current_text, overlap_tokens)
                        current_text = overlap_text + " " + word if overlap_text else word
                        current_tokens = self.token_counter.count_tokens(current_text)
                        current_char_start += len(current_text) - len(overlap_text)

            elif current_tokens + sent_tokens <= max_tokens:
                current_text += sentence
                current_tokens += sent_tokens

            else:
                # Save current chunk
                if current_text:
                    chunk = Chunk(
                        text=current_text.strip(),
                        chunk_index=len(chunks),
                        token_count=current_tokens,
                        chunk_type=chunk_type,
                        section_title=section_title,
                        language=language,
                        line_start=None,
                        line_end=None,
                        char_start=current_char_start,
                        char_end=current_char_start + len(current_text)
                    )
                    chunks.append(chunk)

                # Start new with overlap
                overlap_text = self._get_overlap_text(current_text, overlap_tokens)
                current_text = overlap_text + sentence if overlap_text else sentence
                current_tokens = self.token_counter.count_tokens(current_text)
                current_char_start += len(current_text) - len(overlap_text)

        # Add final chunk
        if current_text:
            chunk = Chunk(
                text=current_text.strip(),
                chunk_index=len(chunks),
                token_count=current_tokens,
                chunk_type=chunk_type,
                section_title=section_title,
                language=language,
                line_start=None,
                line_end=None,
                char_start=current_char_start,
                char_end=current_char_start + len(current_text)
            )
            chunks.append(chunk)

        return chunks

    def _get_overlap_text(self, text: str, overlap_tokens: int) -> str:
        """
        Get last N tokens of text for overlap

        Args:
            text: Text to get overlap from
            overlap_tokens: Number of tokens for overlap

        Returns:
            Overlapping text
        """
        if not text or overlap_tokens <= 0:
            return ""

        # Simple approximation: take last ~N words (tokens ≈ words for English)
        words = text.split()
        overlap_words = words[-overlap_tokens:]
        return " ".join(overlap_words)


if __name__ == "__main__":
    # Test chunker
    print("Testing document chunker...")

    from backend.knowledge.extractors import ExtractedDocument

    # Create sample document
    sample_text = """# Test Document

This is a test paragraph with some content. It should be chunked appropriately.

## Section 1

Here is some content in section 1. This section has multiple paragraphs.

More content here in the same section.

## Section 2

Different section with different content. This one is shorter.
"""

    doc = ExtractedDocument(
        text=sample_text,
        title="Test",
        metadata={'file_type': 'markdown'},
        sections=[
            {'title': 'Test Document', 'line_number': 1, 'level': 1, 'type': 'heading'},
            {'title': 'Section 1', 'line_number': 5, 'level': 2, 'type': 'heading'},
            {'title': 'Section 2', 'line_number': 11, 'level': 2, 'type': 'heading'},
        ]
    )

    chunker = DocumentChunker()
    chunks = chunker.chunk_document(doc, max_tokens=100, overlap_tokens=20, min_tokens=10)

    print(f"\n✓ Created {len(chunks)} chunks")
    for chunk in chunks:
        print(f"\n  Chunk {chunk.chunk_index}:")
        print(f"    Tokens: {chunk.token_count}")
        print(f"    Section: {chunk.section_title}")
        print(f"    Preview: {chunk.text[:100]}...")

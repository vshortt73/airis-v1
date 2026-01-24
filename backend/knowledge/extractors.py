"""
Text Extractors - Extract text from various file types
Handles code files, markdown, plain text, and PDFs
"""

import os
import sys
from typing import Optional, List, Dict
from dataclasses import dataclass
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config


@dataclass
class ExtractedDocument:
    """Extracted document with metadata"""
    text: str
    title: str
    metadata: Dict
    sections: List[Dict]  # List of {title, start_pos, end_pos}


class TextExtractor:
    """Handles text extraction from different file types"""

    def extract_text(self, file_path: str, file_type: str) -> Optional[ExtractedDocument]:
        """
        Extract text and metadata from file

        Args:
            file_path: Path to file
            file_type: File extension (.py, .md, .pdf, etc.)

        Returns:
            ExtractedDocument or None on error
        """
        try:
            if file_type in ['.py', '.js', '.ts', '.jsx', '.tsx', '.sql', '.sh', '.yaml', '.yml', '.json']:
                return self.extract_code(file_path, file_type)
            elif file_type in ['.md', '.txt', '.rst', '.org']:
                return self.extract_markdown(file_path, file_type)
            elif file_type == '.pdf' and getattr(config, 'KNOWLEDGE_PDF_ENABLED', True):
                return self.extract_pdf(file_path)
            elif file_type == '.docx' and getattr(config, 'KNOWLEDGE_DOCX_ENABLED', True):
                return self.extract_docx(file_path)
            elif file_type == '.odt' and getattr(config, 'KNOWLEDGE_ODT_ENABLED', True):
                return self.extract_odt(file_path)
            elif file_type in ['.doc', '.rtf']:
                print(f"[extractors][extract_text] ⚠ Legacy format {file_type} not supported: {file_path}")
                return None
            else:
                # Try as plain text
                return self.extract_plain_text(file_path)

        except Exception as e:
            print(f"[extractors][extract_text] ✗ Error extracting {file_path}: {e}")
            return None

    def extract_code(self, file_path: str, file_type: str) -> ExtractedDocument:
        """
        Extract text from code files

        Preserves structure, extracts docstrings/comments as metadata
        """
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

        # Extract title from file name
        file_name = os.path.basename(file_path)
        title = os.path.splitext(file_name)[0]

        # Determine language
        language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'jsx',
            '.tsx': 'tsx',
            '.sql': 'sql',
            '.sh': 'bash',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.json': 'json'
        }
        language = language_map.get(file_type, 'text')

        # Extract sections based on code structure
        sections = self._extract_code_sections(text, language)

        metadata = {
            'language': language,
            'file_type': 'code',
            'line_count': text.count('\n') + 1
        }

        return ExtractedDocument(
            text=text,
            title=title,
            metadata=metadata,
            sections=sections
        )

    def _extract_code_sections(self, text: str, language: str) -> List[Dict]:
        """
        Extract logical sections from code

        For Python: functions and classes
        For other languages: basic structure
        """
        sections = []

        if language == 'python':
            # Find Python functions and classes
            class_pattern = r'^class\s+(\w+)'
            func_pattern = r'^def\s+(\w+)'

            for i, line in enumerate(text.split('\n')):
                # Check for class
                class_match = re.match(class_pattern, line)
                if class_match:
                    sections.append({
                        'title': f"class {class_match.group(1)}",
                        'line_number': i + 1,
                        'type': 'class'
                    })

                # Check for function
                func_match = re.match(func_pattern, line)
                if func_match:
                    sections.append({
                        'title': f"def {func_match.group(1)}",
                        'line_number': i + 1,
                        'type': 'function'
                    })

        # Add a default section if none found
        if not sections:
            sections.append({
                'title': 'code',
                'line_number': 1,
                'type': 'file'
            })

        return sections

    def extract_markdown(self, file_path: str, file_type: str) -> ExtractedDocument:
        """
        Extract text from markdown/text files

        Parses heading structure, preserves code blocks
        """
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

        # Extract title from first H1 heading or filename
        title_match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = os.path.splitext(os.path.basename(file_path))[0]

        # Extract sections from headings
        sections = self._extract_markdown_sections(text)

        # Extract links
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', text)

        metadata = {
            'file_type': 'markdown' if file_type == '.md' else 'text',
            'link_count': len(links),
            'has_code_blocks': '```' in text
        }

        return ExtractedDocument(
            text=text,
            title=title,
            metadata=metadata,
            sections=sections
        )

    def _extract_markdown_sections(self, text: str) -> List[Dict]:
        """
        Extract sections from markdown headings

        Returns list of {title, start_pos, level}
        """
        sections = []
        heading_pattern = r'^(#{1,6})\s+(.+)$'

        for i, line in enumerate(text.split('\n')):
            match = re.match(heading_pattern, line)
            if match:
                level = len(match.group(1))  # Number of # symbols
                title = match.group(2).strip()
                sections.append({
                    'title': title,
                    'line_number': i + 1,
                    'level': level,
                    'type': 'heading'
                })

        return sections

    def extract_pdf(self, file_path: str) -> Optional[ExtractedDocument]:
        """
        Extract text from PDF files

        Uses pypdf library for text extraction
        """
        try:
            import pypdf
        except ImportError:
            print("[extractors][extract_pdf] ✗ pypdf not installed - run: pip install pypdf")
            return None

        try:
            reader = pypdf.PdfReader(file_path)

            # Check page count
            page_count = len(reader.pages)
            if page_count > config.KNOWLEDGE_PDF_MAX_PAGES:
                print(f"[extractors][extract_pdf] ⚠ PDF too large ({page_count} pages): {file_path}")
                return None

            # Extract text from all pages
            text_parts = []
            sections = []

            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                    sections.append({
                        'title': f"Page {i + 1}",
                        'page_number': i + 1,
                        'type': 'page'
                    })

            text = '\n\n'.join(text_parts)

            # Extract title from PDF metadata or filename
            metadata_obj = reader.metadata
            if metadata_obj and metadata_obj.title:
                title = metadata_obj.title
            else:
                title = os.path.splitext(os.path.basename(file_path))[0]

            metadata = {
                'file_type': 'pdf',
                'page_count': page_count,
                'author': metadata_obj.author if metadata_obj and metadata_obj.author else None
            }

            return ExtractedDocument(
                text=text,
                title=title,
                metadata=metadata,
                sections=sections
            )

        except Exception as e:
            print(f"[extractors][extract_pdf] ✗ Error extracting PDF {file_path}: {e}")
            return None

    def extract_docx(self, file_path: str) -> Optional[ExtractedDocument]:
        """
        Extract text from Word (.docx) files

        Uses python-docx library for text extraction
        """
        try:
            from docx import Document
        except ImportError:
            print("[extractors][extract_docx] ✗ python-docx not installed - run: pip install python-docx")
            return None

        try:
            doc = Document(file_path)

            # Extract text from paragraphs
            text_parts = []
            sections = []
            current_section = None

            for i, para in enumerate(doc.paragraphs):
                text = para.text.strip()
                if not text:
                    continue

                # Check for headings (style-based)
                style_name = para.style.name if para.style else ""
                if style_name.startswith('Heading'):
                    # Extract heading level from style name (e.g., "Heading 1" -> 1)
                    try:
                        level = int(style_name.split()[-1])
                    except (ValueError, IndexError):
                        level = 1

                    sections.append({
                        'title': text,
                        'paragraph_index': i,
                        'level': level,
                        'type': 'heading'
                    })

                text_parts.append(text)

            full_text = '\n\n'.join(text_parts)

            # Extract tables
            table_count = len(doc.tables)
            if table_count > 0:
                text_parts.append(f"\n\n[Document contains {table_count} table(s)]")
                for t_idx, table in enumerate(doc.tables):
                    table_text = []
                    for row in table.rows:
                        row_text = [cell.text.strip() for cell in row.cells]
                        table_text.append(' | '.join(row_text))
                    if table_text:
                        text_parts.append(f"\n--- Table {t_idx + 1} ---\n" + '\n'.join(table_text))

            full_text = '\n\n'.join(text_parts)

            # Get title from core properties or filename
            title = os.path.splitext(os.path.basename(file_path))[0]
            try:
                if doc.core_properties.title:
                    title = doc.core_properties.title
            except:
                pass

            metadata = {
                'file_type': 'docx',
                'paragraph_count': len(doc.paragraphs),
                'table_count': table_count,
                'author': getattr(doc.core_properties, 'author', None)
            }

            return ExtractedDocument(
                text=full_text,
                title=title,
                metadata=metadata,
                sections=sections if sections else [{'title': 'content', 'paragraph_index': 0, 'type': 'file'}]
            )

        except Exception as e:
            print(f"[extractors][extract_docx] ✗ Error extracting DOCX {file_path}: {e}")
            return None

    def extract_odt(self, file_path: str) -> Optional[ExtractedDocument]:
        """
        Extract text from LibreOffice/OpenDocument (.odt) files

        Uses odfpy library for text extraction
        """
        try:
            from odf import text as odf_text
            from odf.opendocument import load
        except ImportError:
            print("[extractors][extract_odt] ✗ odfpy not installed - run: pip install odfpy")
            return None

        try:
            doc = load(file_path)

            # Extract all text content
            text_parts = []
            sections = []

            # Get all paragraphs
            paragraphs = doc.getElementsByType(odf_text.P)

            for i, para in enumerate(paragraphs):
                # Extract text from paragraph (including nested spans)
                para_text = self._get_odf_text(para)
                if para_text.strip():
                    text_parts.append(para_text.strip())

            # Get headings
            headings = doc.getElementsByType(odf_text.H)
            for i, heading in enumerate(headings):
                heading_text = self._get_odf_text(heading)
                if heading_text.strip():
                    # Try to get outline level
                    level = heading.getAttribute('outlinelevel') or '1'
                    try:
                        level = int(level)
                    except:
                        level = 1

                    sections.append({
                        'title': heading_text.strip(),
                        'index': i,
                        'level': level,
                        'type': 'heading'
                    })

            full_text = '\n\n'.join(text_parts)

            # Get title from metadata or filename
            title = os.path.splitext(os.path.basename(file_path))[0]
            try:
                meta = doc.meta
                if meta:
                    title_elem = meta.getElementsByType(odf_text.Title)
                    if title_elem:
                        title = self._get_odf_text(title_elem[0]) or title
            except:
                pass

            metadata = {
                'file_type': 'odt',
                'paragraph_count': len(paragraphs),
                'heading_count': len(headings)
            }

            return ExtractedDocument(
                text=full_text,
                title=title,
                metadata=metadata,
                sections=sections if sections else [{'title': 'content', 'index': 0, 'type': 'file'}]
            )

        except Exception as e:
            print(f"[extractors][extract_odt] ✗ Error extracting ODT {file_path}: {e}")
            return None

    def _get_odf_text(self, element) -> str:
        """Recursively extract text from ODF element"""
        result = []
        if hasattr(element, 'childNodes'):
            for child in element.childNodes:
                if child.nodeType == 3:  # Text node
                    result.append(str(child))
                else:
                    result.append(self._get_odf_text(child))
        return ''.join(result)

    def extract_plain_text(self, file_path: str) -> ExtractedDocument:
        """
        Extract plain text (fallback for unknown types)
        """
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()

        title = os.path.splitext(os.path.basename(file_path))[0]

        return ExtractedDocument(
            text=text,
            title=title,
            metadata={'file_type': 'text'},
            sections=[{'title': 'content', 'line_number': 1, 'type': 'file'}]
        )


if __name__ == "__main__":
    # Test extractor
    print("Testing text extractors...")

    extractor = TextExtractor()

    # Test Python file
    test_file = __file__  # This file
    doc = extractor.extract_text(test_file, '.py')

    if doc:
        print(f"\n✓ Extracted: {doc.title}")
        print(f"  Text length: {len(doc.text)} chars")
        print(f"  Sections: {len(doc.sections)}")
        print(f"  Metadata: {doc.metadata}")

        if doc.sections:
            print("\n  First 3 sections:")
            for section in doc.sections[:3]:
                print(f"    - {section}")

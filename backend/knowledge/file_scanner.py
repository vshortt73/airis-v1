"""
File Scanner - Directory traversal and file discovery for knowledge indexing
Handles recursive scanning, pattern matching, and incremental indexing logic
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
import psycopg2


@dataclass
class FileInfo:
    """Information about a discovered file"""
    file_path: str
    file_name: str
    file_type: str  # Extension like .py, .md, etc.
    file_size_bytes: int
    modified_time: datetime
    doc_category: str  # e.g., "project_code", "external_docs"


def get_db_connection():
    """Get database connection (standard Iris pattern)"""
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


def matches_pattern(file_path: str, patterns: List[str]) -> bool:
    """
    Check if file matches any of the glob patterns

    Args:
        file_path: Path to check
        patterns: List of glob patterns like ["*.py", "*.md"]

    Returns:
        True if file matches any pattern
    """
    from fnmatch import fnmatch
    file_name = os.path.basename(file_path)
    return any(fnmatch(file_name, pattern) for pattern in patterns)


def should_exclude(file_path: str, exclude_patterns: List[str]) -> bool:
    """
    Check if file path contains any exclusion patterns

    Args:
        file_path: Path to check
        exclude_patterns: List of exclusion strings

    Returns:
        True if file should be excluded
    """
    return any(pattern in file_path for pattern in exclude_patterns)


def determine_category(file_path: str, scan_directories: List[str]) -> str:
    """
    Determine document category based on which directory it's in

    Args:
        file_path: Absolute file path
        scan_directories: List of scan directories from config

    Returns:
        Category string like "project_code", "external_docs"
    """
    # Check which scan directory this file belongs to
    for scan_dir in scan_directories:
        if file_path.startswith(scan_dir):
            # Use directory name as category
            if scan_dir == "/iris-v3":
                return "project_code"
            else:
                return os.path.basename(scan_dir.rstrip('/'))

    return "unknown"


def scan_directories(
    directories: List[str],
    file_patterns: Dict[str, List[str]],
    exclude_patterns: List[str]
) -> List[FileInfo]:
    """
    Recursively scan directories for indexable files

    Args:
        directories: List of directory paths to scan
        file_patterns: Dict of pattern categories (code, docs, pdf) -> glob patterns
        exclude_patterns: List of exclusion patterns

    Returns:
        List of FileInfo objects for discovered files
    """
    print(f"[file_scanner][scan_directories] Scanning {len(directories)} directories...")

    discovered_files = []
    all_patterns = []

    # Flatten all patterns
    for category, patterns in file_patterns.items():
        all_patterns.extend(patterns)

    for directory in directories:
        if not os.path.exists(directory):
            print(f"[file_scanner][scan_directories] ⚠ Directory not found: {directory}")
            continue

        print(f"[file_scanner][scan_directories] Scanning: {directory}")

        # Walk directory tree
        for root, dirs, files in os.walk(directory):
            # Filter out excluded directories (modify in-place)
            dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), exclude_patterns)]

            for file_name in files:
                file_path = os.path.join(root, file_name)

                # Check exact filename exclusions
                if file_name in config.KNOWLEDGE_EXCLUDE_FILENAMES:
                    continue

                # Check path exclusions
                if should_exclude(file_path, exclude_patterns):
                    continue

                # Check if matches any pattern
                if not matches_pattern(file_path, all_patterns):
                    continue

                # Check file size
                try:
                    stat = os.stat(file_path)
                    file_size_mb = stat.st_size / (1024 * 1024)

                    if file_size_mb > config.KNOWLEDGE_MAX_FILE_SIZE_MB:
                        print(f"[file_scanner][scan_directories] ⚠ Skipping large file ({file_size_mb:.1f}MB): {file_name}")
                        continue

                    # Create FileInfo
                    file_info = FileInfo(
                        file_path=file_path,
                        file_name=file_name,
                        file_type=os.path.splitext(file_name)[1],
                        file_size_bytes=stat.st_size,
                        modified_time=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        doc_category=determine_category(file_path, directories)
                    )

                    discovered_files.append(file_info)

                except (OSError, PermissionError) as e:
                    print(f"[file_scanner][scan_directories] ✗ Error accessing {file_name}: {e}")

    print(f"[file_scanner][scan_directories] ✓ Discovered {len(discovered_files)} files")
    return discovered_files


def calculate_file_hash(file_path: str) -> Optional[str]:
    """
    Calculate SHA256 hash of file content

    Args:
        file_path: Path to file

    Returns:
        SHA256 hash as hex string, or None on error
    """
    try:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read in chunks to handle large files
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception as e:
        print(f"[file_scanner][calculate_file_hash] ✗ Error hashing {file_path}: {e}")
        return None


def get_existing_document(file_path: str) -> Optional[Dict]:
    """
    Get existing document from database by file path

    Args:
        file_path: Absolute file path

    Returns:
        Dict with doc_id, modified_time, doc_hash or None if not found
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT doc_id, modified_time, doc_hash, indexed_at
            FROM knowledge_documents
            WHERE file_path = %s
        """, (file_path,))

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            return {
                'doc_id': row[0],
                'modified_time': row[1],
                'doc_hash': row[2],
                'indexed_at': row[3]
            }
        return None

    except Exception as e:
        print(f"[file_scanner][get_existing_document] ✗ Error querying database: {e}")
        return None


def should_index_file(file_info: FileInfo, incremental: bool = True, hash_check: bool = True) -> bool:
    """
    Determine if file needs (re-)indexing

    Checks:
    1. File exists and readable
    2. Not in exclusion patterns (already checked in scan)
    3. Size within limits (already checked in scan)
    4. Modified time > last indexed (incremental)
    5. Content hash changed (if hash checking enabled)

    Args:
        file_info: FileInfo object
        incremental: If True, skip unchanged files
        hash_check: If True, verify content hash changed

    Returns:
        True if file should be indexed
    """
    # If not incremental, always index
    if not incremental:
        return True

    # Check if file exists in database
    existing = get_existing_document(file_info.file_path)

    # New file - always index
    if not existing:
        print(f"[file_scanner][should_index_file] → New file: {file_info.file_name}")
        return True

    # Check modified time
    existing_mtime = existing['modified_time']
    if file_info.modified_time <= existing_mtime:
        # File not modified since last index
        return False

    # Modified time changed - check hash if enabled
    if hash_check and config.KNOWLEDGE_HASH_CHECK:
        current_hash = calculate_file_hash(file_info.file_path)
        existing_hash = existing['doc_hash']

        if current_hash == existing_hash:
            # Hash unchanged (e.g., just touched)
            print(f"[file_scanner][should_index_file] ⊘ Hash unchanged: {file_info.file_name}")
            return False

    # Modified and hash changed (or hash check disabled)
    print(f"[file_scanner][should_index_file] → Modified: {file_info.file_name}")
    return True


if __name__ == "__main__":
    # Test scanning
    print("Testing file scanner...")

    files = scan_directories(
        config.KNOWLEDGE_SCAN_DIRECTORIES,
        config.KNOWLEDGE_FILE_PATTERNS,
        config.KNOWLEDGE_EXCLUDE_PATTERNS
    )

    print(f"\n✓ Total files discovered: {len(files)}")

    # Show sample
    if files:
        print("\nSample files:")
        for f in files[:5]:
            print(f"  - {f.file_name} ({f.file_type}, {f.file_size_bytes} bytes, {f.doc_category})")

    # Test incremental logic
    if files:
        print("\nTesting incremental indexing...")
        test_file = files[0]
        should_idx = should_index_file(test_file)
        print(f"Should index {test_file.file_name}: {should_idx}")

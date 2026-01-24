"""
Knowledge Base Indexer - Main Orchestrator
Coordinates document scanning, extraction, chunking, embedding, and database insertion
Called by cron job for scheduled indexing
"""

import os
import sys
import time
from typing import Dict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config
from backend.knowledge.file_scanner import scan_directories, should_index_file
from backend.knowledge.extractors import TextExtractor
from backend.knowledge.chunker import DocumentChunker
from backend.knowledge.embedder import generate_chunk_embeddings
from backend.knowledge.db_writer import index_document, create_index_status, update_index_status


def main():
    """
    Main indexing orchestrator

    Pipeline:
    1. Scan directories for files
    2. Filter for indexing (incremental check)
    3. For each file:
       - Extract text
       - Chunk document
       - Generate embeddings
       - Write to database
    4. Track statistics and errors
    5. Update index status
    """
    start_time = time.time()

    print("=" * 70)
    print("KNOWLEDGE BASE INDEXING")
    print("=" * 70)
    print(f"Start time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Directories: {config.KNOWLEDGE_SCAN_DIRECTORIES}")
    print("=" * 70)

    # Create index status record
    status_id = create_index_status(config.KNOWLEDGE_SCAN_DIRECTORIES)

    stats = {
        'scanned': 0,
        'indexed': 0,
        'updated': 0,
        'failed': 0,
        'chunks_created': 0
    }

    errors = []

    try:
        # ==================================================================
        # STEP 1: Scan Directories
        # ==================================================================
        print("\n[1/5] SCANNING DIRECTORIES")
        print("-" * 70)

        file_infos = scan_directories(
            config.KNOWLEDGE_SCAN_DIRECTORIES,
            config.KNOWLEDGE_FILE_PATTERNS,
            config.KNOWLEDGE_EXCLUDE_PATTERNS
        )

        print(f"✓ Discovered {len(file_infos)} files")

        # ==================================================================
        # STEP 2: Filter for Indexing (Incremental)
        # ==================================================================
        print("\n[2/5] FILTERING FOR INDEXING")
        print("-" * 70)

        files_to_index = []
        for file_info in file_infos:
            stats['scanned'] += 1

            if should_index_file(
                file_info,
                incremental=config.KNOWLEDGE_INCREMENTAL_INDEXING,
                hash_check=config.KNOWLEDGE_HASH_CHECK
            ):
                files_to_index.append(file_info)

        print(f"✓ {len(files_to_index)} files need (re-)indexing")
        print(f"  ({len(file_infos) - len(files_to_index)} files unchanged)")

        if not files_to_index:
            print("\n✓ No files to index - all up to date!")
            duration = int(time.time() - start_time)
            update_index_status(status_id, 'completed', stats, duration)
            print(f"\nCompleted in {duration} seconds")
            return 0

        # ==================================================================
        # STEP 3: Process Files
        # ==================================================================
        print("\n[3/5] PROCESSING FILES")
        print("-" * 70)

        extractor = TextExtractor()
        chunker = DocumentChunker()

        for i, file_info in enumerate(files_to_index, 1):
            print(f"\n[{i}/{len(files_to_index)}] {file_info.file_name}")
            print(f"  Path: {file_info.file_path}")
            print(f"  Type: {file_info.file_type}")
            print(f"  Size: {file_info.file_size_bytes} bytes")

            try:
                # Extract text
                print("  → Extracting text...")
                extracted = extractor.extract_text(file_info.file_path, file_info.file_type)

                if not extracted:
                    print(f"  ✗ Extraction failed")
                    stats['failed'] += 1
                    errors.append({
                        'file': file_info.file_path,
                        'stage': 'extraction',
                        'error': 'Extraction returned None'
                    })
                    continue

                print(f"  ✓ Extracted {len(extracted.text)} chars")

                # Chunk document
                print("  → Chunking document...")
                chunks = chunker.chunk_document(
                    extracted,
                    max_tokens=config.KNOWLEDGE_MAX_CHUNK_TOKENS,
                    overlap_tokens=config.KNOWLEDGE_CHUNK_OVERLAP_TOKENS,
                    min_tokens=config.KNOWLEDGE_MIN_CHUNK_TOKENS
                )

                if not chunks:
                    print(f"  ✗ No chunks created")
                    # stats['failed'] += 1
                    # errors.append({
                    #     'file': file_info.file_path,
                    #     'stage': 'chunking',
                    #     'error': 'No chunks created'
                    # })
                    continue

                print(f"  ✓ Created {len(chunks)} chunks")

                # Generate embeddings
                print("  → Generating embeddings...")
                embeddings = generate_chunk_embeddings(
                    chunks,
                    extracted.title,
                    batch_size=config.KNOWLEDGE_EMBEDDING_BATCH_SIZE
                )

                if not embeddings or len(embeddings) != len(chunks):
                    print(f"  ✗ Embedding generation failed")
                    stats['failed'] += 1
                    errors.append({
                        'file': file_info.file_path,
                        'stage': 'embedding',
                        'error': f'Embedding count mismatch: {len(embeddings)} vs {len(chunks)}'
                    })
                    continue

                print(f"  ✓ Generated {len(embeddings)} dual-facet embeddings")

                # Write to database
                print("  → Writing to database...")
                doc_id = index_document(file_info, extracted, chunks, embeddings)

                if doc_id:
                    print(f"  ✓ Indexed successfully (doc_id={doc_id})")
                    stats['indexed'] += 1
                    stats['chunks_created'] += len(chunks)
                else:
                    print(f"  ✗ Database write failed")
                    stats['failed'] += 1
                    errors.append({
                        'file': file_info.file_path,
                        'stage': 'database',
                        'error': 'index_document returned None'
                    })

            except Exception as e:
                print(f"  ✗ ERROR: {e}")
                stats['failed'] += 1
                errors.append({
                    'file': file_info.file_path,
                    'stage': 'processing',
                    'error': str(e)
                })

        # ==================================================================
        # STEP 4: Finalize Index Status
        # ==================================================================
        print("\n[4/5] FINALIZING INDEX STATUS")
        print("-" * 70)

        duration = int(time.time() - start_time)

        # Determine final status
        if stats['failed'] == 0:
            final_status = 'completed'
        elif stats['indexed'] > 0:
            final_status = 'partial'
        else:
            final_status = 'failed'

        update_index_status(status_id, final_status, stats, duration, errors if errors else None)

        print(f"✓ Index status updated: {final_status}")

        # ==================================================================
        # STEP 5: Summary
        # ==================================================================
        print("\n[5/5] SUMMARY")
        print("=" * 70)
        print(f"Status:           {final_status.upper()}")
        print(f"Files scanned:    {stats['scanned']}")
        print(f"Files indexed:    {stats['indexed']}")
        print(f"Files failed:     {stats['failed']}")
        print(f"Chunks created:   {stats['chunks_created']}")
        print(f"Duration:         {duration}s ({duration // 60}m {duration % 60}s)")
        print("=" * 70)

        if errors:
            print(f"\nErrors encountered: {len(errors)}")
            for error in errors[:5]:  # Show first 5
                print(f"  - {error['file']}: {error['error']} ({error['stage']})")
            if len(errors) > 5:
                print(f"  ... and {len(errors) - 5} more")

        print(f"\nCompleted at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        return 0 if final_status == 'completed' else 1

    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        duration = int(time.time() - start_time)
        update_index_status(status_id, 'failed', stats, duration, [{'error': str(e), 'stage': 'fatal'}])
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

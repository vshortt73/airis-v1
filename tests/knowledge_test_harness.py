"""
Knowledge Base Test Harness - Interactive testing for document_search MCP tool

Tests Iris's document search and RAG capabilities:
- Semantic search over indexed documents
- Filter by category, file type, path
- Knowledge base statistics
- Performance timing

Usage:
    python tests/knowledge_test_harness.py
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.embeddings import generate_embedding
import psycopg2
from app import config


class KnowledgeTestHarness:
    """Interactive test harness for knowledge base / document search"""

    def __init__(self, db_params: Dict):
        self.conn = psycopg2.connect(**db_params)
        self.cursor = self.conn.cursor()

    def get_stats(self) -> Dict:
        """Get knowledge base statistics"""
        print("\n" + "="*80)
        print("KNOWLEDGE BASE STATISTICS")
        print("="*80)

        # Overall stats
        self.cursor.execute("""
            SELECT
                COUNT(*) as doc_count,
                COALESCE(SUM(chunk_count), 0) as total_chunks,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(file_size_bytes), 0) as total_bytes
            FROM knowledge_documents
        """)
        doc_count, total_chunks, total_tokens, total_bytes = self.cursor.fetchone()

        print(f"\nOverall:")
        print(f"  Documents: {doc_count:,}")
        print(f"  Chunks: {total_chunks:,}")
        print(f"  Total Tokens: {total_tokens:,}")
        print(f"  Total Size: {total_bytes / 1024 / 1024:.2f} MB")

        # By category
        self.cursor.execute("""
            SELECT doc_category, COUNT(*) as count, SUM(chunk_count) as chunks
            FROM knowledge_documents
            GROUP BY doc_category
            ORDER BY count DESC
        """)

        print(f"\nBy Category:")
        for category, count, chunks in self.cursor.fetchall():
            category_name = category or 'unknown'
            print(f"  {category_name:20s}: {count:4d} docs, {chunks:5d} chunks")

        # By file type
        self.cursor.execute("""
            SELECT file_type, COUNT(*) as count, SUM(chunk_count) as chunks
            FROM knowledge_documents
            GROUP BY file_type
            ORDER BY count DESC
            LIMIT 10
        """)

        print(f"\nBy File Type (top 10):")
        for file_type, count, chunks in self.cursor.fetchall():
            print(f"  {file_type:15s}: {count:4d} docs, {chunks:5d} chunks")

        # Last index run
        self.cursor.execute("""
            SELECT scan_started_at, scan_completed_at, scan_status,
                   docs_indexed, docs_failed, chunks_created, duration_seconds
            FROM knowledge_index_status
            ORDER BY scan_started_at DESC
            LIMIT 1
        """)

        last_run = self.cursor.fetchone()

        if last_run:
            print(f"\nLast Indexing Run:")
            print(f"  Started: {last_run[0]}")
            print(f"  Completed: {last_run[1]}")
            print(f"  Status: {last_run[2]}")
            print(f"  Docs Indexed: {last_run[3]}")
            print(f"  Docs Failed: {last_run[4]}")
            print(f"  Chunks Created: {last_run[5]}")
            print(f"  Duration: {last_run[6]:.2f}s")

        return {
            'doc_count': doc_count,
            'total_chunks': total_chunks,
            'total_tokens': total_tokens
        }

    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_category: Optional[str] = None,
        filter_file_type: Optional[str] = None,
        filter_path: Optional[str] = None,
        similarity_threshold: Optional[float] = None
    ) -> Dict:
        """
        Perform semantic document search

        This mimics the document_search MCP tool implementation
        """

        print("\n" + "="*80)
        print("DOCUMENT SEARCH")
        print("="*80)

        print(f"\nQuery: '{query}'")
        print(f"Parameters:")
        print(f"  top_k: {top_k}")
        print(f"  threshold: {similarity_threshold or config.KNOWLEDGE_SIMILARITY_THRESHOLD}")
        if filter_category:
            print(f"  category: {filter_category}")
        if filter_file_type:
            print(f"  file_type: {filter_file_type}")
        if filter_path:
            print(f"  path: {filter_path}")

        # Parameter validation
        top_k = min(max(1, top_k), config.KNOWLEDGE_MAX_SEARCH_LIMIT)
        threshold = similarity_threshold or config.KNOWLEDGE_SIMILARITY_THRESHOLD

        # Generate query embedding
        print("\n⏳ Generating embedding...")
        start = time.time()
        query_embedding = generate_embedding(query)
        embedding_time = time.time() - start

        if not query_embedding:
            print("✗ Failed to generate query embedding")
            return {"success": False, "error": "Embedding generation failed"}

        print(f"✓ Embedding generated in {embedding_time:.3f}s")

        # Build SQL query (same as knowledge_server.py)
        sql = """
            SELECT
                kc.chunk_id,
                kc.chunk_text,
                kc.section_title,
                kc.token_count,
                kc.line_start,
                kc.line_end,
                kc.chunk_type,
                kc.language,
                kd.file_path,
                kd.file_name,
                kd.file_type,
                kd.doc_category,
                (
                    %s * (1 - (kc.emb_content <=> %s::vector)) +
                    %s * (1 - (kc.emb_context <=> %s::vector))
                )::float AS similarity
            FROM knowledge_chunks kc
            JOIN knowledge_documents kd ON kc.doc_id = kd.doc_id
            WHERE 1=1
        """

        # Get weights from config
        content_weight = config.KNOWLEDGE_FACET_WEIGHTS.get('content', 0.6)
        context_weight = config.KNOWLEDGE_FACET_WEIGHTS.get('context', 0.4)

        params = [content_weight, query_embedding, context_weight, query_embedding]

        # Apply filters
        if filter_category:
            sql += " AND kd.doc_category = %s"
            params.append(filter_category)

        if filter_file_type:
            sql += " AND kd.file_type = %s"
            params.append(filter_file_type)

        if filter_path:
            sql += " AND kd.file_path LIKE %s"
            params.append(f"%{filter_path}%")

        # Order by similarity and limit (oversample for filtering)
        sql += """
            ORDER BY similarity DESC
            LIMIT %s
        """
        params.append(top_k * 2)

        # Execute search
        print("⏳ Searching...")
        start = time.time()
        self.cursor.execute(sql, params)
        candidates = self.cursor.fetchall()
        search_time = time.time() - start

        print(f"✓ Search completed in {search_time:.3f}s")

        # Calculate tiers and filter by threshold
        tier_thresholds = config.KNOWLEDGE_TIER_THRESHOLDS

        results = []
        for row in candidates:
            (chunk_id, chunk_text, section, tokens, line_start, line_end,
             chunk_type, language, file_path, file_name, file_type,
             category, similarity) = row

            # Determine tier
            tier = self._calculate_tier(similarity, tier_thresholds)

            if tier is None or similarity < threshold:
                continue  # Below threshold

            results.append({
                "chunk_id": chunk_id,
                "chunk_text": chunk_text,
                "section_title": section,
                "file_path": file_path,
                "file_name": file_name,
                "file_type": file_type,
                "category": category,
                "chunk_type": chunk_type,
                "language": language,
                "line_range": [line_start, line_end] if line_start else None,
                "token_count": tokens,
                "similarity": round(similarity, 3),
                "tier": tier
            })

        # Limit to top_k after filtering
        results = results[:top_k]

        print(f"\n📊 Found {len(results)} results (from {len(candidates)} candidates)")

        # Display results
        self._display_results(results)

        return {
            "success": True,
            "query": query,
            "result_count": len(results),
            "results": results,
            "timing": {
                "embedding": embedding_time,
                "search": search_time,
                "total": embedding_time + search_time
            }
        }

    def _calculate_tier(self, similarity: float, thresholds: Dict[int, float]) -> Optional[int]:
        """Calculate result tier based on similarity"""
        if similarity >= thresholds[1]:
            return 1
        elif similarity >= thresholds[2]:
            return 2
        elif similarity >= thresholds[3]:
            return 3
        elif similarity >= thresholds[4]:
            return 4
        return None

    def _display_results(self, results: List[Dict]):
        """Display search results in a readable format"""

        if not results:
            print("\n  (No results)")
            return

        print("\nResults by Tier:")

        # Group by tier
        by_tier = {}
        for result in results:
            tier = result['tier']
            if tier not in by_tier:
                by_tier[tier] = []
            by_tier[tier].append(result)

        # Display each tier
        for tier in sorted(by_tier.keys()):
            tier_results = by_tier[tier]
            tier_names = {1: "Tier 1 (Excellent)", 2: "Tier 2 (Good)",
                         3: "Tier 3 (Fair)", 4: "Tier 4 (Weak)"}

            print(f"\n{tier_names.get(tier, f'Tier {tier}')} - {len(tier_results)} results:")
            print("-" * 80)

            for i, result in enumerate(tier_results, 1):
                print(f"\n  [{i}] {result['file_name']} (similarity: {result['similarity']:.3f})")
                print(f"      Path: {result['file_path']}")

                if result['section_title']:
                    print(f"      Section: {result['section_title']}")

                if result['line_range']:
                    print(f"      Lines: {result['line_range'][0]}-{result['line_range'][1]}")

                print(f"      Type: {result['file_type']} | Category: {result['category']}")
                print(f"      Tokens: {result['token_count']}")

                # Show snippet
                snippet = result['chunk_text'][:200]
                if len(result['chunk_text']) > 200:
                    snippet += "..."

                print(f"\n      {snippet}")

    def interactive_mode(self):
        """Interactive query interface"""

        print("\n" + "="*80)
        print("KNOWLEDGE BASE TEST HARNESS - INTERACTIVE MODE")
        print("="*80)

        print("\nCommands:")
        print("  search <query>              - Search with default settings")
        print("  search <query> --top <N>    - Limit results")
        print("  search <query> --cat <cat>  - Filter by category")
        print("  search <query> --type <ext> - Filter by file type (.py, .md, etc)")
        print("  search <query> --path <str> - Filter by path pattern")
        print("  search <query> --min <0-1>  - Set minimum similarity")
        print("  stats                       - Show knowledge base statistics")
        print("  preset <name>               - Run preset query")
        print("  quit                        - Exit")

        # Show available categories and file types
        self.cursor.execute("SELECT DISTINCT doc_category FROM knowledge_documents WHERE doc_category IS NOT NULL")
        categories = [row[0] for row in self.cursor.fetchall()]

        self.cursor.execute("SELECT DISTINCT file_type FROM knowledge_documents ORDER BY file_type")
        file_types = [row[0] for row in self.cursor.fetchall()]

        if categories:
            print(f"\nAvailable categories: {', '.join(categories)}")
        if file_types:
            print(f"Available file types: {', '.join(file_types[:20])}")

        # Preset queries
        presets = {
            'mcp': {
                'query': 'how to add a new MCP tool server',
                'filter_file_type': '.py'
            },
            'database': {
                'query': 'PostgreSQL database connection setup',
                'filter_file_type': '.py'
            },
            'memory': {
                'query': 'episodic memory retrieval and embeddings',
                'filter_path': 'backend/memory'
            },
            'vision': {
                'query': 'vision system architecture and GPU isolation',
                'filter_file_type': '.md'
            },
            'protocols': {
                'query': 'protocol system personality configuration',
                'filter_path': 'protocols'
            }
        }

        print(f"\nPreset queries: {', '.join(presets.keys())}")

        while True:
            try:
                print("\n" + "-"*80)
                user_input = input("\n> ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ['quit', 'exit', 'q']:
                    break

                if user_input.lower() == 'stats':
                    self.get_stats()
                    continue

                if user_input.lower().startswith('preset '):
                    preset_name = user_input.split(' ', 1)[1].strip()
                    if preset_name in presets:
                        preset = presets[preset_name]
                        print(f"\nRunning preset: {preset_name}")
                        self.search(**preset)
                    else:
                        print(f"Unknown preset: {preset_name}")
                        print(f"Available: {', '.join(presets.keys())}")
                    continue

                if user_input.lower().startswith('search '):
                    # Parse search command
                    parts = user_input.split(' ')

                    # Extract query (everything before first --)
                    query_parts = []
                    i = 1
                    while i < len(parts) and not parts[i].startswith('--'):
                        query_parts.append(parts[i])
                        i += 1

                    query = ' '.join(query_parts)

                    if not query:
                        print("Error: No query specified")
                        continue

                    # Parse options
                    options = {
                        'top_k': 10,
                        'filter_category': None,
                        'filter_file_type': None,
                        'filter_path': None,
                        'similarity_threshold': None
                    }

                    while i < len(parts):
                        if parts[i] == '--top' and i + 1 < len(parts):
                            options['top_k'] = int(parts[i + 1])
                            i += 2
                        elif parts[i] == '--cat' and i + 1 < len(parts):
                            options['filter_category'] = parts[i + 1]
                            i += 2
                        elif parts[i] == '--type' and i + 1 < len(parts):
                            options['filter_file_type'] = parts[i + 1]
                            i += 2
                        elif parts[i] == '--path' and i + 1 < len(parts):
                            options['filter_path'] = parts[i + 1]
                            i += 2
                        elif parts[i] == '--min' and i + 1 < len(parts):
                            options['similarity_threshold'] = float(parts[i + 1])
                            i += 2
                        else:
                            i += 1

                    # Execute search
                    self.search(query, **options)

                else:
                    print("Unknown command. Try 'search <query>', 'stats', 'preset <name>', or 'quit'")

            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()

    def run_benchmark(self):
        """Run a benchmark with several test queries"""

        print("\n" + "="*80)
        print("KNOWLEDGE BASE BENCHMARK")
        print("="*80)

        test_queries = [
            {
                'name': 'Code Search - MCP Tools',
                'query': 'how to implement and register a new MCP tool',
                'filter_file_type': '.py',
                'top_k': 5
            },
            {
                'name': 'Documentation Search - Vision',
                'query': 'dual-Ollama vision system with GPU isolation',
                'filter_file_type': '.md',
                'top_k': 5
            },
            {
                'name': 'General Search - Database',
                'query': 'PostgreSQL connection and query execution patterns',
                'top_k': 10
            },
            {
                'name': 'Filtered Search - Backend',
                'query': 'embeddings and semantic similarity search',
                'filter_path': 'backend',
                'top_k': 5
            }
        ]

        results = []

        for i, test in enumerate(test_queries, 1):
            print(f"\n{'='*80}")
            print(f"Test {i}/{len(test_queries)}: {test['name']}")
            print(f"{'='*80}")

            result = self.search(**{k: v for k, v in test.items() if k != 'name'})
            results.append({
                'name': test['name'],
                'result': result
            })

            time.sleep(0.5)  # Brief pause between tests

        # Summary
        print("\n" + "="*80)
        print("BENCHMARK SUMMARY")
        print("="*80)

        total_time = sum(r['result']['timing']['total'] for r in results if r['result'].get('success'))
        avg_time = total_time / len(results)

        print(f"\nTotal Time: {total_time:.3f}s")
        print(f"Average Time: {avg_time:.3f}s per query")

        print(f"\nResults by Test:")
        for result in results:
            if result['result'].get('success'):
                timing = result['result']['timing']
                count = result['result']['result_count']
                print(f"  {result['name']:40s}: {count:2d} results in {timing['total']:.3f}s")

    def cleanup(self):
        """Close database connection"""
        self.cursor.close()
        self.conn.close()


def main():
    """Main entry point"""

    print("="*80)
    print("KNOWLEDGE BASE TEST HARNESS")
    print("="*80)
    print("\nTests document_search MCP tool and RAG system")

    # Get database credentials
    print("\nDatabase Configuration:")
    db_password = os.environ.get('IRIS_DB_PASSWORD')

    if not db_password:
        db_password = input("  Password: ").strip()

    db_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
        'password': db_password
    }

    # Connect
    print("\n⏳ Connecting to database...")

    try:
        harness = KnowledgeTestHarness(db_params)
        print("✓ Connected\n")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return

    # Choose mode
    print("Select mode:")
    print("  1. Interactive (default)")
    print("  2. Benchmark")
    print("  3. Statistics only")

    mode = input("\nMode [1]: ").strip() or "1"

    try:
        if mode == "2":
            harness.run_benchmark()
        elif mode == "3":
            harness.get_stats()
        else:
            harness.interactive_mode()
    finally:
        harness.cleanup()

    print("\n✓ Test harness complete")


if __name__ == "__main__":
    main()

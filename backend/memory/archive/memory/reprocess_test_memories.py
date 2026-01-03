"""
Re-process the 72 test set memories with improved memory creation system

This script:
1. Loads test_set.json to get the 72 memory IDs
2. For each memory, fetches original transcript from database
3. Re-runs improved memory creation (relaxed limits + key_details + category-aware)
4. Updates the episodic_memories table with new summaries and embeddings

This allows us to test the improvements on a controlled subset before
batch processing all 5000 memories.
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

import json
import asyncio
import psycopg2
from psycopg2.extras import DictCursor
from Colors import Colors

# Import the improved memory creation functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'new'))
from memory_creation import generate_summaries
from core.embeddings import generate_embedding

# Import emotion scoring from retrieval system (has valence/arousal)
from memory_retrieval_v2 import score_emotion

DB_CFG = dict(
    dbname="irisdb",
    user="irisuser",
    password=os.environ.get('IRIS_DB_PASSWORD', 'yourpassword'),
    host="localhost",
    port=5432
)


async def reprocess_single_memory(memory_id: int, transcript: str, category: str, conv_title: str = None):
    """Re-process a single memory with improved system"""

    print(f"\n{Colors.BRIGHT_CYAN}Processing Memory ID {memory_id}{Colors.RESET}")
    print(f"  Category: {category}")
    print(f"  Transcript length: {len(transcript)} chars")

    try:
        # 1. Generate improved summaries (with category-aware prompts)
        print(f"  {Colors.YELLOW}→ Generating improved summaries...{Colors.RESET}")
        summaries = await generate_summaries(transcript, conv_title, category)

        if not summaries:
            print(f"  {Colors.BRIGHT_RED}✗ Failed to generate summaries{Colors.RESET}")
            return False

        # Verify key_details was generated (warn but don't fail)
        if not summaries.get('key_details'):
            print(f"  {Colors.YELLOW}⚠ key_details field missing from summaries{Colors.RESET}")
            print(f"  {Colors.YELLOW}  Available keys: {list(summaries.keys())}{Colors.RESET}")
            print(f"  {Colors.YELLOW}  Setting to empty string{Colors.RESET}")
            summaries['key_details'] = ''

        # 2. Generate embeddings for all 5 facets
        print(f"  {Colors.YELLOW}→ Generating embeddings...{Colors.RESET}")
        emb_summary_context = generate_embedding(summaries['summary_context']) if summaries['summary_context'] else None
        emb_summary_event = generate_embedding(summaries['summary_event']) if summaries['summary_event'] else None
        emb_summary_significance = generate_embedding(summaries['summary_significance']) if summaries['summary_significance'] else None
        emb_takeaway = generate_embedding(summaries['takeaway']) if summaries['takeaway'] else None
        emb_key_details = generate_embedding(summaries['key_details']) if summaries['key_details'] else None

        if not emb_key_details and summaries['key_details']:
            print(f"  {Colors.YELLOW}⚠ Failed to generate key_details embedding{Colors.RESET}")

        # 3. Score emotions (using retrieval system's emotion scorer)
        print(f"  {Colors.YELLOW}→ Scoring emotions...{Colors.RESET}")
        emotion = score_emotion(transcript)

        # 4. Update database
        print(f"  {Colors.YELLOW}→ Updating database...{Colors.RESET}")
        conn = psycopg2.connect(**DB_CFG)
        cur = conn.cursor()

        try:
            cur.execute("""
                UPDATE episodic_memories
                SET
                    summary_context = %s,
                    summary_event = %s,
                    summary_significance = %s,
                    summary_tone = %s,
                    takeaway = %s,
                    key_details = %s,
                    emb_summary_context = %s,
                    emb_summary_event = %s,
                    emb_summary_significance = %s,
                    emb_takeaway = %s,
                    emb_key_details = %s,
                    emotion_label = %s,
                    valence = %s,
                    arousal = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (
                summaries['summary_context'],
                summaries['summary_event'],
                summaries['summary_significance'],
                summaries['summary_tone'],
                summaries['takeaway'],
                summaries['key_details'],
                emb_summary_context,
                emb_summary_event,
                emb_summary_significance,
                emb_takeaway,
                emb_key_details,
                emotion['emotion_label'],
                emotion['valence'],
                emotion['arousal'],
                memory_id
            ))

            conn.commit()
            print(f"  {Colors.BRIGHT_GREEN}✓ Memory {memory_id} updated successfully{Colors.RESET}")

            # Show key_details for verification
            print(f"  {Colors.BRIGHT_MAGENTA}Key Details:{Colors.RESET} {summaries['key_details'][:100]}...")

            return True

        except Exception as e:
            conn.rollback()
            print(f"  {Colors.BRIGHT_RED}✗ Database error: {e}{Colors.RESET}")
            return False

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        print(f"  {Colors.BRIGHT_RED}✗ Processing error: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        return False


async def reprocess_test_set():
    """Re-process all 72 test memories"""

    # Load test set
    test_set_path = os.path.join(os.path.dirname(__file__), 'test_set.json')

    if not os.path.exists(test_set_path):
        print(f"{Colors.BRIGHT_RED}Error: test_set.json not found{Colors.RESET}")
        print(f"Expected: {test_set_path}")
        print(f"Run: python create_test_set.py first")
        return

    with open(test_set_path, 'r') as f:
        test_set = json.load(f)

    memory_ids = [m['id'] for m in test_set['memories']]

    print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
    print(f"RE-PROCESSING TEST SET WITH IMPROVED MEMORY CREATION")
    print(f"{'='*80}{Colors.RESET}\n")
    print(f"Total memories: {len(memory_ids)}")
    print(f"Categories: {test_set['metadata']['total_categories']}")
    print(f"\nImprovements:")
    print(f"  • Relaxed sentence limits (2 → 3-4 sentences)")
    print(f"  • Added KEY_DETAILS field with category-aware prompts")
    print(f"  • Category-specific hints for different memory types")
    print(f"  • 5 embeddings instead of 4")

    # Fetch all test memories from database
    conn = psycopg2.connect(**DB_CFG)
    cur = conn.cursor(cursor_factory=DictCursor)

    cur.execute("""
        SELECT id, transcript, category
        FROM episodic_memories
        WHERE id = ANY(%s)
        ORDER BY id
    """, (memory_ids,))

    memories = cur.fetchall()
    cur.close()
    conn.close()

    print(f"\n{Colors.BRIGHT_CYAN}Starting re-processing...{Colors.RESET}\n")

    # Process each memory
    success_count = 0
    fail_count = 0

    for i, mem in enumerate(memories, 1):
        print(f"{Colors.BRIGHT_YELLOW}[{i}/{len(memories)}]{Colors.RESET}")

        success = await reprocess_single_memory(
            mem['id'],
            mem['transcript'],
            mem['category'],
            conv_title=None
        )

        if success:
            success_count += 1
        else:
            fail_count += 1

    # Summary
    print(f"\n{Colors.BRIGHT_MAGENTA}{'='*80}")
    print(f"RE-PROCESSING COMPLETE")
    print(f"{'='*80}{Colors.RESET}\n")
    print(f"Total memories: {len(memories)}")
    print(f"{Colors.BRIGHT_GREEN}Successfully updated: {success_count}{Colors.RESET}")
    if fail_count > 0:
        print(f"{Colors.BRIGHT_RED}Failed: {fail_count}{Colors.RESET}")

    print(f"\n{Colors.BRIGHT_CYAN}Next step:{Colors.RESET}")
    print(f"  Run: python test_v2_stratified.py")
    print(f"  This will test self-retrieval on the re-processed memories")
    print(f"  Target: >70% self-retrieval rate")


if __name__ == "__main__":
    asyncio.run(reprocess_test_set())

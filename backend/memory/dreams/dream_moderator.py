#!/usr/bin/env python3
"""
Dream Moderator - Main Orchestrator for Iris's Dream System

Coordinates the complete dream lifecycle:
1. Emotional analysis
2. Dream type selection
3. Context preparation
4. Dream phase (10 turns)
5. Reflection phase (5 turns)
6. JSON extraction
7. Scoring & embedding
8. Database storage
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

import asyncio
import argparse
from datetime import date, datetime, timedelta
from typing import Dict, Optional

# Import all dream system modules
from emotional_analyzer import analyze_daily_emotions
from dream_type_selector import select_dream_type
from context_builder import build_dream_context
from conversation_manager import DreamConversation
from loop_detector import LoopDetector
from reflection_tracker import ReflectionTracker
from json_extractor import extract_reflection_with_fallback
from dream_scorer import score_and_embed_dream
from dream_storage import store_dream

# ============================================
# DREAM MODERATOR CLASS
# ============================================

class DreamModerator:
    """Main orchestrator for dream sequences"""

    def __init__(self, target_date: Optional[date] = None, force_type: Optional[str] = None):
        """
        Initialize dream moderator

        Args:
            target_date: Date to process (defaults to today)
            force_type: Force a specific dream type (for testing)
        """
        self.target_date = target_date or date.today()
        self.force_type = force_type

        self.start_time = None
        self.dream_id = None

        print(f"[DreamModerator] Initialized for {self.target_date}")
        if force_type:
            print(f"[DreamModerator] Forcing dream type: {force_type}")

    async def run(self) -> Optional[int]:
        """
        Execute complete dream sequence

        Returns:
            Dream ID if successful, None otherwise
        """
        self.start_time = datetime.now()

        print(f"\n{'='*60}")
        print(f" DREAM MODERATOR - {self.target_date}")
        print(f"{'='*60}\n")

        try:
            # Step 1: Emotional Analysis
            print(f"\n--- STEP 1: Emotional Analysis ---")
            emotional_analysis = analyze_daily_emotions(self.target_date)

            # Step 2: Dream Type Selection
            print(f"\n--- STEP 2: Dream Type Selection ---")
            print(f"[DreamModerator.run] self.force_type = {self.force_type}")
            if self.force_type:
                print(f"[DreamModerator.run] Using forced type: {self.force_type}")
                selection = {
                    'dream_type': self.force_type,
                    'reason': 'Manually forced for testing',
                    'confidence': 1.0,
                    'metadata': emotional_analysis
                }
            else:
                print(f"[DreamModerator.run] Calling select_dream_type()")
                selection = select_dream_type(emotional_analysis)

            dream_type = selection['dream_type']
            print(f"✓ Selected: {dream_type}")
            print(f"  Reason: {selection['reason']}")
            print(f"  Confidence: {selection['confidence']:.1%}")

            # Step 3: Context Preparation
            print(f"\n--- STEP 3: Context Preparation ---")
            dream_context = build_dream_context(dream_type, selection['metadata'])

            # Step 4 & 5: Run Dream Conversation (10 + 5 turns)
            print(f"\n--- STEPS 4 & 5: Dream Conversation ---")
            # Pass source_date for daily_consolidation dreams
            source_date = selection['metadata'].get('source_date') if dream_type in ['daily_consolidation', 'emotional_processing'] else None
            conversation = await self._run_dream_conversation(dream_context, dream_type, source_date)

            if not conversation:
                print(f"[DreamModerator] ✗ Dream conversation failed")
                return None

            # Step 6: Extract Reflection Data
            print(f"\n--- STEP 6: Reflection Extraction ---")
            reflection_data = self._extract_reflection(conversation)

            if not reflection_data:
                print(f"[DreamModerator] ✗ Reflection extraction failed")
                return None

            # Step 7: Score and Embed
            print(f"\n--- STEP 7: Scoring & Embedding ---")
            full_transcript = conversation.get_full_transcript()
            scores_and_embeddings = score_and_embed_dream(full_transcript, reflection_data)

            # Step 8: Store to Database
            print(f"\n--- STEP 8: Database Storage ---")
            self.dream_id = await self._store_dream(
                dream_type=dream_type,
                conversation=conversation,
                reflection_data=reflection_data,
                scores_and_embeddings=scores_and_embeddings,
                selection=selection
            )

            # Summary
            duration = (datetime.now() - self.start_time).total_seconds()
            print(f"\n{'='*60}")
            print(f" DREAM COMPLETE")
            print(f"{'='*60}")
            print(f"Dream ID: {self.dream_id}")
            print(f"Type: {dream_type}")
            print(f"Theme: {reflection_data.get('theme', 'unknown')}")
            print(f"Duration: {duration:.1f} seconds")
            print(f"{'='*60}\n")

            return self.dream_id

        except Exception as e:
            print(f"[DreamModerator] ✗ Fatal error: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _run_dream_conversation(
        self,
        dream_context: str,
        dream_type: str,
        source_date = None
    ) -> Optional[DreamConversation]:
        """Run the 15-turn dream conversation with loop detection"""

        conversation = DreamConversation(dream_context, dream_type, source_date)
        loop_detector = LoopDetector()

        # Initialize
        conversation._initialize_contexts()

        # Dream Phase (10 turns)
        print(f"\n  🌙 Starting Dream Phase (10 turns)")
        for i in range(10):
            # Check for loops
            variety_injection = loop_detector.apply_variety_injection()
            if variety_injection:
                # Inject variety into Freud's context as a user message
                conversation.freud_history.append({
                    "role": "user",
                    "content": f"{variety_injection}"
                })

            # Execute turn
            freud_msg, iris_response = await conversation.dream_turn()

            if not freud_msg or not iris_response:
                print(f"[DreamModerator] ✗ Dream turn {conversation.turn} failed")
                break

            # Track responses for loop detection
            loop_detector.add_response('freud', freud_msg)
            loop_detector.add_response('iris', iris_response)

        print(f"  ✓ Dream phase complete ({conversation.turn} turns)")

        # Reflection Phase (5 turns)
        print(f"\n  💭 Starting Reflection Phase (5 turns)")
        await conversation.transition_to_reflection()

        reflection_tracker = ReflectionTracker()

        for i in range(5):
            # Guide Freud to ask for next field
            next_prompt = reflection_tracker.get_prompt_for_next_field()

            if next_prompt:
                # Add prompt guidance to Freud's context as a user message
                conversation.freud_history.append({
                    "role": "user",
                    "content": next_prompt
                })

            # Execute turn
            freud_msg, iris_response = await conversation.dream_turn()

            if not freud_msg or not iris_response:
                print(f"[DreamModerator] ✗ Reflection turn {conversation.turn} failed")
                break

            # Try to extract field from Iris's response
            reflection_tracker.extract_field_from_response(iris_response)

            # Show progress
            print(f"  Progress: {reflection_tracker.get_completion_percentage():.0f}%")

        print(f"  ✓ Reflection phase complete")
        print(f"  Final: {reflection_tracker.get_progress_summary()}")

        # Attach tracker's collected data to conversation for later use
        conversation.reflection_tracker_data = reflection_tracker.get_collected_data()

        return conversation

    def _extract_reflection(self, conversation: DreamConversation) -> Optional[Dict]:
        """Extract reflection data from conversation"""

        # First, try to use data from the ReflectionTracker (collected in real-time)
        tracker_data = getattr(conversation, 'reflection_tracker_data', None)

        if tracker_data:
            # Count how many fields the tracker collected
            tracker_fields = [f for f, v in tracker_data.items() if v]
            print(f"[DreamModerator] Using ReflectionTracker data ({len(tracker_fields)} fields collected)")

            # Use tracker data as primary source
            reflection_data = tracker_data.copy()

            # Validate we got something
            required_fields = ['summary', 'mood', 'theme', 'top_3_emotions', 'takeaway']
            missing = [f for f in required_fields if not reflection_data.get(f)]

            if missing:
                print(f"[DreamModerator] ⚠ Missing fields: {missing}")

            return reflection_data

        # Fallback: Try JSON extraction from transcript (legacy method)
        print(f"[DreamModerator] No tracker data, falling back to JSON extraction")

        # Get reflection transcript
        reflection_transcript_list = []
        for entry in conversation.full_transcript:
            if entry['phase'] == 'reflection':
                reflection_transcript_list.append({
                    'turn': entry['turn'],
                    'speaker': entry['speaker'].lower(),
                    entry['speaker'].lower(): entry['content']
                })

        # Get Freud's final response (should contain JSON)
        final_freud_response = ""
        for entry in reversed(conversation.full_transcript):
            if entry['speaker'] == 'Freud' and entry['phase'] == 'reflection':
                final_freud_response = entry['content']
                break

        # Extract with fallback
        reflection_data = extract_reflection_with_fallback(
            final_freud_response,
            reflection_transcript_list
        )

        # Validate we got something
        required_fields = ['summary', 'mood', 'theme', 'top_3_emotions', 'takeaway']
        missing = [f for f in required_fields if not reflection_data.get(f)]

        if missing:
            print(f"[DreamModerator] ⚠ Missing fields: {missing}")

        return reflection_data

    async def _store_dream(
        self,
        dream_type: str,
        conversation: DreamConversation,
        reflection_data: Dict,
        scores_and_embeddings: Dict,
        selection: Dict
    ) -> Optional[int]:
        """Store dream to database"""

        # Calculate duration
        duration = int((datetime.now() - self.start_time).total_seconds())

        # Prepare metadata
        metadata = {
            'source_date': selection['metadata'].get('source_date') if dream_type == 'emotional_processing' else None,
            'freud_model': 'qwen2.5:14b',
            'iris_model': 'qwen3:32b',
            'dream_duration_seconds': duration
        }

        # Get transcripts
        full_transcript = conversation.get_full_transcript()
        dream_phase_transcript = conversation.get_phase_transcript('dream')
        reflection_phase_transcript = conversation.get_phase_transcript('reflection')

        # Store
        dream_id = store_dream(
            dream_date=self.target_date,
            dream_type=dream_type,
            full_transcript=full_transcript,
            dream_phase_transcript=dream_phase_transcript,
            reflection_phase_transcript=reflection_phase_transcript,
            reflection_data=reflection_data,
            scores_and_embeddings=scores_and_embeddings,
            metadata=metadata
        )

        return dream_id

# ============================================
# CLI INTERFACE
# ============================================

async def main():
    """Main CLI entry point"""

    parser = argparse.ArgumentParser(description='Iris Dream Moderator')

    parser.add_argument(
        '--date',
        type=str,
        help='Target date (YYYY-MM-DD), defaults to today'
    )

    parser.add_argument(
        '--dream-type',
        type=str,
        choices=['emotional_processing', 'memory_consolidation', 'identity_exploration', 'creative_random', 'daily_consolidation'],
        help='Force a specific dream type (for testing)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without storing to database'
    )

    args = parser.parse_args()

    # Parse date
    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            print(f"✗ Invalid date format: {args.date}. Use YYYY-MM-DD")
            return

    # Create moderator
    print(f"[CLI] Creating moderator with force_type={args.dream_type}")
    moderator = DreamModerator(
        target_date=target_date,
        force_type=args.dream_type
    )

    # Run dream
    print(f"[CLI] Starting dream run, moderator.force_type={moderator.force_type}")
    dream_id = await moderator.run()

    if dream_id:
        print(f"\n✓ Dream creation successful!")
        print(f"Dream ID: {dream_id}")
    else:
        print(f"\n✗ Dream creation failed")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

"""
Compare Lexicon-based vs Transformer-based Psychological Scoring

This script runs both scoring methods on the same topics and compares results.
Useful for:
- Validating transformer improvements
- Understanding scoring differences
- Choosing appropriate method for your use case
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)

from psychological_scoring import (
    score_topic as score_topic_lexicon,
    get_topic_messages,
    get_all_topics
)

from psychological_scoring_transformers import (
    score_topic as score_topic_transformer,
    ScoringConfig
)

import pandas as pd
from typing import List, Dict
import time

# ============================================
# COMPARISON FUNCTIONS
# ============================================

def compare_single_topic(session_id: str, topic_id: int, messages: List[Dict]) -> Dict:
    """
    Score a single topic with both methods and compare

    Args:
        session_id: Session UUID
        topic_id: Topic ID
        messages: List of message dicts

    Returns:
        Dict with comparison results
    """
    print(f"\n{'='*80}")
    print(f"COMPARING SCORING METHODS")
    print(f"Topic {topic_id} in session {session_id}")
    print(f"{'='*80}\n")

    # Time lexicon-based scoring
    print("[LEXICON METHOD]")
    start = time.time()
    lexicon_scores = score_topic_lexicon(session_id, topic_id, messages)
    lexicon_time = time.time() - start
    print(f"Completed in {lexicon_time:.2f}s\n")

    # Time transformer-based scoring
    print("[TRANSFORMER METHOD]")
    start = time.time()
    transformer_scores = score_topic_transformer(session_id, topic_id, messages)
    transformer_time = time.time() - start
    print(f"Completed in {transformer_time:.2f}s\n")

    # Calculate differences
    comparison = {
        'session_id': session_id,
        'topic_id': topic_id,
        'message_count': len(messages),
        'token_count': lexicon_scores['token_count'],

        # Lexicon scores
        'lexicon_arousal': lexicon_scores['arousal'],
        'lexicon_valence': lexicon_scores['valence'],
        'lexicon_novelty': lexicon_scores['novelty'],
        'lexicon_coherence': lexicon_scores['coherence'],
        'lexicon_cohesion': lexicon_scores['cohesion'],
        'lexicon_recurrence': lexicon_scores['recurrence'],
        'lexicon_time': lexicon_time,

        # Transformer scores
        'transformer_arousal': transformer_scores['arousal'],
        'transformer_valence': transformer_scores['valence'],
        'transformer_novelty': transformer_scores['novelty'],
        'transformer_coherence': transformer_scores['coherence'],
        'transformer_cohesion': transformer_scores['cohesion'],
        'transformer_recurrence': transformer_scores['recurrence'],
        'transformer_time': transformer_time,

        # Differences (transformer - lexicon)
        'diff_arousal': transformer_scores['arousal'] - lexicon_scores['arousal'],
        'diff_valence': transformer_scores['valence'] - lexicon_scores['valence'],
        'diff_novelty': transformer_scores['novelty'] - lexicon_scores['novelty'],
        'diff_coherence': transformer_scores['coherence'] - lexicon_scores['coherence'],
        'diff_cohesion': transformer_scores['cohesion'] - lexicon_scores['cohesion'],
        'diff_recurrence': transformer_scores['recurrence'] - lexicon_scores['recurrence'],
    }

    return comparison

def print_comparison_summary(comparison: Dict):
    """Print a formatted summary of the comparison"""
    print(f"\n{'='*80}")
    print("COMPARISON SUMMARY")
    print(f"{'='*80}")

    print(f"\nMetadata:")
    print(f"  Messages: {comparison['message_count']}")
    print(f"  Tokens:   {comparison['token_count']}")

    print(f"\nPerformance:")
    print(f"  Lexicon method:     {comparison['lexicon_time']:.2f}s")
    print(f"  Transformer method: {comparison['transformer_time']:.2f}s")
    print(f"  Speedup factor:     {comparison['lexicon_time']/comparison['transformer_time']:.2f}x")

    print(f"\nScore Comparison:")
    print(f"{'Metric':<15} {'Lexicon':<10} {'Transformer':<12} {'Difference':<12}")
    print(f"{'-'*50}")

    metrics = ['arousal', 'valence', 'novelty', 'coherence', 'cohesion', 'recurrence']
    for metric in metrics:
        lex_score = comparison[f'lexicon_{metric}']
        trans_score = comparison[f'transformer_{metric}']
        diff = comparison[f'diff_{metric}']

        # Format with appropriate precision
        if metric == 'valence':
            print(f"{metric.capitalize():<15} {lex_score:>+9.3f} {trans_score:>+11.3f} {diff:>+11.3f}")
        else:
            print(f"{metric.capitalize():<15} {lex_score:>9.3f} {trans_score:>11.3f} {diff:>+11.3f}")

    print(f"{'='*80}\n")

def compare_multiple_topics(num_topics: int = 5):
    """
    Compare scoring methods across multiple topics

    Args:
        num_topics: Number of topics to compare (default 5)
    """
    print(f"\n{'='*80}")
    print(f"MULTI-TOPIC COMPARISON ({num_topics} topics)")
    print(f"{'='*80}\n")

    topics = get_all_topics()
    if not topics:
        print("No topics found in database")
        return

    # Limit to requested number
    topics = topics[:num_topics]

    comparisons = []

    for session_id, topic_id in topics:
        messages = get_topic_messages(session_id, topic_id)
        if not messages:
            continue

        comparison = compare_single_topic(session_id, topic_id, messages)
        comparisons.append(comparison)

    # Create summary DataFrame
    df = pd.DataFrame(comparisons)

    print(f"\n{'='*80}")
    print("AGGREGATE STATISTICS")
    print(f"{'='*80}\n")

    print("Average Scores:")
    print(f"{'Metric':<15} {'Lexicon Mean':<15} {'Transformer Mean':<18} {'Avg Difference'}")
    print(f"{'-'*65}")

    metrics = ['arousal', 'valence', 'novelty', 'coherence', 'cohesion', 'recurrence']
    for metric in metrics:
        lex_mean = df[f'lexicon_{metric}'].mean()
        trans_mean = df[f'transformer_{metric}'].mean()
        diff_mean = df[f'diff_{metric}'].mean()

        if metric == 'valence':
            print(f"{metric.capitalize():<15} {lex_mean:>+14.3f} {trans_mean:>+17.3f} {diff_mean:>+11.3f}")
        else:
            print(f"{metric.capitalize():<15} {lex_mean:>14.3f} {trans_mean:>17.3f} {diff_mean:>+11.3f}")

    print(f"\nAverage Processing Times:")
    print(f"  Lexicon:     {df['lexicon_time'].mean():.2f}s")
    print(f"  Transformer: {df['transformer_time'].mean():.2f}s")

    print(f"\n{'='*80}\n")

    # Save to CSV
    output_file = "scoring_comparison_results.csv"
    df.to_csv(output_file, index=False)
    print(f"Results saved to: {output_file}\n")

    return df

# ============================================
# MAIN EXECUTION
# ============================================

def main():
    """Main comparison workflow"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare lexicon-based vs transformer-based psychological scoring"
    )
    parser.add_argument(
        '--num-topics',
        type=int,
        default=5,
        help='Number of topics to compare (default: 5)'
    )
    parser.add_argument(
        '--single',
        action='store_true',
        help='Test only a single topic (first available)'
    )
    parser.add_argument(
        '--device',
        type=str,
        choices=['cpu', 'cuda'],
        help='Force device for transformer models (default: auto-detect)'
    )

    args = parser.parse_args()

    # Override device if specified
    if args.device:
        ScoringConfig.DEVICE = args.device
        print(f"[Config] Forcing device: {args.device}")

    # Print configuration
    print("\n" + "="*80)
    print("PSYCHOLOGICAL SCORING COMPARISON TOOL")
    print("="*80)
    print(f"Transformer device: {ScoringConfig.DEVICE}")
    print("="*80)

    if args.single:
        # Single topic comparison
        topics = get_all_topics()
        if not topics:
            print("No topics found in database")
            return

        session_id, topic_id = topics[0]
        messages = get_topic_messages(session_id, topic_id)

        if messages:
            comparison = compare_single_topic(session_id, topic_id, messages)
            print_comparison_summary(comparison)
    else:
        # Multiple topics comparison
        compare_multiple_topics(num_topics=args.num_topics)

if __name__ == "__main__":
    main()

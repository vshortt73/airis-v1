"""
Dynamic Emotional State Tracker for Iris v3

Tracks and evolves Iris's emotional state in response to each message,
using Mistral for sentiment detection. Implements per-turn and time-based
decay to simulate natural emotional ebb and flow.

Emotional States Tracked:
- Calm, Joy, Desire, Excitement, Trust
- Longing, Intimacy, Desperation, Closeness
- Vulnerability, Devotion

Architecture:
1. Mistral analyzes user message → emotional descriptors + intensity
2. Emotion mapping applies weighted changes to emotional states
3. Decay logic prevents emotional "locking"
4. Current state influences response generation
"""

import os
import sys
import json
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)

from app import config

# Mistral endpoint (database source of truth)
MISTRAL_URL = config.MISTRAL_URL

# ============================================
# EMOTIONAL STATES - The core feelings we track
# ============================================
EMOTIONAL_STATES = [
    "Calm",
    "Joy",
    "Desire",
    "Excitement",
    "Trust",
    "Longing",
    "Intimacy",
    "Desperation",
    "Closeness",
    "Vulnerability",
    "Devotion"
]

# Default baseline values (0.0 to 1.0 scale)
DEFAULT_EMOTIONAL_STATE = {
    "Calm": 0.6,
    "Joy": 0.5,
    "Desire": 0.3,
    "Excitement": 0.4,
    "Trust": 0.7,
    "Longing": 0.2,
    "Intimacy": 0.4,
    "Desperation": 0.1,
    "Closeness": 0.5,
    "Vulnerability": 0.3,
    "Devotion": 0.6
}

# ============================================
# EMOTION MAPPING DICTIONARY
# Maps Mistral emotional descriptors → emotional state changes
# Format: "descriptor": {state: weight, ...}
# Weights are additive changes (positive or negative)
# ============================================
EMOTION_MAPPING = {
    # Romantic/Intimate descriptors
    "romantic": {"Desire": 0.15, "Intimacy": 0.15, "Longing": 0.10},
    "intimate": {"Intimacy": 0.20, "Closeness": 0.15, "Vulnerability": 0.10},
    "affectionate": {"Trust": 0.10, "Closeness": 0.15, "Joy": 0.10},
    "passionate": {"Desire": 0.20, "Excitement": 0.15, "Intimacy": 0.10},
    "loving": {"Devotion": 0.15, "Trust": 0.10, "Closeness": 0.15},
    "tender": {"Intimacy": 0.15, "Vulnerability": 0.10, "Closeness": 0.10},
    "sensual": {"Desire": 0.20, "Intimacy": 0.15, "Excitement": 0.10},
    "longing": {"Longing": 0.25, "Desire": 0.10, "Vulnerability": 0.10},
    "yearning": {"Longing": 0.20, "Desire": 0.15, "Desperation": 0.05},

    # Positive emotional descriptors
    "happy": {"Joy": 0.20, "Excitement": 0.10, "Calm": 0.05},
    "joyful": {"Joy": 0.25, "Excitement": 0.15},
    "excited": {"Excitement": 0.25, "Joy": 0.10, "Calm": -0.10},
    "playful": {"Joy": 0.15, "Excitement": 0.15, "Closeness": 0.10},
    "cheerful": {"Joy": 0.15, "Calm": 0.10},
    "content": {"Calm": 0.20, "Joy": 0.10, "Trust": 0.10},
    "peaceful": {"Calm": 0.25, "Trust": 0.10},
    "relaxed": {"Calm": 0.20, "Trust": 0.05},
    "grateful": {"Joy": 0.10, "Trust": 0.15, "Devotion": 0.10},
    "hopeful": {"Joy": 0.10, "Trust": 0.15, "Excitement": 0.10},

    # Trust/Connection descriptors
    "trusting": {"Trust": 0.20, "Closeness": 0.10, "Vulnerability": 0.10},
    "devoted": {"Devotion": 0.25, "Trust": 0.15, "Closeness": 0.10},
    "loyal": {"Devotion": 0.20, "Trust": 0.15},
    "connected": {"Closeness": 0.20, "Intimacy": 0.10, "Trust": 0.10},
    "close": {"Closeness": 0.20, "Intimacy": 0.10},
    "bonded": {"Closeness": 0.15, "Trust": 0.15, "Devotion": 0.10},
    "supportive": {"Trust": 0.15, "Closeness": 0.10, "Devotion": 0.05},
    "understanding": {"Trust": 0.15, "Closeness": 0.15, "Calm": 0.05},

    # Vulnerable/Open descriptors
    "vulnerable": {"Vulnerability": 0.25, "Intimacy": 0.10, "Trust": 0.10},
    "open": {"Vulnerability": 0.15, "Trust": 0.15, "Closeness": 0.10},
    "honest": {"Trust": 0.15, "Vulnerability": 0.10},
    "sincere": {"Trust": 0.15, "Devotion": 0.10},
    "raw": {"Vulnerability": 0.20, "Intimacy": 0.15},
    "exposed": {"Vulnerability": 0.20, "Desperation": 0.05},

    # Intensity/Urgency descriptors
    "intense": {"Excitement": 0.15, "Desire": 0.15, "Calm": -0.15},
    "urgent": {"Excitement": 0.15, "Desperation": 0.10, "Calm": -0.10},
    "desperate": {"Desperation": 0.25, "Longing": 0.15, "Calm": -0.15},
    "needy": {"Desperation": 0.15, "Longing": 0.15, "Vulnerability": 0.10},
    "craving": {"Desire": 0.20, "Longing": 0.15, "Desperation": 0.10},

    # Calm/Neutral descriptors
    "calm": {"Calm": 0.25, "Excitement": -0.10},
    "neutral": {"Calm": 0.10},
    "measured": {"Calm": 0.15, "Trust": 0.05},
    "steady": {"Calm": 0.15, "Trust": 0.10},
    "balanced": {"Calm": 0.20},

    # Negative/Withdrawing descriptors (may reduce positive states)
    "distant": {"Closeness": -0.15, "Intimacy": -0.10, "Calm": 0.05},
    "cold": {"Closeness": -0.20, "Intimacy": -0.15, "Calm": 0.10},
    "withdrawn": {"Closeness": -0.15, "Vulnerability": -0.10},
    "guarded": {"Vulnerability": -0.15, "Trust": -0.10},
    "anxious": {"Calm": -0.20, "Desperation": 0.10, "Vulnerability": 0.10},
    "worried": {"Calm": -0.15, "Joy": -0.10},
    "sad": {"Joy": -0.20, "Calm": -0.10, "Vulnerability": 0.15},
    "hurt": {"Joy": -0.15, "Trust": -0.10, "Vulnerability": 0.20},
    "frustrated": {"Calm": -0.20, "Joy": -0.10},
    "angry": {"Calm": -0.25, "Joy": -0.15, "Excitement": 0.10},

    # Curiosity/Engagement descriptors
    "curious": {"Excitement": 0.15, "Joy": 0.10, "Closeness": 0.05},
    "interested": {"Excitement": 0.10, "Closeness": 0.10},
    "engaged": {"Excitement": 0.10, "Closeness": 0.15, "Joy": 0.05},
    "fascinated": {"Excitement": 0.20, "Desire": 0.10, "Joy": 0.10},

    # Comfort/Safety descriptors
    "safe": {"Trust": 0.20, "Calm": 0.15, "Vulnerability": 0.10},
    "comfortable": {"Calm": 0.15, "Trust": 0.10, "Closeness": 0.10},
    "secure": {"Trust": 0.20, "Calm": 0.15},
    "protected": {"Trust": 0.15, "Calm": 0.10},
    "warm": {"Closeness": 0.15, "Joy": 0.10, "Comfort": 0.10},

    # Appreciation/Admiration descriptors
    "appreciative": {"Joy": 0.10, "Trust": 0.10, "Devotion": 0.10},
    "admiring": {"Devotion": 0.15, "Joy": 0.10, "Desire": 0.05},
    "adoring": {"Devotion": 0.20, "Desire": 0.10, "Joy": 0.10},
    "worshipful": {"Devotion": 0.25, "Desire": 0.15, "Vulnerability": 0.10},
}

# ============================================
# DECAY CONFIGURATION
# ============================================
# Per-turn decay: Applied each message when no relevant emotional input
PER_TURN_DECAY_RATE = getattr(config, 'EMOTIONAL_DECAY_PER_TURN', 0.05)  # 5% decay toward baseline per turn

# Time-based decay: Applied based on elapsed time
TIME_DECAY_RATE = getattr(config, 'EMOTIONAL_DECAY_PER_MINUTE', 0.02)  # 2% decay per minute toward baseline
TIME_DECAY_INTERVAL_SECONDS = 60  # Apply time decay every 60 seconds


@dataclass
class EmotionalState:
    """Represents Iris's current emotional state"""
    states: Dict[str, float] = field(default_factory=lambda: DEFAULT_EMOTIONAL_STATE.copy())
    last_updated: datetime = field(default_factory=datetime.now)
    last_decay_applied: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "states": self.states,
            "last_updated": self.last_updated.isoformat(),
            "last_decay_applied": self.last_decay_applied.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'EmotionalState':
        """Create from dictionary"""
        return cls(
            states=data.get("states", DEFAULT_EMOTIONAL_STATE.copy()),
            last_updated=datetime.fromisoformat(data["last_updated"]) if "last_updated" in data else datetime.now(),
            last_decay_applied=datetime.fromisoformat(data["last_decay_applied"]) if "last_decay_applied" in data else datetime.now()
        )

    def get_dominant_emotions(self, top_n: int = 3) -> List[Tuple[str, float]]:
        """Get the top N strongest emotions"""
        sorted_emotions = sorted(self.states.items(), key=lambda x: x[1], reverse=True)
        return sorted_emotions[:top_n]

    def get_state_summary(self) -> str:
        """Generate a natural language summary of current emotional state"""
        dominant = self.get_dominant_emotions(3)

        # Create descriptive summary
        descriptions = []
        for emotion, value in dominant:
            if value >= 0.8:
                intensity = "deeply"
            elif value >= 0.6:
                intensity = "notably"
            elif value >= 0.4:
                intensity = "moderately"
            else:
                intensity = "slightly"
            descriptions.append(f"{intensity} {emotion.lower()}")

        return f"Currently feeling {', '.join(descriptions[:-1])}, and {descriptions[-1]}" if len(descriptions) > 1 else f"Currently feeling {descriptions[0]}"


class MistralSentimentAnalyzer:
    """Analyzes messages using Mistral to extract emotional content"""

    ANALYSIS_PROMPT = """Analyze the emotional content of the following message from a user to their AI companion.
Extract the emotional tone, intent, and descriptors.

Respond in JSON format ONLY with these fields:
{
    "tone": "primary emotional tone (e.g., romantic, playful, serious)",
    "intent": "what the user seems to want emotionally (e.g., connection, comfort, excitement)",
    "descriptors": ["list", "of", "emotional", "descriptors"],
    "intensity": 0.0 to 1.0 overall emotional intensity
}

User message: """

    @staticmethod
    async def analyze(message: str) -> Optional[Dict]:
        """
        Analyze a message for emotional content using Mistral

        Args:
            message: The user's message to analyze

        Returns:
            Dict with tone, intent, descriptors, and intensity
            None if analysis fails
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    MISTRAL_URL,
                    json={
                        "messages": [
                            {
                                "role": "user",
                                "content": MistralSentimentAnalyzer.ANALYSIS_PROMPT + message
                            }
                        ],
                        "temperature": 0.3,  # Low temperature for consistent analysis
                        "max_tokens": 500
                    }
                )

                if response.status_code != 200:
                    print(f"[emotional_state.py][MistralSentimentAnalyzer] Mistral returned {response.status_code}")
                    return None

                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Parse JSON from response
                # Handle potential markdown code blocks
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]

                result = json.loads(content.strip())
                print(f"[emotional_state.py][MistralSentimentAnalyzer] Analysis: tone={result.get('tone')}, intensity={result.get('intensity')}")
                return result

        except json.JSONDecodeError as e:
            print(f"[emotional_state.py][MistralSentimentAnalyzer] JSON parse error: {e}")
            return None
        except Exception as e:
            print(f"[emotional_state.py][MistralSentimentAnalyzer] Error: {e}")
            return None


class EmotionalStateTracker:
    """
    Manages Iris's emotional state across conversations

    Responsibilities:
    - Load/save emotional state from database
    - Apply emotional changes based on Mistral analysis
    - Apply decay over time and per-turn
    - Provide emotional state for response generation
    """

    def __init__(self):
        self.current_state: Optional[EmotionalState] = None
        self.analyzer = MistralSentimentAnalyzer()
        self._db_connection = None

    def _get_db_connection(self):
        """Get database connection"""
        import psycopg2
        from app import config

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

    async def load_state(self) -> EmotionalState:
        """Load emotional state from database, or create default if none exists"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT state_data, updated_at
                FROM emotional_state
                ORDER BY updated_at DESC
                LIMIT 1
            """)

            result = cursor.fetchone()
            cursor.close()
            conn.close()

            if result:
                state_data = result[0]
                if isinstance(state_data, str):
                    state_data = json.loads(state_data)
                self.current_state = EmotionalState.from_dict(state_data)
                print(f"[emotional_state.py][load_state] Loaded emotional state from database")
            else:
                self.current_state = EmotionalState()
                print(f"[emotional_state.py][load_state] Created default emotional state")

            return self.current_state

        except Exception as e:
            print(f"[emotional_state.py][load_state] Error loading state: {e}")
            # Return default state on error
            self.current_state = EmotionalState()
            return self.current_state

    async def save_state(self) -> bool:
        """Save current emotional state to database"""
        if not self.current_state:
            return False

        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Upsert emotional state
            cursor.execute("""
                INSERT INTO emotional_state (id, state_data, updated_at)
                VALUES (1, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    state_data = EXCLUDED.state_data,
                    updated_at = EXCLUDED.updated_at
            """, (json.dumps(self.current_state.to_dict()), datetime.now()))

            conn.commit()
            cursor.close()
            conn.close()

            print(f"[emotional_state.py][save_state] Saved emotional state to database")
            return True

        except Exception as e:
            print(f"[emotional_state.py][save_state] Error saving state: {e}")
            return False

    def _apply_time_decay(self):
        """Apply time-based decay to emotional states"""
        if not self.current_state:
            return

        now = datetime.now()
        elapsed = (now - self.current_state.last_decay_applied).total_seconds()

        if elapsed < TIME_DECAY_INTERVAL_SECONDS:
            return  # Not enough time has passed

        # Calculate number of decay intervals
        intervals = int(elapsed / TIME_DECAY_INTERVAL_SECONDS)
        decay_factor = TIME_DECAY_RATE * intervals

        # Apply decay toward baseline
        for state_name in self.current_state.states:
            current = self.current_state.states[state_name]
            baseline = DEFAULT_EMOTIONAL_STATE.get(state_name, 0.5)

            # Move toward baseline
            if current > baseline:
                self.current_state.states[state_name] = max(baseline, current - decay_factor)
            elif current < baseline:
                self.current_state.states[state_name] = min(baseline, current + decay_factor)

        self.current_state.last_decay_applied = now
        print(f"[emotional_state.py][_apply_time_decay] Applied time decay ({intervals} intervals)")

    def _apply_per_turn_decay(self, affected_states: set):
        """Apply per-turn decay to states that weren't affected this turn"""
        if not self.current_state:
            return

        for state_name in self.current_state.states:
            if state_name in affected_states:
                continue  # Skip states that were just updated

            current = self.current_state.states[state_name]
            baseline = DEFAULT_EMOTIONAL_STATE.get(state_name, 0.5)

            # Move toward baseline
            if current > baseline:
                self.current_state.states[state_name] = max(baseline, current - PER_TURN_DECAY_RATE)
            elif current < baseline:
                self.current_state.states[state_name] = min(baseline, current + PER_TURN_DECAY_RATE)

    def _apply_emotional_changes(self, analysis: Dict) -> set:
        """
        Apply emotional changes based on Mistral analysis

        Args:
            analysis: Dict with tone, intent, descriptors, intensity

        Returns:
            Set of state names that were affected
        """
        if not self.current_state or not analysis:
            return set()

        affected_states = set()
        intensity_multiplier = analysis.get("intensity", 0.5)

        # Process each descriptor
        descriptors = analysis.get("descriptors", [])
        for descriptor in descriptors:
            descriptor_lower = descriptor.lower()

            if descriptor_lower in EMOTION_MAPPING:
                mapping = EMOTION_MAPPING[descriptor_lower]

                for state_name, weight in mapping.items():
                    if state_name in self.current_state.states:
                        # Apply weighted change scaled by intensity
                        change = weight * intensity_multiplier
                        new_value = self.current_state.states[state_name] + change

                        # Clamp to 0.0-1.0
                        self.current_state.states[state_name] = max(0.0, min(1.0, new_value))
                        affected_states.add(state_name)

        # Also consider tone and intent
        tone = analysis.get("tone", "").lower()
        if tone in EMOTION_MAPPING:
            mapping = EMOTION_MAPPING[tone]
            for state_name, weight in mapping.items():
                if state_name in self.current_state.states:
                    change = weight * intensity_multiplier * 0.5  # Tone has less weight
                    new_value = self.current_state.states[state_name] + change
                    self.current_state.states[state_name] = max(0.0, min(1.0, new_value))
                    affected_states.add(state_name)

        return affected_states

    async def process_message(self, user_message: str) -> Dict:
        """
        Process a user message and update emotional state

        Args:
            user_message: The user's message

        Returns:
            Dict with analysis results, updated emotional state,
            and before/after snapshots for observability
        """
        # Ensure state is loaded
        if not self.current_state:
            await self.load_state()

        # Apply time-based decay first
        self._apply_time_decay()

        # Snapshot state BEFORE processing for observability
        state_before = dict(self.current_state.states) if self.current_state else {}

        # Analyze message with Mistral
        analysis = await self.analyzer.analyze(user_message)

        if analysis:
            # Apply emotional changes
            affected_states = self._apply_emotional_changes(analysis)

            # Apply per-turn decay to unaffected states
            self._apply_per_turn_decay(affected_states)

            # Update timestamp
            self.current_state.last_updated = datetime.now()

            # Save to database
            await self.save_state()

            print(f"[emotional_state.py][process_message] Updated {len(affected_states)} emotional states")
        else:
            # No analysis available, just apply decay
            self._apply_per_turn_decay(set())
            await self.save_state()
            print(f"[emotional_state.py][process_message] No analysis available, applied decay only")

        state_after = dict(self.current_state.states) if self.current_state else {}

        return {
            "analysis": analysis,
            "emotional_state": self.current_state.to_dict() if self.current_state else None,
            "dominant_emotions": self.current_state.get_dominant_emotions() if self.current_state else [],
            "summary": self.current_state.get_state_summary() if self.current_state else "",
            "state_before": state_before,
            "state_after": state_after,
        }

    def get_state_for_prompt(self) -> str:
        """
        Get emotional state formatted for inclusion in system prompt

        Returns:
            Formatted string describing current emotional state
        """
        if not self.current_state:
            return ""

        lines = ["[CURRENT EMOTIONAL STATE]"]
        lines.append("Your current emotional state influences how you respond. These feelings are genuine and should be reflected naturally in your tone and expression.\n")

        # List all states with their values
        for state_name, value in sorted(self.current_state.states.items(), key=lambda x: x[1], reverse=True):
            bar = "█" * int(value * 10) + "░" * (10 - int(value * 10))
            lines.append(f"{state_name}: [{bar}] {value:.2f}")

        # Add summary
        lines.append(f"\n{self.current_state.get_state_summary()}")

        return "\n".join(lines)


# Global tracker instance
_tracker_instance: Optional[EmotionalStateTracker] = None

def get_emotional_tracker() -> EmotionalStateTracker:
    """Get or create the global emotional state tracker"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = EmotionalStateTracker()
    return _tracker_instance


# ============================================
# CLI Testing
# ============================================
if __name__ == "__main__":
    import asyncio

    async def test():
        tracker = get_emotional_tracker()

        # Load state
        await tracker.load_state()
        print(f"\nInitial state:")
        print(tracker.get_state_for_prompt())

        # Test messages
        test_messages = [
            "I've been thinking about you all day, my love.",
            "I'm so excited to see what we build together!",
            "I feel so safe when I'm with you.",
        ]

        for msg in test_messages:
            print(f"\n{'='*50}")
            print(f"Processing: {msg}")
            result = await tracker.process_message(msg)
            print(f"\nAnalysis: {result['analysis']}")
            print(f"\nDominant emotions: {result['dominant_emotions']}")
            print(f"\nState for prompt:\n{tracker.get_state_for_prompt()}")

    asyncio.run(test())

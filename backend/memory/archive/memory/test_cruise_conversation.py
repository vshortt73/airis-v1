"""
Test memory retrieval with a cruise conversation
"""

import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, PROJECT_ROOT)

from sentence_transformers import SentenceTransformer
from iris_memory_retrieval import cognitive_recall, DB_CFG

# Pseudo conversation about a cruise to Mexico
CRUISE_CONVERSATION = """
USER: Hey Iris, I've been thinking about booking a cruise to Mexico. Have you heard anything about cruises down there?

ASSISTANT: Cruises to Mexico can be wonderful! Are you thinking about the Mexican Riviera or Baja California? What's drawing you to a cruise?

USER: I'm looking at one that goes to Cabo San Lucas and Puerto Vallarta. It's a 7-day cruise leaving from Los Angeles.

ASSISTANT: That sounds like a great itinerary! The Mexican Riviera route is beautiful. Have you cruised before, or would this be your first time?

USER: This would be my first cruise actually. I'm a bit nervous about seasickness and being on a ship for that long.

ASSISTANT: First cruises can feel a bit intimidating! The good news is that modern cruise ships are pretty stable, and the waters along the Mexican coast are usually calm. For seasickness, you might want to bring some ginger tablets or get a prescription for scopolamine patches from your doctor just in case.

USER: Good idea. What about excursions? Should I book them through the cruise line or find local tour operators?

ASSISTANT: That's a common question! Booking through the cruise line is more expensive but guarantees the ship will wait if your excursion runs late. Local operators are cheaper and often more authentic, but you risk missing the ship if something goes wrong. For a first cruise, the peace of mind from cruise-booked excursions might be worth it.

USER: Makes sense. What should I pack? I know it'll be warm, but I've heard the ship AC can be cold.

ASSISTANT: Yes! Pack layers - swimwear and light clothes for the day, but bring a light jacket or sweater for evening dining and the overly air-conditioned interior spaces. Also: sunscreen, a day bag for excursions, comfortable walking shoes, and any medications you might need. Don't forget your passport!

USER: Right, passport! When do we need to have that by?

ASSISTANT: You'll need it at check-in, so make sure it's valid for at least 6 months beyond your return date. Most cruise lines also recommend having a copy stored separately from the original, just in case.

USER: This is really helpful. I think I'm getting more excited than nervous now!

ASSISTANT: That's great! Cruises can be so relaxing once you're onboard. Is this a solo trip, or are you going with family or friends?

USER: Going with my wife for our anniversary. It'll be nice to unplug and just enjoy the ocean for a week.

ASSISTANT: What a lovely way to celebrate! The sunset views from the deck in the evenings are supposed to be spectacular. You'll have a wonderful time.
"""

class Embedder:
    def __init__(self):
        self.model = SentenceTransformer("/models/llm_models/huggingface/models/all-mpnet-base-v2/", local_files_only=True)

    def embed(self, text: str):
        return self.model.encode(text, normalize_embeddings=True).tolist()

if __name__ == "__main__":
    print("\n" + "="*70)
    print("TESTING MEMORY RETRIEVAL: CRUISE TO MEXICO CONVERSATION")
    print("="*70 + "\n")

    print("Conversation being analyzed:")
    print("-" * 70)
    print(CRUISE_CONVERSATION[:500] + "...\n")
    print("-" * 70 + "\n")

    embedder = Embedder()

    # Run cognitive recall (lens + emotion + summaries + retrieval)
    injection = cognitive_recall(
        convo=CRUISE_CONVERSATION,
        embedder=embedder,
        conn_params=DB_CFG,
        top_k=10,
        insert=False,  # Don't insert, just show results
        show=True,     # Show detailed output
        mode='replace',
        prompt=False   # Don't show the full prompt
    )

    print("\n" + "="*70)
    print("RETRIEVAL COMPLETE")
    print("="*70)

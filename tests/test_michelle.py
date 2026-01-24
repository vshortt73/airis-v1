from transformers import pipeline

def run_emotion_tracker():
    # Initialize the emotion classifier
    # This downloads the model on first run; thereafter it is 100% offline
    classifier = pipeline(
        "text-classification", 
        model="michellejieli/emotion_text_classifier", 
        top_k=None  # Returns scores for ALL emotions, not just the top one
    )

    # Test harness for interpersonal dialogue
    test_messages = [
        "I can't believe you forgot our anniversary again.", # Likely Anger/Sadness
        "I'm actually a bit worried about how much we've been arguing.", # Fear/Sadness
        "That's so kind of you, thank you!", # Joy
        "I don't really have an opinion on that.", # Neutral
        "Wait, you actually finished the whole project already?", # Surprise
        "Then don't hold back. tell me exactly what you want me to do. where to kiss, to touch - and all the things that come after where love is made."
    ]

    print(f"{'Message':<60} | {'Primary Emotion':<15} | {'Score'}")
    print("-" * 85)

    for message in test_messages:
        # Perform inference
        results = classifier(message)[0]
        
        # Sort results to get the highest confidence emotion
        top_emotion = sorted(results, key=lambda x: x['score'], reverse=True)[0]
        
        emotion_label = top_emotion['label']
        confidence = top_emotion['score']

        print(f"{message[:58]:<60} | {emotion_label:<15} | {confidence:.4f}")

if __name__ == "__main__":
    run_emotion_tracker()
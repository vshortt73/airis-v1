from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

def run_sentiment_harness():
    # Initialize the analyzer (runs entirely offline)
    analyzer = SentimentIntensityAnalyzer()
    
    # Test cases representing interpersonal communication
    conversations = [
        "That sounds fine.",                        # Neutral/Polite
        "That sounds GREAT!!",                      # Positive (punctuation/caps emphasis)
        "I am not happy with how this is going.",   # Negative
        "It's not that I'm mad, just disappointed.", # Nuanced/Mixed
        "Sure, whatever you want. 🙄",               # Sarcasm (VADER handles some emojis)
        "I KIND OF like the idea, but it's risky."  # Qualified sentiment
    ]

    print(f"{'Text':<50} | {'Compound':<10} | {'Sentiment'}")
    print("-" * 75)

    for text in conversations:
        # Get sentiment scores
        # Returns a dict: {'neg', 'neu', 'pos', 'compound'}
        scores = analyzer.polarity_scores(text)
        compound = scores['compound']

        # Classify based on standard VADER thresholds
        if compound >= 0.05:
            sentiment = "Positive"
        elif compound <= -0.05:
            sentiment = "Negative"
        else:
            sentiment = "Neutral"

        print(f"{text:<50} | {compound:<10.4f} | {sentiment}")

if __name__ == "__main__":
    run_sentiment_harness()
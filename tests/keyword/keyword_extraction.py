"""
V4 Memory System - Keyword Extraction
Extracts meaningful keywords from user queries for fast memory search
"""

import re
from typing import List, Set, Tuple
from collections import Counter


class KeywordExtractor:
    """
    Smart keyword extraction for memory queries
    Designed to find the "real" content words that will match memories
    """
    
    def __init__(self):
        # Words that appear in queries but don't help find memories
        self.stop_words = self._load_stop_words()
        self.query_meta_words = self._load_query_meta_words()
        self.temporal_words = self._load_temporal_words()
        
    def extract(self, query: str) -> List[str]:
        """
        Extract keywords from a user query
        
        Args:
            query: User's question (e.g., "Remember our conversation about loop detection?")
            
        Returns:
            List of keywords in order of importance
            
        Example:
            >>> extractor = KeywordExtractor()
            >>> extractor.extract("Remember our conversation about loop detection?")
            ['loop detection', 'loop', 'detection']
        """
        # Step 1: Basic cleaning - remove punctuation first
        query = re.sub(r'[^\w\s-]', ' ', query)
        query = query.lower().strip()
        
        # Step 2: Extract multi-word phrases (most important)
        phrases = self._extract_phrases(query)
        
        # Step 3: Extract individual significant words
        words = self._extract_words(query)
        
        # Step 4: Remove noise words
        filtered_words = self._filter_noise(words)
        
        # Step 5: Combine and rank
        keywords = self._rank_keywords(phrases, filtered_words)
        
        # Step 6: Clean up the final keywords
        keywords = self._clean_keywords(keywords)
        
        return keywords
    
    def extract_with_context(self, query: str) -> dict:
        """
        Extract keywords plus additional context about the query
        
        Returns:
            {
                'keywords': [...],
                'temporal_reference': 'last week' | None,
                'query_type': 'historical' | 'current' | 'general',
                'has_specific_topic': True | False
            }
        """
        keywords = self.extract(query)
        
        return {
            'keywords': keywords,
            'temporal_reference': self._extract_temporal_reference(query),
            'query_type': self._classify_query_type(query),
            'has_specific_topic': len(keywords) > 0
        }
    
    def _extract_phrases(self, query: str) -> List[str]:
        """
        Extract multi-word phrases that should stay together
        
        Examples:
            "loop detection" -> keep together
            "dream system" -> keep together
            "GPU allocation" -> keep together
        """
        phrases = []
        
        # Pattern 1: "about X" or "regarding X"
        about_pattern = r'(?:about|regarding|concerning)\s+([a-z\s]+?)(?:\s+(?:last|this|yesterday|when|that|\?|$))'
        matches = re.findall(about_pattern, query)
        for match in matches:
            phrase = match.strip()
            if len(phrase.split()) <= 4:  # Only keep reasonable length phrases
                phrases.append(phrase)
        
        # Pattern 2: Quoted phrases
        quoted = re.findall(r'"([^"]+)"', query)
        phrases.extend(quoted)
        
        # Pattern 3: Common technical/concept phrases (2-3 words)
        # Look for noun + noun or adjective + noun patterns
        words = query.split()
        for i in range(len(words) - 1):
            # Simple heuristic: if both words are not in stop words, might be a phrase
            if (words[i] not in self.stop_words and 
                words[i+1] not in self.stop_words and
                words[i] not in self.query_meta_words):
                potential_phrase = f"{words[i]} {words[i+1]}"
                # Only keep if it seems like a real concept
                if self._looks_like_concept(potential_phrase):
                    phrases.append(potential_phrase)
        
        return list(set(phrases))  # Remove duplicates
    
    def _extract_words(self, query: str) -> List[str]:
        """
        Extract individual words from query
        """
        # Remove punctuation except hyphens (for terms like "self-aware")
        query = re.sub(r'[^\w\s-]', ' ', query)
        
        # Split into words
        words = query.split()
        
        return words
    
    def _filter_noise(self, words: List[str]) -> List[str]:
        """
        Remove stop words, query meta-words, and temporal words
        """
        filtered = []
        
        for word in words:
            word = word.lower().strip()
            
            # Skip if empty or too short
            if len(word) < 2:
                continue
            
            # Skip if it's noise
            if (word in self.stop_words or 
                word in self.query_meta_words or
                word in self.temporal_words):
                continue
            
            filtered.append(word)
        
        return filtered
    
    def _rank_keywords(self, phrases: List[str], words: List[str]) -> List[str]:
        """
        Combine phrases and words, rank by importance
        
        Priority:
            1. Multi-word phrases (most specific)
            2. Individual content words
            3. Remove duplicates (words already in phrases)
        """
        keywords = []
        
        # Add phrases first (highest priority)
        keywords.extend(phrases)
        
        # Add individual words that aren't already in phrases
        phrase_words = set()
        for phrase in phrases:
            phrase_words.update(phrase.split())
        
        for word in words:
            if word not in phrase_words:
                keywords.append(word)
        
        return keywords
    
    def _clean_keywords(self, keywords: List[str]) -> List[str]:
        """
        Final cleanup of extracted keywords
        """
        cleaned = []
        
        for keyword in keywords:
            # Strip whitespace
            keyword = keyword.strip()
            
            # Remove if empty or too short
            if len(keyword) < 2:
                continue
            
            # Remove if it's just noise words
            if keyword in self.stop_words or keyword in self.query_meta_words:
                continue
            
            # Remove phrases that are just "word about" or "about word"
            if re.match(r'^(about|from|with|using)\s+\w+$', keyword):
                continue
            if re.match(r'^\w+\s+(about|from|with|using)$', keyword):
                continue
            
            cleaned.append(keyword)
        
        return cleaned
    
    def _extract_temporal_reference(self, query: str) -> str | None:
        """
        Extract time references from query
        
        Examples:
            "last week" -> "last week"
            "yesterday" -> "yesterday"
            "three days ago" -> "three days ago"
        """
        temporal_patterns = [
            r'(yesterday)',
            r'(last (?:night|week|month|year))',
            r'(this (?:morning|week|month|year))',
            r'(\d+ (?:day|week|month|year)s? ago)',
            r'(recently)',
            r'(earlier)',
            r'(previously)',
        ]
        
        for pattern in temporal_patterns:
            match = re.search(pattern, query.lower())
            if match:
                return match.group(1)
        
        return None
    
    def _classify_query_type(self, query: str) -> str:
        """
        Classify the type of query
        
        Returns:
            'historical' - asking about past conversations
            'current' - asking about current state
            'general' - general question
        """
        query_lower = query.lower()
        
        # Historical query indicators
        historical_patterns = [
            r'\bremember\b',
            r'\brecall\b',
            r'\bwhat did (we|i)\b',
            r'\bearlier\b',
            r'\bpreviously\b',
            r'\blast (week|month|time)\b',
            r'\bago\b',
            r'\bconversation about\b',
            r'\bdiscussed\b',
        ]
        
        for pattern in historical_patterns:
            if re.search(pattern, query_lower):
                return 'historical'
        
        # Current state indicators
        current_patterns = [
            r'\bcurrent\b',
            r'\bwhat (am i|are we) working on\b',
            r'\bwhat should\b',
            r'\btoday\b',
            r'\bright now\b',
        ]
        
        for pattern in current_patterns:
            if re.search(pattern, query_lower):
                return 'current'
        
        return 'general'
    
    def _looks_like_concept(self, phrase: str) -> bool:
        """
        Heuristic to determine if a phrase looks like a real concept
        """
        words = phrase.split()
        
        # Too short or too long
        if len(words) < 2 or len(words) > 3:
            return False
        
        # Contains temporal words (probably not a concept)
        if any(w in self.temporal_words for w in words):
            return False
        
        # All words too short (probably not meaningful)
        if all(len(w) < 3 for w in words):
            return False
        
        return True
    
    def _load_stop_words(self) -> Set[str]:
        """
        Common English stop words that don't help find memories
        """
        return {
            'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for',
            'from', 'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on',
            'that', 'the', 'to', 'was', 'will', 'with', 'we', 'you',
            'i', 'me', 'my', 'our', 'your', 'his', 'her', 'their',
            'this', 'these', 'those', 'what', 'which', 'who', 'how',
            'why', 'when', 'where', 'there', 'here', 'some', 'any',
            'can', 'could', 'would', 'should', 'may', 'might', 'must',
        }
    
    def _load_query_meta_words(self) -> Set[str]:
        """
        Words that appear in queries but don't describe the content
        """
        return {
            'remember', 'recall', 'remind', 'forgot', 'forget',
            'conversation', 'discussed', 'talked', 'mentioned', 'said',
            'tell', 'told', 'asked', 'question', 'answer',
            'chat', 'discussion', 'topic', 'subject',
            'please', 'can', 'could', 'would', 'help',
        }
    
    def _load_temporal_words(self) -> Set[str]:
        """
        Time-related words that don't help find content
        """
        return {
            'yesterday', 'today', 'tomorrow',
            'last', 'next', 'this', 'recent', 'recently',
            'ago', 'earlier', 'later', 'previously',
            'morning', 'afternoon', 'evening', 'night',
            'day', 'week', 'month', 'year',
            'when', 'time',
        }


def test_keyword_extraction():
    """
    Test the keyword extractor with various query types
    """
    extractor = KeywordExtractor()
    
    test_queries = [
        "Remember our conversation about loop detection?",
        "What did we discuss about the dream system last week?",
        "Tell me about GPU allocation",
        "Earlier you mentioned string theory",
        "What are my current projects?",
        "Remember when we talked about consciousness yesterday?",
        "What did we decide about the variety injection implementation?",
    ]
    
    print("Keyword Extraction Test Results:")
    print("=" * 80)
    
    for query in test_queries:
        result = extractor.extract_with_context(query)
        
        print(f"\nQuery: {query}")
        print(f"  Keywords: {result['keywords']}")
        print(f"  Temporal: {result['temporal_reference']}")
        print(f"  Type: {result['query_type']}")
        print(f"  Has topic: {result['has_specific_topic']}")


if __name__ == "__main__":
    test_keyword_extraction()
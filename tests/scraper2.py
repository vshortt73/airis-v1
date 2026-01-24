import requests
from bs4 import BeautifulSoup
from readability import Document
import feedparser
from urllib.parse import urlparse, quote_plus

# -------------------------
# Helper functions
# -------------------------

def extract_article(url):
    """Extract main text from a friendly page using readability-lxml."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()

    doc = Document(r.text)
    html = doc.summary(html_partial=True)
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "iframe", "aside"]):
        tag.decompose()

    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(strip=True)) > 40
    ]

    return {
        "title": doc.title(),
        "text": "\n\n".join(paragraphs)
    }


def get_rss_summary(url, max_items=5):
    """Attempt to find an RSS feed for a domain and return latest item."""
    domain = urlparse(url).netloc
    rss_url = f"https://{domain}/rss"
    
    # Common NYTimes style feeds
    common_feeds = [
        f"https://{domain}/rss",
        f"https://{domain}/feed",
        f"https://{domain}/feeds/posts/default"
    ]
    
    for feed_url in common_feeds:
        feed = feedparser.parse(feed_url)
        if feed.entries:
            entry = feed.entries[0]
            return {
                "title": entry.title,
                "summary": entry.get("summary", ""),
                "link": entry.link
            }
    return None


def ddg_search(query, max_results=5):
    """DuckDuckGo HTML search for discovery."""
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.post(url, data={"q": query}, headers=headers, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    for res in soup.select(".result")[:max_results]:
        a = res.select_one(".result__a")
        snippet = res.select_one(".result__snippet")
        if not a:
            continue
        results.append({
            "title": a.get_text(strip=True),
            "link": a["href"],
            "snippet": snippet.get_text(strip=True) if snippet else ""
        })
    return results


# -------------------------
# Main Web Surfer
# -------------------------

def web_surf(target, use_search=True):
    """
    Given a URL or query:
    - If URL: try RSS → readability → fallback
    - If query: search DDG → try URLs
    Returns structured dict or list of dicts
    """
    # Check if target looks like a URL
    if target.startswith("http"):
        # 1. Try RSS
        rss = get_rss_summary(target)
        if rss:
            return {
                "title": rss["title"],
                "text": rss["summary"],
                "url": rss["link"],
                "source": urlparse(target).netloc,
                "snippet": rss["summary"]
            }

        # 2. Try readability extraction
        try:
            article = extract_article(target)
            return {
                "title": article["title"],
                "text": article["text"],
                "url": target,
                "source": urlparse(target).netloc,
                "snippet": article["text"][:300]
            }
        except Exception:
            pass

        # 3. Fallback minimal
        return {
            "title": target,
            "text": "Unable to extract content, returning URL only",
            "url": target,
            "source": urlparse(target).netloc,
            "snippet": ""
        }

    else:
        # Treat target as a search query
        if not use_search:
            return []

        ddg_results = ddg_search(target, max_results=5)
        structured_results = []

        for res in ddg_results:
            try:
                article = extract_article(res["link"])
                text = article["text"]
                title = article["title"]
            except Exception:
                text = res["snippet"]
                title = res["title"]

            structured_results.append({
                "title": title,
                "text": text,
                "url": res["link"],
                "source": urlparse(res["link"]).netloc,
                "snippet": res["snippet"]
            })

        return structured_results


if __name__ == "__main__":
    # 1️⃣ Direct URL (friendly site)
    url_result = web_surf("https://www.nytimes.com/2026/01/04/briefing/the-venezuela-takeover.html")
    print("\nURL Result:")
    print(url_result["title"])
    print(url_result["snippet"])
    print(url_result["url"])

    # 2️⃣ Query search (DuckDuckGo)
  #  search_results = web_surf("U.S.+invasion+Venezuela+2025+official+statements")
  #  print("\nSearch Results:")
  #  for r in search_results:
  #      print(r["title"])
  #      print(r["snippet"])
  #      print(r["url"])
  #      print("---")

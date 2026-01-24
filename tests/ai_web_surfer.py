import asyncio
import aiohttp
from bs4 import BeautifulSoup
from readability import Document
import feedparser
from urllib.parse import urlparse, urljoin, quote_plus

# -------------------------
# Async HTTP Fetch
# -------------------------
async def fetch(session, url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }
    try:
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status == 200:
                return await resp.text()
            return None
    except Exception:
        return None

# -------------------------
# Article Extraction
# -------------------------
async def extract_article_async(session, url):
    html = await fetch(session, url)
    if not html:
        return None
    doc = Document(html)
    soup = BeautifulSoup(doc.summary(html_partial=True), "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "aside"]):
        tag.decompose()
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(strip=True)) > 40
    ]
    return {
        "title": doc.title(),
        "text": "\n\n".join(paragraphs),
        "url": url,
        "source": urlparse(url).netloc,
        "snippet": "\n".join(paragraphs[:40])
    }

# -------------------------
# RSS Feed Fallback
# -------------------------
def get_rss_summary(url):
    domain = urlparse(url).netloc
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
                "text": entry.get("summary", ""),
                "url": entry.link,
                "source": domain,
                "snippet": entry.get("summary", "")
            }
    return None

# -------------------------
# Link Extraction
# -------------------------
def extract_links(base_url, html, max_links=3):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http"):
            links.append(href)
        else:
            links.append(urljoin(base_url, href))
        if len(links) >= max_links:
            break
    return links

# -------------------------
# Crawl Function (async)
# -------------------------
async def crawl_url(session, url, depth=1, max_links=3):
    results = []

    html = await fetch(session, url)
    if not html:
        rss = get_rss_summary(url)
        if rss:
            return [rss]
        return [{"title": url, "text": "", "url": url, "source": urlparse(url).netloc, "snippet": ""}]

    article = await extract_article_async(session, url)
    if article:
        results.append(article)

    if depth > 0:
        links = extract_links(url, html, max_links)
        tasks = [crawl_url(session, link, depth=depth-1, max_links=max_links) for link in links]
        nested = await asyncio.gather(*tasks)
        for n in nested:
            results.extend(n)

    return results

# -------------------------
# DuckDuckGo Search
# -------------------------
async def ddg_search(query, max_results=5):
    url = "https://html.duckduckgo.com/html/"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data={"q": query}, headers={"User-Agent": "Mozilla/5.0"}) as r:
            html = await r.text()
    soup = BeautifulSoup(html, "html.parser")
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
async def ai_web_surf(targets, depth=1, max_links=3):
    """
    targets: list of URLs or search queries
    Returns structured text results for AI consumption
    """
    results = []

    async with aiohttp.ClientSession() as session:
        for target in targets:
            if target.startswith("http"):
                res = await crawl_url(session, target, depth=depth, max_links=max_links)
                results.extend(res)
            else:
                # treat as search query
                search_results = await ddg_search(target)
                tasks = [crawl_url(session, r["link"], depth=depth, max_links=max_links) for r in search_results]
                search_texts = await asyncio.gather(*tasks)
                for page_list in search_texts:
                    results.extend(page_list)

    return results

# -------------------------
# Example Usage
# -------------------------
if __name__ == "__main__":
    queries = [
        "Python web scraping tutorial",
        "Latest AI news"
    ]
    results = asyncio.run(ai_web_surf(queries, depth=1, max_links=2))

    for i, r in enumerate(results[:100], 1):
         if len(r["snippet"]) > 15:
            print(f"snippet length: {len(r["snippet"])}")
            print(f"\n{i}. {r['title']}")
            print(r["snippet"])
            print(r["url"])

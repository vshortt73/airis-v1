"""
Web Surfer - Async web crawling and content extraction
Provides search, crawl, and article extraction capabilities with comprehensive
timeout protection, rate limiting, and quality filtering.
"""

import asyncio
import aiohttp
import logging
import time
from bs4 import BeautifulSoup
from readability import Document
import feedparser
from urllib.parse import urlparse, urljoin, quote_plus
from urllib.robotparser import RobotFileParser
from typing import Optional, List, Dict, Any, Set
from dataclasses import dataclass
from collections import defaultdict

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class WebSurferConfig:
    """Configuration for web surfer timeouts and limits"""
    FETCH_TIMEOUT: int = 15
    ARTICLE_TIMEOUT: int = 10
    RSS_TIMEOUT: int = 8
    NESTED_CRAWL_TIMEOUT_PER_LINK: int = 20
    URL_CRAWL_TIMEOUT_PER_URL: int = 30
    DDG_TIMEOUT: int = 10
    MIN_PARAGRAPH_LENGTH: int = 40
    MAX_SNIPPET_PARAGRAPHS: int = 40
    MAX_RETRIES: int = 2
    RATE_LIMIT_RPS: float = 5.0  # Requests per second per domain
    MIN_CONTENT_LENGTH: int = 200  # Minimum article length
    MIN_WORD_DIVERSITY: float = 0.3  # Minimum unique word ratio
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

# ============================================================================
# LOGGING SETUP
# ============================================================================

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(name)s] %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# ============================================================================
# UTILITY CLASSES
# ============================================================================

class RateLimiter:
    """Rate limiter to avoid overwhelming servers"""

    def __init__(self, requests_per_second: float = 5.0):
        self.rps = requests_per_second
        self.last_request: Dict[str, float] = defaultdict(float)

    async def wait_if_needed(self, domain: str) -> None:
        """Wait if we're making requests too quickly to this domain"""
        now = time.time()
        time_since_last = now - self.last_request[domain]
        min_interval = 1.0 / self.rps

        if time_since_last < min_interval:
            wait_time = min_interval - time_since_last
            logger.debug(f"Rate limiting {domain}: waiting {wait_time:.2f}s")
            await asyncio.sleep(wait_time)

        self.last_request[domain] = time.time()

class RobotsChecker:
    """Check robots.txt compliance"""

    def __init__(self):
        self.parsers: Dict[str, RobotFileParser] = {}

    async def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        """Check if we're allowed to fetch this URL"""
        try:
            domain = urlparse(url).netloc
            if domain not in self.parsers:
                rp = RobotFileParser()
                rp.set_url(f"https://{domain}/robots.txt")
                # Run synchronous read in executor
                loop = asyncio.get_event_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(None, rp.read),
                    timeout=5
                )
                self.parsers[domain] = rp

            return self.parsers[domain].can_fetch(user_agent, url)
        except Exception as e:
            logger.debug(f"Could not check robots.txt for {url}: {e}")
            return True  # If can't read, assume allowed

# ============================================================================
# CONTENT QUALITY VALIDATION
# ============================================================================

def is_quality_content(article: Optional[Dict[str, Any]], config: WebSurferConfig) -> bool:
    """Check if extracted article has meaningful content"""
    if not article or not article.get("text"):
        return False

    text = article["text"]

    # Too short = probably an error page or navigation
    if len(text) < config.MIN_CONTENT_LENGTH:
        logger.debug(f"Content too short for {article.get('url')}: {len(text)} chars")
        return False

    # Too much repetition = probably boilerplate
    words = text.lower().split()
    if len(words) > 0:
        diversity = len(set(words)) / len(words)
        if diversity < config.MIN_WORD_DIVERSITY:
            logger.debug(f"Content too repetitive for {article.get('url')}: {diversity:.2f}")
            return False

    return True

def filter_link_quality(url: str) -> bool:
    """Filter out common junk URLs"""
    SKIP_PATTERNS = [
        '/search', '/tag/', '/category/', 'javascript:',
        'mailto:', '#', '/login', '/signup', '/register',
        '/cart', '/checkout', '/account', '.pdf', '.zip',
        '/wp-admin', '/admin'
    ]

    url_lower = url.lower()
    return not any(pattern in url_lower for pattern in SKIP_PATTERNS)

# ============================================================================
# WEB SURFER CLASS
# ============================================================================

class WebSurfer:
    """Main web surfer class with crawling, extraction, and search capabilities"""

    def __init__(self, config: Optional[WebSurferConfig] = None):
        self.config = config or WebSurferConfig()
        self.session: Optional[aiohttp.ClientSession] = None
        self.crawled_urls: Set[str] = set()
        self.rate_limiter = RateLimiter(self.config.RATE_LIMIT_RPS)
        self.robots_checker = RobotsChecker()

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    # ========================================================================
    # HTTP FETCHING
    # ========================================================================

    async def fetch(self, url: str, timeout: Optional[int] = None) -> Optional[str]:
        """
        Fetch HTML content from URL with proper error handling

        Args:
            url: URL to fetch
            timeout: Optional timeout override

        Returns:
            HTML content as string, or None if failed
        """
        if not self.session:
            raise RuntimeError("WebSurfer must be used as async context manager")

        headers = {
            "User-Agent": self.config.USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/"
        }

        timeout_val = timeout or self.config.FETCH_TIMEOUT

        try:
            # Rate limiting
            domain = urlparse(url).netloc
            await self.rate_limiter.wait_if_needed(domain)

            async with self.session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_val)
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                elif resp.status in [301, 302, 303, 307, 308]:
                    logger.warning(f"Redirect {resp.status} for {url}")
                    return None
                else:
                    logger.warning(f"Non-200 status {resp.status} for {url}")
                    return None

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {url}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            return None

    async def fetch_with_retry(
        self,
        url: str,
        max_retries: Optional[int] = None
    ) -> Optional[str]:
        """
        Fetch URL with retry logic for transient failures

        Args:
            url: URL to fetch
            max_retries: Maximum retry attempts

        Returns:
            HTML content or None
        """
        retries = max_retries or self.config.MAX_RETRIES

        for attempt in range(retries):
            result = await self.fetch(url)
            if result:
                return result

            if attempt < retries - 1:
                wait_time = 1 * (attempt + 1)  # Exponential backoff
                logger.info(f"Retry {attempt + 1}/{retries} for {url} after {wait_time}s")
                await asyncio.sleep(wait_time)

        logger.warning(f"Failed to fetch {url} after {retries} attempts")
        return None

    # ========================================================================
    # ARTICLE EXTRACTION
    # ========================================================================

    async def extract_article(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract article content from URL using readability

        Args:
            url: URL to extract article from

        Returns:
            Dict with title, text, snippet, url, source, or None if failed
        """
        try:
            html = await asyncio.wait_for(
                self.fetch_with_retry(url),
                timeout=self.config.ARTICLE_TIMEOUT
            )

            if not html:
                return None

            # Extract main content using readability
            doc = Document(html)
            soup = BeautifulSoup(doc.summary(html_partial=True), "html.parser")

            # Remove unwanted tags
            for tag in soup(["script", "style", "noscript", "iframe", "aside"]):
                tag.decompose()

            # Extract meaningful paragraphs
            paragraphs = [
                p.get_text(" ", strip=True)
                for p in soup.find_all("p")
                if len(p.get_text(strip=True)) > self.config.MIN_PARAGRAPH_LENGTH
            ]

            if not paragraphs:
                logger.debug(f"No paragraphs found in {url}")
                return None

            article = {
                "title": doc.title(),
                "text": "\n\n".join(paragraphs),
                "url": url,
                "source": urlparse(url).netloc,
                "snippet": "\n".join(paragraphs[:self.config.MAX_SNIPPET_PARAGRAPHS])
            }

            return article

        except asyncio.TimeoutError:
            logger.warning(f"Article extraction timeout for {url}")
            return None
        except Exception as e:
            logger.error(f"Article extraction error for {url}: {e}")
            return None

    # ========================================================================
    # RSS FEED FALLBACK
    # ========================================================================

    async def get_rss_summary(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Try to get content from RSS feed as fallback

        Args:
            url: URL to check for RSS feeds

        Returns:
            Dict with feed entry data, or None if no feed found
        """
        def _sync_parse():
            """Synchronous RSS parsing function"""
            domain = urlparse(url).netloc
            common_feeds = [
                f"https://{domain}/rss",
                f"https://{domain}/feed",
                f"https://{domain}/feeds/posts/default",
                f"https://{domain}/atom.xml",
                f"https://{domain}/rss.xml"
            ]

            for feed_url in common_feeds:
                try:
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
                except Exception as e:
                    logger.debug(f"RSS parse error for {feed_url}: {e}")
                    continue

            return None

        try:
            # Run synchronous feedparser in thread pool with timeout
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, _sync_parse),
                timeout=self.config.RSS_TIMEOUT
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"RSS feed timeout for {url}")
            return None
        except Exception as e:
            logger.error(f"RSS feed error for {url}: {e}")
            return None

    # ========================================================================
    # LINK EXTRACTION
    # ========================================================================

    def extract_links(self, base_url: str, html: str, max_links: int = 3) -> List[str]:
        """
        Extract quality links from HTML

        Args:
            base_url: Base URL for resolving relative links
            html: HTML content
            max_links: Maximum number of links to extract

        Returns:
            List of absolute URLs
        """
        soup = BeautifulSoup(html, "html.parser")
        links = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]

            # Normalize URL
            if href.startswith("http"):
                full_url = href
            else:
                full_url = urljoin(base_url, href)

            # Quality filter
            if not filter_link_quality(full_url):
                continue

            # Avoid duplicates
            if full_url in seen:
                continue

            seen.add(full_url)
            links.append(full_url)

            if len(links) >= max_links:
                break

        return links

    # ========================================================================
    # URL CRAWLING
    # ========================================================================

    async def crawl_url(
        self,
        url: str,
        depth: int = 1,
        max_links: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Crawl a URL and optionally follow links

        Args:
            url: URL to crawl
            depth: How many link hops to follow (0 = just this URL)
            max_links: Maximum links to follow per page

        Returns:
            List of article dictionaries
        """
        logger.info(f"Crawling {url} (depth={depth})")
        results = []

        # Check if already crawled
        if url in self.crawled_urls:
            logger.debug(f"Already crawled {url}, skipping")
            return results

        self.crawled_urls.add(url)

        # Check robots.txt
        if not await self.robots_checker.can_fetch(url):
            logger.info(f"Blocked by robots.txt: {url}")
            return results

        # Fetch HTML
        html = None
        try:
            html = await asyncio.wait_for(
                self.fetch_with_retry(url),
                timeout=5
            )
        except asyncio.TimeoutError:
            logger.warning(f"Timeout triggered for {url}")

        # Fail fast for this URL
        if not html:
            # Try RSS fallback
            rss = await self.get_rss_summary(url)
            if rss:
                return [rss]

            # Return empty result
            return [{
                "title": url,
                "text": "",
                "url": url,
                "source": urlparse(url).netloc,
                "snippet": ""
            }]

        # Extract article
        article = await self.extract_article(url)
        if article and is_quality_content(article, self.config):
            results.append(article)
        elif article:
            logger.debug(f"Low quality content filtered from {url}")

        # Follow links if depth > 0
        if depth > 0:
            links = self.extract_links(url, html, max_links)
            logger.debug(f"Found {len(links)} quality links from {url}")

            if links:
                tasks = [
                    self.crawl_url(link, depth=depth-1, max_links=max_links)
                    for link in links
                ]

                try:
                    # Overall timeout for nested crawls
                    timeout = self.config.NESTED_CRAWL_TIMEOUT_PER_LINK * len(tasks)
                    nested = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=timeout
                    )

                    for n in nested:
                        if isinstance(n, Exception):
                            logger.error(f"Nested crawl exception: {n}")
                            continue
                        results.extend(n)

                except asyncio.TimeoutError:
                    logger.warning(f"Nested crawl timeout for links from {url}")

        return results

    # ========================================================================
    # SEARCH
    # ========================================================================

    async def ddg_search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Search DuckDuckGo for query

        Args:
            query: Search query
            max_results: Maximum number of results to return

        Returns:
            List of search result dicts with title, link, snippet
        """
        if not self.session:
            raise RuntimeError("WebSurfer must be used as async context manager")

        url = "https://html.duckduckgo.com/html/"

        try:
            async with self.session.post(
                url,
                data={"q": query},
                headers={"User-Agent": self.config.USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=self.config.DDG_TIMEOUT)
            ) as r:
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

            logger.info(f"DuckDuckGo search for '{query}' returned {len(results)} results")
            return results

        except asyncio.TimeoutError:
            logger.error(f"DuckDuckGo search timeout for query: {query}")
            return []
        except Exception as e:
            logger.error(f"DuckDuckGo search error for query '{query}': {e}")
            return []

    # ========================================================================
    # MAIN SURF FUNCTION
    # ========================================================================

    async def surf(
        self,
        targets: List[str],
        depth: int = 1,
        max_links: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Main web surfing function - handles both URLs and search queries

        Args:
            targets: List of URLs or search queries
            depth: How many link hops to follow
            max_links: Maximum links per page

        Returns:
            List of article dictionaries
        """
        results = []
        logger.info(f"Starting web surf with {len(targets)} target(s)")

        # ---- URL targets (CONCURRENT) ----
        url_targets = [t for t in targets if t.startswith("http")]
        if url_targets:
            logger.info(f"Crawling {len(url_targets)} direct URLs")

            # Filter already crawled
            new_urls = [u for u in url_targets if u not in self.crawled_urls]

            tasks = [
                self.crawl_url(url, depth=depth, max_links=max_links)
                for url in new_urls
            ]

            if tasks:
                try:
                    timeout = self.config.URL_CRAWL_TIMEOUT_PER_URL * len(tasks)
                    completed = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=timeout
                    )

                    for res in completed:
                        if isinstance(res, Exception):
                            logger.error(f"URL crawl exception: {res}")
                            continue
                        results.extend(res)

                except asyncio.TimeoutError:
                    logger.error(f"Overall timeout for URL targets: {url_targets}")

        # ---- Search queries ----
        query_targets = [t for t in targets if not t.startswith("http")]
        for query in query_targets:
            logger.info(f"Processing search query: '{query}'")

            search_results = await self.ddg_search(query)
            logger.info(f"Got {len(search_results)} search results, crawling...")

            # Filter already crawled
            new_links = [
                r["link"] for r in search_results
                if r["link"] not in self.crawled_urls
            ]

            tasks = [
                self.crawl_url(link, depth=depth, max_links=max_links)
                for link in new_links
            ]

            if tasks:
                try:
                    timeout = self.config.URL_CRAWL_TIMEOUT_PER_URL * len(tasks)
                    completed = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=timeout
                    )

                    for res in completed:
                        if isinstance(res, Exception):
                            logger.error(f"Search result crawl exception: {res}")
                            continue
                        results.extend(res)

                except asyncio.TimeoutError:
                    logger.error(f"Overall timeout for search query: {query}")

        logger.info(f"Web surf completed: {len(results)} articles extracted")
        return results

# ============================================================================
# STANDALONE FUNCTIONS (Backward Compatibility)
# ============================================================================

async def ai_web_surf(
    targets: List[str],
    depth: int = 1,
    max_links: int = 3
) -> List[Dict[str, Any]]:
    """
    Backward compatible function - creates WebSurfer instance and runs surf

    Args:
        targets: List of URLs or search queries
        depth: Link depth to follow
        max_links: Max links per page

    Returns:
        List of article dictionaries
    """
    async with WebSurfer() as surfer:
        return await surfer.surf(targets, depth=depth, max_links=max_links)

def deduplicate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate results by URL

    Args:
        results: List of article dictionaries

    Returns:
        Deduplicated list
    """
    seen = set()
    unique = []

    for r in results:
        url = r.get("url")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    return unique

async def comp_results(
    targets: List[str],
    depth: int = 1,
    max_links: int = 2,
    top_n: int = 20
) -> List[Dict[str, Any]]:
    """
    Complete results function with deduplication and limiting

    Args:
        targets: List of URLs or queries
        depth: Link depth
        max_links: Max links per page
        top_n: Maximum results to return

    Returns:
        Deduplicated and limited list of articles
    """
    results = await ai_web_surf(targets, depth=depth, max_links=max_links)

    # Deduplicate by URL
    results = deduplicate_results(results)

    # Limit results
    results = results[:top_n]

    return results

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Enable debug logging for testing
    logger.setLevel(logging.DEBUG)

    async def test():
        """Test the web surfer"""
        targets = ["Latest AI news"]

        async with WebSurfer() as surfer:
            results = await surfer.surf(targets, depth=1, max_links=2)

            print(f"\n{'='*60}")
            print(f"Found {len(results)} articles")
            print(f"{'='*60}\n")

            for i, r in enumerate(results[:5], 1):
                if r.get("snippet"):
                    print(f"{i}. {r['title']}")
                    print(f"   Source: {r['source']}")
                    print(f"   URL: {r['url']}")
                    snippet = r['snippet'][:200].replace("\n", " ")
                    print(f"   Snippet: {snippet}...\n")

    # Uncomment to run test
    # asyncio.run(test())

import asyncio
from ai_web_surfer import ai_web_surf
from urllib.parse import urlparse

# -------------------------
# Helper: Deduplicate results by URL
# -------------------------
def deduplicate_results(results):
    seen = set()
    unique = []
    for r in results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    return unique

# -------------------------
# Test harness
# -------------------------
async def test_harness(targets, depth=1, max_links=2, top_n=20):
    """
    Run the AI Web Surfer on multiple targets and return structured JSON
    targets: list of URLs or queries
    depth: how many link hops to follow
    max_links: max links per page
    top_n: how many results to return
    """
    print(f"Starting AI Web Surfer test harness with {len(targets)} targets...\n")

    results = await ai_web_surf(targets, depth=depth, max_links=max_links)

    # Deduplicate by URL
    results = deduplicate_results(results)

    # Limit results
    results = results[:top_n]

    # Print summary for quick inspection
    for i, r in enumerate(results, 1):
        if len(r['snippet']) > 15:
            print(f"\n{i}. {r['title']}")
            print(f"Source: {r['source']}")
            print(f"URL: {r['url']}")
            snippet = r['snippet'].replace("\n", " ")
            print(f"Snippet: {snippet}...")
    
    return results

# -------------------------
# Example usage
# -------------------------
if __name__ == "__main__":
    targets = [
        "U.S.+invasion+Venezuela+2025+official+statements"
    ]

    final_results = asyncio.run(test_harness(targets, depth=2, max_links=2, top_n=5))
    
    # final_results is JSON-ready for your MCP agent
    # Each item has: title, text, url, source, snippet

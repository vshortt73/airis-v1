import requests
from bs4 import BeautifulSoup

def duckduckgo_search(query, max_results=10):
    url = "https://html.duckduckgo.com/html/"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9",
    }

    r = requests.post(
        url,
        data={"q": query},
        headers=headers,
        timeout=10
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # ✅ HARD VALIDATION
    results_container = soup.select(".result")
    if not results_container:
        raise RuntimeError("DuckDuckGo did not return search results")

    results = []

    for res in results_container[:max_results]:
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


if __name__ == "__main__":
    results = duckduckgo_search("U.S.+invasion+Venezuela+2025+official+statements")

    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['title']}")
        print(r["snippet"])
        print(r["link"])

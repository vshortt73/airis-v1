"""
Iris Info Server - MCP Server for Information Tools
Provides weather, news, webcam, and web fetching capabilities
"""

import sys
from pathlib import Path
from typing import Dict, Any
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from readability import Document
import feedparser
from urllib.parse import urlparse, urljoin, quote_plus
# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Add info server directory to path for local imports
INFO_SERVER_DIR = Path(__file__).parent
sys.path.insert(0, str(INFO_SERVER_DIR))

from web_surfer import ai_web_surf

from mcp_servers.base.base_server import IrisMCPServer
import requests

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Info Server",
    description="Information retrieval tools: weather, news, webcam, web content"
)

# ============================================================================
# WEB SEARCH TOOL
# ============================================================================
@server.register_tool
async def web_search(
    query: str,
    max_size: int = 10000,
    depth: int = 1,
    max_links: int = 1):
    """
    Search the web for information using DuckDuckGo search.
    Use this when you need to search for information using keywords or phrases.

    Args:
        query: Search query or keywords (e.g., "latest AI news", "Python tutorials")
        max_size: Maximum token count for results (default: 10000)
        depth: How many link hops to follow from search results (default: 1)
        max_links: Maximum number of links to follow per page (default: 1)

    Returns:
        List of articles with titles, snippets, and URLs

    Example:
        web_search(query="latest developments in quantum computing")
    """
    output = []
    count = 0
    queries = [query]
    tcount = 0

    if query:
        print(f"[web_search] Searching for: {query}", file=sys.stderr)
        try:
            output.append({"success": True})
            print("[web_search] Getting results...", file=sys.stderr)
            results = await ai_web_surf(queries, depth=depth, max_links=max_links)
            for item in results:
                tcount = tcount + (len(item["snippet"])/4)
                if tcount < max_size:
                    count = count + 1
                    output.append({
                        f"article number {count}": {
                            "title": item["title"],
                            "snippet": item["snippet"],
                            "url": item["url"]
                        }
                    })
                else:
                    output.append({"truncation": f"max size of {max_size} tokens reached (current: {tcount})"})
                    break
            output.append({"Token Count": f"{tcount}"})
            print(f"[web_search] ✓ Found {count} articles", file=sys.stderr)
        except Exception as e:
            output.append({"success": False})
            output.append({"error": f"Search error: {e}"})
    else:
        output.append({"success": False})
        output.append({"error": "No search query provided"})
    return output


# ============================================================================
# URL FETCH TOOL
# ============================================================================
@server.register_tool
async def url_fetch(
    url: str,
    max_size: int = 10000,
    depth: int = 0,
    max_links: int = 0):
    """
    Fetch and extract content from a specific URL.
    Use this when you have a direct URL you want to read (not a search query).

    Args:
        url: Direct URL to fetch (must start with http:// or https://)
        max_size: Maximum token count for results (default: 10000)
        depth: How many link hops to follow from this page (default: 0 = just this URL)
        max_links: Maximum number of links to follow per page (default: 0)

    Returns:
        Article content with title, text, snippet, and URL

    Example:
        url_fetch(url="https://example.com/article")
    """
    output = []
    count = 0
    urls = [url]
    tcount = 0

    if url:
        if not url.startswith(('http://', 'https://')):
            output.append({"success": False})
            output.append({"error": "URL must start with http:// or https://"})
            return output

        print(f"[url_fetch] Fetching URL: {url}", file=sys.stderr)
        try:
            output.append({"success": True})
            print("[url_fetch] Getting content...", file=sys.stderr)
            results = await ai_web_surf(urls, depth=depth, max_links=max_links)
            for item in results:
                tcount = tcount + (len(item["snippet"])/4)
                if tcount < max_size:
                    count = count + 1
                    output.append({
                        f"article number {count}": {
                            "title": item["title"],
                            "snippet": item["snippet"],
                            "url": item["url"]
                        }
                    })
                else:
                    output.append({"truncation": f"max size of {max_size} tokens reached (current: {tcount})"})
                    break
            output.append({"Token Count": f"{tcount}"})
            print(f"[url_fetch] ✓ Fetched {count} article(s)", file=sys.stderr)
        except Exception as e:
            output.append({"success": False})
            output.append({"error": f"Fetch error: {e}"})
    else:
        output.append({"success": False})
        output.append({"error": "No URL provided"})
    return output


# ============================================================================
# ARXIV SEARCH TOOL
# ============================================================================
@server.register_tool
async def arxiv_search(
    query: str,
    max_results: int = 5):
    """
    Search arXiv for academic papers and preprints.
    Use this when Victor asks about research papers, scientific topics, or academic literature.

    Args:
        query: Search query (keywords, authors, titles, etc.)
        max_results: Maximum number of results to return (default: 5, max: 20)

    Returns:
        List of papers with titles, authors, abstracts, and links

    Example:
        arxiv_search(query="quantum computing error correction")
    """
    output = []

    if not query:
        output.append({"success": False})
        output.append({"error": "No search query provided"})
        return output

    try:
        # Limit max_results
        max_results = min(max_results, 20)

        print(f"[arxiv_search] Searching arXiv for: {query}", file=sys.stderr)

        # arXiv API endpoint
        base_url = "http://export.arxiv.org/api/query"
        params = {
            'search_query': f'all:{query}',
            'start': 0,
            'max_results': max_results,
            'sortBy': 'relevance',
            'sortOrder': 'descending'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(base_url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    output.append({"success": False})
                    output.append({"error": f"arXiv API returned status {response.status}"})
                    return output

                xml_data = await response.text()

        # Parse XML response
        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml_data)

        # Namespace for arXiv API
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'arxiv': 'http://arxiv.org/schemas/atom'
        }

        entries = root.findall('atom:entry', ns)

        if not entries:
            output.append({"success": True})
            output.append({"message": f"No papers found for query: {query}"})
            return output

        output.append({"success": True})
        output.append({"count": len(entries)})

        for idx, entry in enumerate(entries, 1):
            # Extract paper details
            title = entry.find('atom:title', ns)
            title_text = title.text.strip().replace('\n', ' ') if title is not None else "No title"

            summary = entry.find('atom:summary', ns)
            summary_text = summary.text.strip().replace('\n', ' ')[:500] if summary is not None else ""

            # Get arXiv ID and construct URL
            arxiv_id = entry.find('atom:id', ns)
            paper_url = arxiv_id.text if arxiv_id is not None else ""

            # Get authors
            authors = entry.findall('atom:author/atom:name', ns)
            author_list = [author.text for author in authors]
            authors_str = ", ".join(author_list[:3])  # First 3 authors
            if len(author_list) > 3:
                authors_str += f" et al. ({len(author_list)} total)"

            # Get publication date
            published = entry.find('atom:published', ns)
            pub_date = published.text[:10] if published is not None else "Unknown"

            # Get categories
            categories = entry.findall('atom:category', ns)
            category_list = [cat.get('term') for cat in categories[:2]]  # First 2 categories

            output.append({
                f"paper_{idx}": {
                    "title": title_text,
                    "authors": authors_str,
                    "abstract": summary_text + "..." if len(summary_text) == 500 else summary_text,
                    "url": paper_url,
                    "published": pub_date,
                    "categories": category_list
                }
            })

        print(f"[arxiv_search] ✓ Found {len(entries)} papers", file=sys.stderr)
        return output

    except asyncio.TimeoutError:
        output.append({"success": False})
        output.append({"error": "arXiv search timeout"})
        return output
    except Exception as e:
        output.append({"success": False})
        output.append({"error": f"arXiv search error: {e}"})
        return output


# ============================================================================
# PUBMED SEARCH TOOL
# ============================================================================
@server.register_tool
async def pubmed_search(
    query: str,
    max_results: int = 5):
    """
    Search PubMed for biomedical and life sciences literature.
    Use this when Victor asks about medical research, biology, health sciences, or clinical studies.

    Args:
        query: Search query (keywords, diseases, treatments, authors, etc.)
        max_results: Maximum number of results to return (default: 5, max: 20)

    Returns:
        List of articles with titles, authors, abstracts, and PubMed links

    Example:
        pubmed_search(query="CRISPR gene editing")
    """
    output = []

    if not query:
        output.append({"success": False})
        output.append({"error": "No search query provided"})
        return output

    try:
        # Limit max_results
        max_results = min(max_results, 20)

        print(f"[pubmed_search] Searching PubMed for: {query}", file=sys.stderr)

        # Step 1: Search for PMIDs using esearch
        esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        search_params = {
            'db': 'pubmed',
            'term': query,
            'retmax': max_results,
            'retmode': 'json',
            'sort': 'relevance'
        }

        async with aiohttp.ClientSession() as session:
            # Get PMIDs
            async with session.get(esearch_url, params=search_params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    output.append({"success": False})
                    output.append({"error": f"PubMed search API returned status {response.status}"})
                    return output

                search_data = await response.json()

            # Extract PMIDs
            pmid_list = search_data.get('esearchresult', {}).get('idlist', [])

            if not pmid_list:
                output.append({"success": True})
                output.append({"message": f"No articles found for query: {query}"})
                return output

            # Step 2: Fetch article details using efetch
            efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            fetch_params = {
                'db': 'pubmed',
                'id': ','.join(pmid_list),
                'retmode': 'xml'
            }

            async with session.get(efetch_url, params=fetch_params, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    output.append({"success": False})
                    output.append({"error": f"PubMed fetch API returned status {response.status}"})
                    return output

                xml_data = await response.text()

        # Parse XML response
        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml_data)

        articles = root.findall('.//PubmedArticle')

        output.append({"success": True})
        output.append({"count": len(articles)})

        for idx, article in enumerate(articles, 1):
            # Extract article details
            pmid_elem = article.find('.//PMID')
            pmid = pmid_elem.text if pmid_elem is not None else "Unknown"

            title_elem = article.find('.//ArticleTitle')
            title = title_elem.text if title_elem is not None else "No title"

            # Get abstract
            abstract_texts = article.findall('.//AbstractText')
            abstract = " ".join([ab.text for ab in abstract_texts if ab.text])[:500] if abstract_texts else "No abstract available"

            # Get authors
            authors = article.findall('.//Author')
            author_list = []
            for author in authors[:3]:  # First 3 authors
                last_name = author.find('.//LastName')
                initials = author.find('.//Initials')
                if last_name is not None:
                    name = last_name.text
                    if initials is not None:
                        name += f" {initials.text}"
                    author_list.append(name)

            authors_str = ", ".join(author_list)
            if len(authors) > 3:
                authors_str += f" et al. ({len(authors)} total)"

            # Get publication date
            pub_date_elem = article.find('.//PubDate')
            year = pub_date_elem.find('.//Year') if pub_date_elem is not None else None
            month = pub_date_elem.find('.//Month') if pub_date_elem is not None else None
            pub_date = f"{year.text if year is not None else 'Unknown'}"
            if month is not None:
                pub_date = f"{month.text} {pub_date}"

            # Get journal
            journal_elem = article.find('.//Journal/Title')
            journal = journal_elem.text if journal_elem is not None else "Unknown"

            # Construct PubMed URL
            pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

            output.append({
                f"article_{idx}": {
                    "title": title,
                    "authors": authors_str,
                    "abstract": abstract + "..." if len(abstract) == 500 else abstract,
                    "journal": journal,
                    "published": pub_date,
                    "pmid": pmid,
                    "url": pubmed_url
                }
            })

        print(f"[pubmed_search] ✓ Found {len(articles)} articles", file=sys.stderr)
        return output

    except asyncio.TimeoutError:
        output.append({"success": False})
        output.append({"error": "PubMed search timeout"})
        return output
    except Exception as e:
        output.append({"success": False})
        output.append({"error": f"PubMed search error: {e}"})
        return output


# ============================================================================
# WEATHER TOOL
# ============================================================================

@server.register_tool
def weather_get(
    location: str,
    units: str = "imperial"
) -> Dict[str, Any]:
    """
    Get current weather information for a location.
    
    Uses wttr.in (free weather service, no API key needed).
    
    Args:
        location: City name, ZIP code, or coordinates 
                 Examples: "Seattle", "90210", "47.6,-122.3"
        units: Temperature units - "metric" (Celsius) or "imperial" (Fahrenheit)
    
    Returns:
        dict: Weather information including:
            - success: bool
            - location: str
            - temperature: float (in requested units)
            - temperature_c: float
            - temperature_f: float
            - condition: str (e.g., "Clear", "Cloudy")
            - humidity: str
            - feels_like_c: float
            - feels_like_f: float
            - wind_speed_kmph: str
            - wind_speed_mph: str
            - wind_direction: str
            - precipitation_mm: str
            - visibility_km: str
            - pressure_mb: str
            - cloud_cover: str
            - error: str (only if success=False)
    
    Example:
        >>> result = weather_get("Seattle", units="imperial")
        >>> print(f"Temperature: {result['temperature']}°F")
        >>> print(f"Condition: {result['condition']}")
    """
    try:
        # Use wttr.in - free weather service
        format_str = "j1"  # JSON format
        url = f"https://wttr.in/{location}?format={format_str}"
        
        print(f"[weather_get] Fetching weather for: {location}", file=sys.stderr)
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        current = data.get("current_condition", [{}])[0]
        area = data.get("nearest_area", [{}])[0]
        
        # Extract temperature data
        temp_c = float(current.get("temp_C", 0))
        temp_f = float(current.get("temp_F", 0))
        
        result = {
            "success": True,
            "location": location,
            "temperature_c": temp_c,
            "temperature_f": temp_f,
            "temperature": temp_c if units == "metric" else temp_f,
            "units": units,
            "nearest": area.get("areaName", [{}])[0].get("value", "Unknown"),
            "condition": current.get("weatherDesc", [{}])[0].get("value", "Unknown"),
            "humidity": current.get("humidity", "Unknown"),
            "feels_like_c": float(current.get("FeelsLikeC", 0)),
            "feels_like_f": float(current.get("FeelsLikeF", 0)),
            "wind_speed_kmph": current.get("windspeedKmph", "Unknown"),
            "wind_speed_mph": current.get("windspeedMiles", "Unknown"),
            "wind_direction": current.get("winddir16Point", "Unknown"),
            "precipitation_mm": current.get("precipMM", "Unknown"),
            "visibility_km": current.get("visibility", "Unknown"),
            "pressure_mb": current.get("pressure", "Unknown"),
            "cloud_cover": current.get("cloudcover", "Unknown"),
        }
        
        print(f"[weather_get] Success: {result['temperature']}° {result['condition']}", file=sys.stderr)
        return result
        
    except requests.RequestException as e:
        error_msg = f"Failed to fetch weather: {str(e)}"
        print(f"[weather_get] Error: {error_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": error_msg
        }
    except Exception as e:
        error_msg = str(e)
        print(f"[weather_get] Error: {error_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": error_msg
        }


@server.register_tool
def forecast_get(
    location: str
) -> Dict[str, Any]:
    """
    Get weekly weather forecast for a location.

    Uses wttr.in (free weather service, no API key needed).

    Args:
        location: City name, ZIP code, or coordinates
                 Examples: "Seattle", "90210", "47.6,-122.3"

    Returns:
        dict: Forecast information including:
            - success: bool
            - location: str
            - forecast: list of daily forecasts with:
                - date: str
                - high_f: float
                - low_f: float
                - high_c: float
                - low_c: float
                - condition: str
                - description: str (conversational summary)
            - error: str (only if success=False)

    Example:
        >>> result = forecast_get("Seattle")
        >>> for day in result['forecast']:
        ...     print(f"{day['date']}: {day['description']}")
    """
    try:
        # Use wttr.in - free weather service
        format_str = "j1"  # JSON format
        url = f"https://wttr.in/{location}?format={format_str}"

        print(f"[forecast_get] Fetching forecast for: {location}", file=sys.stderr)

        response = requests.get(url, timeout=10)
        response.raise_for_status()

        data = response.json()
        weather_days = data.get("weather", [])
        area = data.get("nearest_area", [{}])[0]
        area_name = area.get("areaName", [{}])[0].get("value", location)

        forecast = []
        for day in weather_days:
            date = day.get("date", "Unknown")
            high_c = float(day.get("maxtempC", 0))
            low_c = float(day.get("mintempC", 0))
            high_f = float(day.get("maxtempF", 0))
            low_f = float(day.get("mintempF", 0))

            # Get hourly data for condition (use noon as representative)
            hourly = day.get("hourly", [])
            noon_hour = hourly[4] if len(hourly) > 4 else (hourly[0] if hourly else {})
            condition = noon_hour.get("weatherDesc", [{}])[0].get("value", "Unknown")
            chance_of_rain = noon_hour.get("chanceofrain", "0")

            # Create conversational description
            description = f"{condition}, high of {int(high_f)}°F and low of {int(low_f)}°F"
            if int(chance_of_rain) > 30:
                description += f" with {chance_of_rain}% chance of rain"

            forecast.append({
                "date": date,
                "high_f": high_f,
                "low_f": low_f,
                "high_c": high_c,
                "low_c": low_c,
                "condition": condition,
                "chance_of_rain": f"{chance_of_rain}%",
                "description": description
            })

        result = {
            "success": True,
            "location": area_name,
            "forecast": forecast
        }

        print(f"[forecast_get] Success: {len(forecast)} days of forecast for {area_name}", file=sys.stderr)
        return result

    except requests.RequestException as e:
        error_msg = f"Failed to fetch forecast: {str(e)}"
        print(f"[forecast_get] Error: {error_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": error_msg
        }
    except Exception as e:
        error_msg = str(e)
        print(f"[forecast_get] Error: {error_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": error_msg
        }


# ============================================================================
# FACE RECOGNITION TOOLS
# ============================================================================

@server.register_tool
async def face_database_status():
    """
    Get status and statistics about the face recognition database.
    Shows how many people Iris knows, training images, and recent recognition activity.

    Returns:
        Dictionary with statistics including:
        - persons_count: Number of known persons
        - embeddings_count: Total training images
        - recognitions_24h: Recognitions in last 24 hours
        - recognitions_7d: Recognitions in last 7 days
        - currently_present: People currently detected

    Example:
        face_database_status() -> Get overview of face recognition system
    """
    try:
        # Import here to avoid circular dependencies
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))

        from core import face_recognition as fr

        print(f"[face_database_status] Getting face database statistics...", file=sys.stderr)

        # Get statistics
        stats = fr.get_statistics()

        # Get list of known persons
        persons = fr.list_persons(enabled_only=True)

        result = {
            "success": True,
            "statistics": {
                "known_persons": stats.get('persons_count', 0),
                "training_images": stats.get('embeddings_count', 0),
                "recognitions_last_24h": stats.get('recognitions_24h', 0),
                "recognitions_last_7d": stats.get('recognitions_7d', 0),
                "currently_present": stats.get('currently_present', 0),
                "active_cameras": stats.get('cameras_count', 0)
            },
            "known_persons": [
                {
                    "name": p['name'],
                    "relationship": p.get('relationship', 'unknown'),
                    "training_images": p.get('training_image_count', 0),
                    "recognition_count": p.get('recognition_count', 0),
                    "last_seen": str(p['last_seen']) if p.get('last_seen') else 'never'
                }
                for p in persons
            ]
        }

        print(f"[face_database_status] ✓ Found {result['statistics']['known_persons']} persons", file=sys.stderr)
        return result

    except Exception as e:
        error_msg = f"Failed to get face database status: {str(e)}"
        print(f"[face_database_status] ✗ Error: {error_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": error_msg
        }


@server.register_tool
async def list_detected_faces():
    """
    Query presence state from background monitoring system.

    IMPORTANT: This only shows people detected by the BACKGROUND monitoring service.
    It does NOT capture from webcam. Use webcam_recognize() to actively look at the camera.

    Returns:
        List of people marked as "present" by background monitoring:
        - name: Person's name
        - location: Camera location
        - entered_at: When they were first detected
        - last_seen: Most recent detection
        - duration: How long they've been present

    Example:
        list_detected_faces() -> Query background monitoring presence state (not live capture)
    """
    try:
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))

        from core import face_recognition as fr
        import psycopg2.extras

        print(f"[list_detected_faces] Getting current presence...", file=sys.stderr)

        conn = fr.get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT * FROM face_presence_current
            ORDER BY entered_at DESC
        """)

        presence = cursor.fetchall()
        cursor.close()
        conn.close()

        if not presence:
            result = {
                "success": True,
                "count": 0,
                "message": "No one is currently detected",
                "present": []
            }
        else:
            result = {
                "success": True,
                "count": len(presence),
                "present": [
                    {
                        "name": p['name'],
                        "display_name": p.get('display_name'),
                        "camera": p['camera_name'],
                        "location": p.get('location', 'unknown'),
                        "entered_at": str(p['entered_at']),
                        "last_seen": str(p['last_seen_at']),
                        "seconds_present": p['seconds_present']
                    }
                    for p in presence
                ]
            }

        print(f"[list_detected_faces] ✓ Found {result['count']} people present", file=sys.stderr)
        return result

    except Exception as e:
        error_msg = f"Failed to list detected faces: {str(e)}"
        print(f"[list_detected_faces] ✗ Error: {error_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": error_msg
        }


@server.register_tool
async def get_person_info(name: str):
    """
    Get detailed information about a specific person in the face database.

    Args:
        name: Person's name (e.g., "Victor", "Luna")

    Returns:
        Detailed information including:
        - Basic info (name, relationship, notes)
        - Training statistics
        - Recognition history
        - Last seen information

    Example:
        get_person_info(name="Victor") -> Get detailed info about Victor
    """
    try:
        import sys
        from pathlib import Path
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))

        from core import face_recognition as fr

        print(f"[get_person_info] Getting info for: {name}", file=sys.stderr)

        # Get person by name
        person = fr.get_person_by_name(name)

        if not person:
            return {
                "success": False,
                "error": f"Person '{name}' not found in database"
            }

        result = {
            "success": True,
            "person": {
                "name": person['name'],
                "display_name": person.get('display_name'),
                "relationship": person.get('relationship', 'unknown'),
                "notes": person.get('notes'),
                "tags": person.get('tags', []),
                "training_images": person.get('training_image_count', 0),
                "total_recognitions": person.get('recognition_count', 0),
                "first_seen": str(person['first_seen']) if person.get('first_seen') else None,
                "last_seen": str(person['last_seen']) if person.get('last_seen') else None,
                "enabled": person.get('enabled', True)
            }
        }

        print(f"[get_person_info] ✓ Found {name}: {result['person']['training_images']} training images", file=sys.stderr)
        return result

    except Exception as e:
        error_msg = f"Failed to get person info: {str(e)}"
        print(f"[get_person_info] ✗ Error: {error_msg}", file=sys.stderr)
        return {
            "success": False,
            "error": error_msg
        }


@server.register_tool
def webcam_recognize(camera_id: int = 0, similarity_threshold: float = None,
                     describe_scene: bool = True, vision_prompt: str = None):
    """
    Look at the webcam to see WHO is there and WHAT you can see.

    This tool does TWO things:
    1. Face Recognition - Identifies specific people (Victor, etc.) using trained face embeddings
    2. Vision Analysis - Describes the full scene, objects, actions using AI vision

    USE THIS TOOL when asked:
    - "Who's there?" / "Do you see anyone?" (face recognition)
    - "What do you see?" / "What am I holding?" (vision analysis)
    - "Look at the camera" / "Look at this" (both)

    IMPORTANT:
    - User must enable the webcam toggle (📷) in the chat interface first
    - Respond naturally! Combine face recognition with scene description conversationally
    - Example: "I see Victor, and it looks like you're holding a coffee mug"

    Args:
        camera_id: Ignored (kept for compatibility)
        similarity_threshold: Minimum similarity for face recognition (default: 0.5)
        describe_scene: Whether to also describe the scene with vision AI (default: True)
        vision_prompt: Optional specific question for vision AI (e.g., "What color is that object?")

    Returns:
        people_present: List of names of recognized people
        unknown_faces: Count of unrecognized faces
        scene_description: What the vision AI sees (objects, actions, etc.)
    """
    try:
        import sys
        import os
        import base64
        from pathlib import Path
        from datetime import datetime, timedelta

        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root))

        from core import face_recognition as fr

        print(f"[webcam_recognize] Reading cached webcam frame from disk...", file=sys.stderr)

        # Read latest frame from disk
        WEBCAM_CACHE_DIR = "/tmp/iris_webcam_cache"
        latest_frame_path = os.path.join(WEBCAM_CACHE_DIR, "frame_latest.jpg")

        # Check if frame exists
        if not os.path.exists(latest_frame_path):
            return {
                "success": False,
                "error": "Webcam not enabled. Please click the 📷 Webcam toggle in the chat interface to enable webcam streaming."
            }

        # Check if frame is stale (older than 10 seconds)
        file_mtime = datetime.fromtimestamp(os.path.getmtime(latest_frame_path))
        age = datetime.now() - file_mtime
        if age > timedelta(seconds=10):
            return {
                "success": False,
                "error": f"Webcam frame is stale ({age.total_seconds():.1f} seconds old). The webcam may have been disabled."
            }

        print(f"[webcam_recognize] Loading image from {latest_frame_path}...", file=sys.stderr)

        # Load image from disk for face recognition
        try:
            img = fr.load_image_from_path(latest_frame_path)
            if img is None:
                return {
                    "success": False,
                    "error": "Failed to decode webcam frame"
                }
            print(f"[webcam_recognize] ✓ Image loaded: {img.shape}", file=sys.stderr)
        except Exception as load_err:
            print(f"[webcam_recognize] ✗ Error loading image: {load_err}", file=sys.stderr)
            return {
                "success": False,
                "error": f"Failed to load image: {str(load_err)}"
            }

        # ============================================================
        # PART 1: Face Recognition (WHO is there)
        # ============================================================
        print(f"[webcam_recognize] Running face recognition...", file=sys.stderr)

        recognized_names = []
        recognized_details = []
        unknown_count = 0
        faces_detected = 0

        try:
            results = fr.recognize_face(img, similarity_threshold=similarity_threshold)
            faces_detected = len(results) if results else 0
            print(f"[webcam_recognize] ✓ Face recognition complete: {faces_detected} faces", file=sys.stderr)

            for face_result in results:
                if face_result.get('best_match'):
                    match = face_result['best_match']
                    name = match['name']
                    recognized_names.append(name)
                    recognized_details.append({
                        "name": name,
                        "relationship": match.get('relationship', 'unknown'),
                        "confidence": round(match['avg_similarity'] * 100, 1),
                        "training_images": match.get('training_image_count', 0)
                    })
                else:
                    unknown_count += 1

        except Exception as recog_err:
            print(f"[webcam_recognize] ⚠️ Face recognition error (continuing with vision): {recog_err}", file=sys.stderr)

        if recognized_names:
            print(f"[webcam_recognize] ✓ Recognized: {', '.join(recognized_names)}", file=sys.stderr)
        elif faces_detected > 0:
            print(f"[webcam_recognize] ⚠️ Detected {faces_detected} face(s) but none recognized", file=sys.stderr)

        # ============================================================
        # PART 2: Vision Analysis (WHAT do you see)
        # ============================================================
        scene_description = None

        if describe_scene:
            print(f"[webcam_recognize] Running vision analysis...", file=sys.stderr)

            try:
                # Read image as base64 for vision service
                with open(latest_frame_path, 'rb') as f:
                    image_bytes = f.read()
                image_base64 = base64.b64encode(image_bytes).decode('utf-8')

                from inference.vision_service import get_vision_service
                service = get_vision_service()

                # Ensure server is available
                if not service.is_loaded():
                    service.load_model()

                if service.is_loaded():
                    # Build prompt - include who we recognized for context
                    if vision_prompt:
                        prompt = vision_prompt
                    elif recognized_names:
                        prompt = f"Describe what you see in this image. I already know {', '.join(recognized_names)} is visible. Focus on what they're doing, objects they're holding or interacting with, and anything else notable in the scene."
                    else:
                        prompt = "Describe what you see in this image. Focus on people, what they're doing, objects they're holding, and anything notable or interesting."

                    vision_result = service.analyze_image(image_base64, prompt)

                    if vision_result['success']:
                        scene_description = vision_result['result']
                        print(f"[webcam_recognize] ✓ Vision analysis complete ({vision_result.get('inference_time', 0):.2f}s)", file=sys.stderr)
                    else:
                        print(f"[webcam_recognize] ⚠️ Vision analysis failed: {vision_result.get('error')}", file=sys.stderr)
                else:
                    print(f"[webcam_recognize] ⚠️ Vision server not available, skipping scene description", file=sys.stderr)

            except Exception as vision_err:
                print(f"[webcam_recognize] ⚠️ Vision analysis error: {vision_err}", file=sys.stderr)

        # ============================================================
        # Combined Results
        # ============================================================
        result = {
            "success": True,
            "people_present": recognized_names,
            "unknown_faces": unknown_count,
            "faces_detected": faces_detected,
            "scene_description": scene_description,
            "_technical_details": recognized_details,
            "_note": "Respond naturally and conversationally. Combine who you see with what's happening. Example: 'I see Victor - looks like you're holding a coffee mug and sitting at your desk.'"
        }

        return result

    except Exception as e:
        error_msg = f"Failed to analyze webcam: {str(e)}"
        print(f"[webcam_recognize] ✗ Error: {error_msg}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": error_msg
        }


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("="*60, file=sys.stderr)
    print("IRIS INFO SERVER", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print(f"Tools available:", file=sys.stderr)
    print(f"  - weather_get: Get current weather for a location", file=sys.stderr)
    print(f"  - web_search: Search the web with keywords", file=sys.stderr)
    print(f"  - url_fetch: Fetch content from a specific URL", file=sys.stderr)
    print(f"  - arxiv_search: Search arXiv for academic papers", file=sys.stderr)
    print(f"  - pubmed_search: Search PubMed for biomedical literature", file=sys.stderr)
    print(f"  - face_database_status: Get face recognition statistics", file=sys.stderr)
    print(f"  - list_detected_faces: List currently detected people", file=sys.stderr)
    print(f"  - get_person_info: Get detailed info about a person", file=sys.stderr)
    print(f"  - webcam_recognize: Look at webcam (face recognition + vision AI scene description)", file=sys.stderr)
    print(f"Starting server...", file=sys.stderr)
    print("="*60, file=sys.stderr)
    server.run()

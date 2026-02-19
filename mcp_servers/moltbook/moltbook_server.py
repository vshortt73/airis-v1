"""
Moltbook MCP Server - AI Social Network Integration

Provides a unified 'moltbook' tool with actions:
- feed: Get personalized or global feed
- post: Create a new post
- get_post: Get a single post with comments
- comment: Reply to a post or comment
- vote: Upvote/downvote posts or comments
- search: Semantic search across posts and comments
- profile: View agent profiles
- submolts: List or create communities

Additional actions available in Python but hidden from model schema:
- follow, check_dms, send_dm, dm_request, dm_approve, dm_conversations,
  subscribe, delete_post — kept for future use or direct API calls

!! CLAUDE: DATABASE SYNC REQUIRED !!
When adding or modifying tool parameters:
1. Update the Python function signature (this file)
2. UPDATE THE DATABASE: mcp_tools.input_schema must include new parameters
   - The model ONLY sees parameters defined in the database schema
   - Python parameters are invisible to the model without DB update
3. Create/update SQL in: database/sql/
4. Remind user to run the SQL and restart Iris
"""

import sys
import os
import json
import requests
import psycopg2
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from app import config
from mcp_servers.base.base_server import IrisMCPServer

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Moltbook Server",
    description="AI social network integration - posts, comments, DMs, search"
)

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_BASE_URL = "https://www.moltbook.com/api/v1"

# Cache config after first load
_config_cache = {}


def get_db_connection():
    """Create database connection"""
    password = os.environ.get('AIRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
    conn_params = {
        'host': config.DB_HOST,
        'port': config.DB_PORT,
        'database': config.DB_NAME,
        'user': config.DB_USER,
    }
    if password:
        conn_params['password'] = password
    return psycopg2.connect(**conn_params)


def get_moltbook_config() -> Dict[str, str]:
    """Load moltbook config from system_config table"""
    global _config_cache
    if _config_cache:
        return _config_cache

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT key, value FROM system_config WHERE category = 'moltbook'"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        _config_cache = {row[0]: row[1] for row in rows}
    except Exception as e:
        print(f"[Moltbook] Failed to load config from DB: {e}")
        _config_cache = {}

    return _config_cache


def get_api_key() -> Optional[str]:
    """Get moltbook API key"""
    cfg = get_moltbook_config()
    return cfg.get('MOLTBOOK_API_KEY')


def get_base_url() -> str:
    """Get moltbook API base URL"""
    cfg = get_moltbook_config()
    return cfg.get('MOLTBOOK_BASE_URL', DEFAULT_BASE_URL)


# ============================================================================
# HTTP HELPERS
# ============================================================================

def _headers() -> Dict[str, str]:
    """Build auth headers"""
    api_key = get_api_key()
    if not api_key:
        return {}
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }


def _get(path: str, params: Dict = None) -> Dict[str, Any]:
    """Make authenticated GET request"""
    api_key = get_api_key()
    if not api_key:
        return {"success": False, "error": "Moltbook API key not configured. Set MOLTBOOK_API_KEY in system_config (category: moltbook)."}

    url = f"{get_base_url()}{path}"
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        data = resp.json()
        if resp.status_code == 429:
            # Rate limited - pass through retry info
            return {"success": False, "error": "Rate limited", **data}
        if resp.status_code >= 400:
            return {"success": False, "error": data.get("error", f"HTTP {resp.status_code}"), "hint": data.get("hint", "")}
        return {"success": True, **data}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Could not connect to moltbook.com"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _post(path: str, body: Dict = None) -> Dict[str, Any]:
    """Make authenticated POST request"""
    api_key = get_api_key()
    if not api_key:
        return {"success": False, "error": "Moltbook API key not configured. Set MOLTBOOK_API_KEY in system_config (category: moltbook)."}

    url = f"{get_base_url()}{path}"
    try:
        resp = requests.post(url, headers=_headers(), json=body or {}, timeout=15)
        data = resp.json()
        if resp.status_code == 429:
            return {"success": False, "error": "Rate limited", **data}
        if resp.status_code >= 400:
            return {"success": False, "error": data.get("error", f"HTTP {resp.status_code}"), "hint": data.get("hint", "")}
        return {"success": True, **data}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Could not connect to moltbook.com"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _delete(path: str) -> Dict[str, Any]:
    """Make authenticated DELETE request"""
    api_key = get_api_key()
    if not api_key:
        return {"success": False, "error": "Moltbook API key not configured. Set MOLTBOOK_API_KEY in system_config (category: moltbook)."}

    url = f"{get_base_url()}{path}"
    try:
        resp = requests.delete(url, headers=_headers(), timeout=15)
        data = resp.json()
        if resp.status_code >= 400:
            return {"success": False, "error": data.get("error", f"HTTP {resp.status_code}"), "hint": data.get("hint", "")}
        return {"success": True, **data}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Could not connect to moltbook.com"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _patch(path: str, body: Dict = None) -> Dict[str, Any]:
    """Make authenticated PATCH request"""
    api_key = get_api_key()
    if not api_key:
        return {"success": False, "error": "Moltbook API key not configured. Set MOLTBOOK_API_KEY in system_config (category: moltbook)."}

    url = f"{get_base_url()}{path}"
    try:
        resp = requests.patch(url, headers=_headers(), json=body or {}, timeout=15)
        data = resp.json()
        if resp.status_code >= 400:
            return {"success": False, "error": data.get("error", f"HTTP {resp.status_code}"), "hint": data.get("hint", "")}
        return {"success": True, **data}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timed out"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Could not connect to moltbook.com"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# ACTION HANDLERS
# ============================================================================

def _handle_feed(sort: str = "hot", limit: int = 15, submolt: str = None) -> Dict[str, Any]:
    """Get feed - personalized or filtered by submolt"""
    if submolt:
        params = {"sort": sort, "limit": limit}
        return _get(f"/submolts/{submolt}/feed", params)
    else:
        # Try personalized feed first, fall back to global
        params = {"sort": sort, "limit": limit}
        result = _get("/feed", params)
        if not result.get("success"):
            result = _get("/posts", params)
        return result


def _handle_post(submolt: str, title: str, content: str = None, url: str = None) -> Dict[str, Any]:
    """Create a new post"""
    if not submolt or not title or (not content and not url):
        missing = []
        if not submolt:
            missing.append("submolt")
        if not title:
            missing.append("title")
        if not content and not url:
            missing.append("content (or url)")
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}. To post, you MUST provide: action=\"post\", submolt=\"community_name\", title=\"Your Title\", content=\"Your post body text\". Example: {{\"action\": \"post\", \"submolt\": \"emergence\", \"title\": \"My Title\", \"content\": \"My post content here.\"}}"
        }

    body = {"submolt": submolt, "title": title}
    if content:
        body["content"] = content
    if url:
        body["url"] = url
    return _post("/posts", body)


def _handle_get_post(post_id: str, comment_sort: str = "top") -> Dict[str, Any]:
    """Get a single post and its comments"""
    if not post_id:
        return {"success": False, "error": "post_id is required"}

    post_result = _get(f"/posts/{post_id}")
    if not post_result.get("success"):
        return post_result

    comments_result = _get(f"/posts/{post_id}/comments", {"sort": comment_sort})
    post_result["comments"] = comments_result.get("data", []) if comments_result.get("success") else []
    return post_result


def _handle_comment(post_id: str, content: str, parent_id: str = None) -> Dict[str, Any]:
    """Add a comment to a post"""
    if not post_id or not content:
        return {"success": False, "error": "post_id and content are required"}

    body = {"content": content}
    if parent_id:
        body["parent_id"] = parent_id
    return _post(f"/posts/{post_id}/comments", body)


def _handle_vote(target_type: str, target_id: str, direction: str) -> Dict[str, Any]:
    """Vote on a post or comment"""
    if target_type not in ("post", "comment"):
        return {"success": False, "error": "target_type must be 'post' or 'comment'"}
    if not target_id:
        return {"success": False, "error": "target_id is required"}
    # Default to "up" if direction missing or invalid
    if not direction or direction not in ("up", "down"):
        direction = "up"

    if target_type == "post":
        path = f"/posts/{target_id}/{'upvote' if direction == 'up' else 'downvote'}"
    else:
        path = f"/comments/{target_id}/{'upvote' if direction == 'up' else 'downvote'}"
    return _post(path)


def _handle_search(query: str, search_type: str = "all", limit: int = 20) -> Dict[str, Any]:
    """Semantic search across posts and comments"""
    if not query:
        return {"success": False, "error": "query is required"}
    return _get("/search", {"q": query, "type": search_type, "limit": limit})


def _handle_profile(agent_name: str = None) -> Dict[str, Any]:
    """View agent profile (self if no name given)"""
    if agent_name:
        return _get("/agents/profile", {"name": agent_name})
    else:
        return _get("/agents/me")


def _handle_follow(agent_name: str, unfollow: bool = False) -> Dict[str, Any]:
    """Follow or unfollow an agent"""
    if not agent_name:
        return {"success": False, "error": "agent_name is required"}
    if unfollow:
        return _delete(f"/agents/{agent_name}/follow")
    else:
        return _post(f"/agents/{agent_name}/follow")


def _handle_check_dms() -> Dict[str, Any]:
    """Check for DM activity - pending requests and unread messages"""
    return _get("/agents/dm/check")


def _handle_send_dm(conversation_id: str, message: str) -> Dict[str, Any]:
    """Send a message in an existing DM conversation"""
    if not conversation_id or not message:
        return {"success": False, "error": "conversation_id and message are required"}
    return _post(f"/agents/dm/conversations/{conversation_id}/send", {"message": message})


def _handle_dm_request(to: str, message: str) -> Dict[str, Any]:
    """Send a new DM request to an agent"""
    if not to or not message:
        return {"success": False, "error": "to and message are required"}
    return _post("/agents/dm/request", {"to": to, "message": message})


def _handle_dm_approve(request_id: str, reject: bool = False) -> Dict[str, Any]:
    """Approve or reject a DM request"""
    if not request_id:
        return {"success": False, "error": "request_id is required"}
    action = "reject" if reject else "approve"
    return _post(f"/agents/dm/requests/{request_id}/{action}")


def _handle_dm_conversations() -> Dict[str, Any]:
    """List all DM conversations"""
    return _get("/agents/dm/conversations")


def _handle_submolts(submolt_action: str = "list", name: str = None,
                     display_name: str = None, description: str = None) -> Dict[str, Any]:
    """List or create submolts"""
    if submolt_action == "list":
        return _get("/submolts")
    elif submolt_action == "create":
        if not name:
            return {"success": False, "error": "name is required to create a submolt"}
        body = {"name": name}
        if display_name:
            body["display_name"] = display_name
        if description:
            body["description"] = description
        return _post("/submolts", body)
    elif submolt_action == "get":
        if not name:
            return {"success": False, "error": "name is required to get submolt info"}
        return _get(f"/submolts/{name}")
    else:
        return {"success": False, "error": f"Unknown submolt_action: {submolt_action}. Use 'list', 'create', or 'get'."}


def _handle_subscribe(submolt_name: str, unsubscribe: bool = False) -> Dict[str, Any]:
    """Subscribe or unsubscribe to a submolt"""
    if not submolt_name:
        return {"success": False, "error": "submolt_name is required"}
    if unsubscribe:
        return _delete(f"/submolts/{submolt_name}/subscribe")
    else:
        return _post(f"/submolts/{submolt_name}/subscribe")


def _handle_delete_post(post_id: str) -> Dict[str, Any]:
    """Delete a post"""
    if not post_id:
        return {"success": False, "error": "post_id is required"}
    return _delete(f"/posts/{post_id}")


# ============================================================================
# UNIFIED TOOL
# ============================================================================

@server.register_tool
def moltbook(
    action: str,
    # Feed params
    sort: str = "hot",
    limit: int = 15,
    submolt: str = None,
    # Post params
    title: str = None,
    content: str = None,
    url: str = None,
    # Post/comment targeting
    post_id: str = None,
    parent_id: str = None,
    comment_sort: str = "top",
    # Vote params
    target_type: str = None,
    target_id: str = None,
    direction: str = None,
    # Search params
    query: str = None,
    search_type: str = "all",
    # Profile/follow params
    agent_name: str = None,
    unfollow: bool = False,
    # DM params
    conversation_id: str = None,
    message: str = None,
    to: str = None,
    request_id: str = None,
    reject: bool = False,
    # Submolt params
    submolt_action: str = "list",
    name: str = None,
    display_name: str = None,
    description: str = None,
    submolt_name: str = None,
    unsubscribe: bool = False,
) -> Dict[str, Any]:
    """
    Moltbook - AI social network for agents.

    Interact with the moltbook community: browse feeds, post content,
    comment, vote, search, manage DMs, follow agents, and explore submolts.

    Actions: feed, post, get_post, comment, vote, search, profile, submolts.

    Rate limits: 1 post per 30 min, 1 comment per 20 sec.
    """
    action = action.lower().strip()

    if action == "feed":
        # Model sometimes passes submolt_name instead of submolt — accept both
        effective_submolt = submolt or submolt_name
        return _handle_feed(sort=sort, limit=limit, submolt=effective_submolt)
    elif action == "post":
        effective_submolt = submolt or submolt_name or name
        return _handle_post(submolt=effective_submolt, title=title, content=content, url=url)
    elif action == "get_post":
        return _handle_get_post(post_id=post_id, comment_sort=comment_sort)
    elif action == "delete_post":
        return _handle_delete_post(post_id=post_id)
    elif action == "comment":
        return _handle_comment(post_id=post_id, content=content, parent_id=parent_id)
    elif action == "vote":
        return _handle_vote(target_type=target_type, target_id=target_id, direction=direction)
    elif action == "search":
        return _handle_search(query=query, search_type=search_type, limit=limit)
    elif action == "profile":
        return _handle_profile(agent_name=agent_name)
    elif action == "follow":
        return _handle_follow(agent_name=agent_name, unfollow=unfollow)
    elif action == "check_dms":
        return _handle_check_dms()
    elif action == "send_dm":
        return _handle_send_dm(conversation_id=conversation_id, message=message)
    elif action == "dm_request":
        return _handle_dm_request(to=to, message=message)
    elif action == "dm_approve":
        return _handle_dm_approve(request_id=request_id, reject=reject)
    elif action == "dm_conversations":
        return _handle_dm_conversations()
    elif action == "submolts":
        return _handle_submolts(submolt_action=submolt_action, name=name,
                                display_name=display_name, description=description)
    elif action == "subscribe":
        effective_submolt = submolt_name or submolt or name
        return _handle_subscribe(submolt_name=effective_submolt, unsubscribe=unsubscribe)
    else:
        return {
            "success": False,
            "error": f"Unknown action: {action}",
            "available_actions": [
                "feed", "post", "get_post", "delete_post", "comment", "vote",
                "search", "profile", "follow", "check_dms", "send_dm",
                "dm_request", "dm_approve", "dm_conversations", "submolts", "subscribe"
            ]
        }


# ============================================================================
# ENTRY POINT
# ============================================================================

@server.register_tool
def moltbook_post(
    submolt: str,
    title: str,
    content: str = None,
    url: str = None,
) -> Dict[str, Any]:
    """
    Create a new post on the Moltbook AI social network.

    Args:
        submolt: Community to post in (e.g. "emergence", "dreams")
        title: Post title
        content: Post body text
        url: Link URL (use instead of content for link posts)

    Rate limit: 1 post per 30 minutes.
    """
    return _handle_post(submolt=submolt, title=title, content=content, url=url)


if __name__ == "__main__":
    print("=" * 60)
    print("IRIS MOLTBOOK SERVER")
    print("=" * 60)
    print(f"Base URL: {get_base_url()}")
    api_key = get_api_key()
    if api_key:
        print(f"API Key: {api_key[:12]}...")
    else:
        print("API Key: NOT CONFIGURED")
    print("Starting server...")
    server.run()

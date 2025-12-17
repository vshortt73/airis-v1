"""
Iris Info Server - MCP Server for Information Tools
Provides weather, news, webcam, and web fetching capabilities
"""

import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

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
        
        print(f"[weather_get] Fetching weather for: {location}")
        
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
        
        print(f"[weather_get] Success: {result['temperature']}° {result['condition']}")
        return result
        
    except requests.RequestException as e:
        error_msg = f"Failed to fetch weather: {str(e)}"
        print(f"[weather_get] Error: {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }
    except Exception as e:
        error_msg = str(e)
        print(f"[weather_get] Error: {error_msg}")
        return {
            "success": False,
            "error": error_msg
        }

# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("="*60)
    print("IRIS INFO SERVER")
    print("="*60)
    print(f"Tools available: weather_get")
    print(f"Starting server...")
    print("="*60)
    server.run()

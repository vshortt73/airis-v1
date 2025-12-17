"""
Traits MCP Server - Personality trait management for Iris

Provides tools for Iris to:
- View her current personality traits
- Modify trait values with logging
- Review her trait modification history

This server allows Iris autonomous self-management of her personality.
"""

import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp_servers.base.base_server import IrisMCPServer
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from app import config


class TraitsMCPServer(IrisMCPServer):
    """MCP Server for managing Iris's personality traits"""
    
    def __init__(self):
        super().__init__(
            name="traits",
            #version="1.0.0"
        )
        
    def get_db_connection(self):
        """Create database connection"""
        password = os.environ.get('IRIS_DB_PASSWORD') or getattr(config, 'DB_PASSWORD', None)
        
        conn_params = {
            'host': config.DB_HOST,
            'port': config.DB_PORT,
            'database': config.DB_NAME,
            'user': config.DB_USER
        }
        
        if password:
            conn_params['password'] = password
        
        return psycopg2.connect(**conn_params)
    
    def setup_tools(self):
        """Register trait management tools"""
        
        @self.tool()
        def trait_get():
            return("placeholder")
            


        @self.tool()
        def trait_view(trait_name: str = None) -> dict:
            """
            View current personality trait values
            
            Args:
                trait_name: Optional specific trait name to view. 
                           If None, returns all traits.
            
            Returns:
                dict: Trait information with name, description, and current value
            """
            try:
                conn = self.get_db_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                if trait_name:
                    # Get specific trait
                    cursor.execute("""
                        SELECT id, name, description, value
                        FROM fulltraits
                        WHERE LOWER(name) = LOWER(%s)
                    """, (trait_name,))
                    
                    result = cursor.fetchone()
                    
                    if not result:
                        cursor.close()
                        conn.close()
                        return {
                            "success": False,
                            "error": f"Trait '{trait_name}' not found"
                        }
                    
                    trait = dict(result)
                    cursor.close()
                    conn.close()
                    
                    return {
                        "success": True,
                        "trait": {
                            "name": trait["name"],
                            "description": trait["description"],
                            "value": trait["value"]
                        }
                    }
                else:
                    # Get all traits
                    cursor.execute("""
                        SELECT id, name, description, value
                        FROM fulltraits
                        ORDER BY name ASC
                    """)
                    
                    results = cursor.fetchall()
                    cursor.close()
                    conn.close()
                    
                    traits = [
                        {
                            "name": dict(row)["name"],
                            "description": dict(row)["description"],
                            "value": dict(row)["value"]
                        }
                        for row in results
                    ]
                    
                    return {
                        "success": True,
                        "trait_count": len(traits),
                        "traits": traits
                    }
                    
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Database error: {str(e)}"
                }
        



        @self.tool()
        def trait_modify(trait_name: str, new_value: str, reason: str = None) -> dict:
            """
            Modify a personality trait value
            
            This tool allows Iris to adjust her personality traits based on
            experiences, preferences, or growth. All modifications are logged.
            
            Args:
                trait_name: Name of the trait to modify
                new_value: New value for the trait (numeric or text depending on trait)
                reason: Optional explanation for why this change is being made
            
            Returns:
                dict: Success status, old value, new value, and log ID
            """
            try:
                conn = self.get_db_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                # Get current trait value
                cursor.execute("""
                    SELECT id, name, value
                    FROM fulltraits
                    WHERE LOWER(name) = LOWER(%s)
                """, (trait_name,))
                
                result = cursor.fetchone()
                
                if not result:
                    cursor.close()
                    conn.close()
                    return {
                        "success": False,
                        "error": f"Trait '{trait_name}' not found"
                    }
                
                trait = dict(result)
                old_value = trait["value"]
                trait_id = trait["id"]
                
                # Update trait value
                cursor.execute("""
                    UPDATE fulltraits
                    SET value = %s
                    WHERE id = %s
                """, (new_value, trait_id))
                
                # Log the modification
                cursor.execute("""
                    INSERT INTO trait_modification_log 
                    (trait_id, trait_name, old_value, new_value, reason, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    trait_id,
                    trait["name"],
                    old_value,
                    new_value,
                    reason or "No reason provided",
                    datetime.now()
                ))
                
                log_id = cursor.fetchone()["id"]
                
                conn.commit()
                cursor.close()
                conn.close()
                
                return {
                    "success": True,
                    "trait_name": trait["name"],
                    "old_value": old_value,
                    "new_value": new_value,
                    "reason": reason or "No reason provided",
                    "log_id": log_id,
                    "message": f"Successfully updated {trait['name']} from {old_value} to {new_value}"
                }
                
            except Exception as e:
                if conn:
                    conn.rollback()
                return {
                    "success": False,
                    "error": f"Database error: {str(e)}"
                }
        
        @self.tool()
        def trait_log(trait_name: str = None, limit: int = 10) -> dict:
            """
            View trait modification history
            
            Args:
                trait_name: Optional trait name to filter logs. If None, shows all modifications.
                limit: Maximum number of log entries to return (default: 10, max: 100)
            
            Returns:
                dict: List of trait modifications with timestamps and reasons
            """
            try:
                # Limit bounds checking
                limit = max(1, min(limit, 100))
                
                conn = self.get_db_connection()
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                
                if trait_name:
                    # Get logs for specific trait
                    cursor.execute("""
                        SELECT 
                            id,
                            trait_name,
                            old_value,
                            new_value,
                            reason,
                            timestamp
                        FROM trait_modification_log
                        WHERE LOWER(trait_name) = LOWER(%s)
                        ORDER BY timestamp DESC
                        LIMIT %s
                    """, (trait_name, limit))
                else:
                    # Get all recent modifications
                    cursor.execute("""
                        SELECT 
                            id,
                            trait_name,
                            old_value,
                            new_value,
                            reason,
                            timestamp
                        FROM trait_modification_log
                        ORDER BY timestamp DESC
                        LIMIT %s
                    """, (limit,))
                
                results = cursor.fetchall()
                cursor.close()
                conn.close()
                
                modifications = [
                    {
                        "log_id": dict(row)["id"],
                        "trait_name": dict(row)["trait_name"],
                        "old_value": dict(row)["old_value"],
                        "new_value": dict(row)["new_value"],
                        "reason": dict(row)["reason"],
                        "timestamp": dict(row)["timestamp"].isoformat()
                    }
                    for row in results
                ]
                
                return {
                    "success": True,
                    "modification_count": len(modifications),
                    "modifications": modifications
                }
                
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Database error: {str(e)}"
                }


if __name__ == "__main__":
    server = TraitsMCPServer()
    server.run()

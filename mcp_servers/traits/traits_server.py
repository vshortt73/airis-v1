"""
Iris Traits Server - MCP Server for Character traits Tools

"""

import sys
import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from typing import Dict, Any
import os
# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from app import config
from mcp_servers.base.base_server import IrisMCPServer
import requests

# ============================================================================
# SERVER INITIALIZATION
# ============================================================================

server = IrisMCPServer(
    name="Iris Traits Serverr",
    description="Character trait management system"
)

class TraitsMCPServer(IrisMCPServer):
    """MCP Server for managing Iris's personality traits"""
    
    def __init__(self):
        super().__init__(
            name="traits",
            #version="1.0.0"
        )

def get_db_connection():
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

    # ============================================================================
    # Trait GET tool
    # ============================================================================

@server.register_tool
def trait_view(
    trait_name: Any,
  ) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT value, description
        FROM fulltraits 
        where name like %s
        LIMIT 1""", (trait_name,))
    
    value, desc = cursor.fetchone()
    cursor.close()
    conn.close()
    return {
        "success": True,
        "trait": {
            "name": trait_name,
            "value": value,
            "description": desc
        }
    }

    # ============================================================================
    # Trait list tool
    # ============================================================================

@server.register_tool
def trait_list() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name, value, description
        FROM fulltraits 
        ORDER BY NAME""")
    
    main_dict = {"success": True}
    row = cursor.fetchall()
    
    for name, value, desc in row:
        # // Add a new object to the array
         sub_dict = {"value": value, "description": desc}
         main_dict[name] = sub_dict

    cursor.close()
    conn.close()
    return main_dict

##
@server.register_tool
def trait_modify(trait_name: str, value: float, reason: str):
    if float(value) > 10 or float(value) < 0:
        return {
        "success": False,
        "error": "Value must be between 0 and 10 in increments of .1"
        }
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT value 
            FROM fulltraits 
            where name like %s
            LIMIT 1""", (trait_name,))
        
        row = cursor.fetchone()

        # Check if a row was actually returned (i.e., not None)
        if row is not None:
        # If a row exists, unpack the value from the tuple
            old_value, = row
            if float(old_value) == float(value):
                return {
                    "success": False,
                    "error": "new value is the same as the old value"
                    }
            
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                WITH updated_row AS (
                    -- Step 1: Update the main table
                    UPDATE fulltraits
                    SET value = %s
                    WHERE name = %s
                    -- We don't need 'RETURNING *' here since we provide all log data via Python variables
                ),
                inserted_log AS (
                    -- Step 2: Insert into the log table using Python variables for values
                    INSERT INTO trait_modification_log (trait_id, trait_name, old_value, new_value, reason)
                    VALUES ((select id from fulltraits where name = %s LIMIT 1), %s, %s, %s, %s) -- Removed extra comma
                    RETURNING id -- Step 3: Return the auto-generated ID of the new log entry
                )
                -- Step 4: Select the final result from the last CTE
                SELECT id FROM inserted_log;
                """, (
                    value,          # %s 1: New value for UPDATE
                    trait_name,     # %s 2: Name condition for WHERE
                    trait_name,     # %s 3: trait_name for INSERT VALUES
                    trait_name,     # %s 3: trait_name for INSERT VALUES
                    old_value,      # %s 4: old_value for INSERT VALUES
                    value,          # %s 5: new_value for INSERT VALUES
                    reason,         # %s 6: reason for INSERT VALUES
                    )
                )
                log_id, = cursor.fetchone()
                conn.commit()
                cursor.close()

                return {
                "success": True,
                "message": f"trait {trait_name} successfully updated",
                "old_value": old_value,
                "new_value": value,
                "reason": reason,
                "log_id": log_id
                }  
            except Exception as e:
                return{
                "success": False,
                "error:": f"SQL Update failed: {e}"
                } 

        else:
        # Handle the case where the query returned no results
            return {
                "success": False,
                "error": "Trait does not exist in fulltraits!"
                }


        
    conn = get_db_connection()
    cursor = conn.cursor()

# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    print("="*60)
    print("IRIS TRAIT SERVER")
    print("="*60)
    print(f"Tools available: trait_view, trait_mod, trait_list")
    print(f"Starting server...")
    print("="*60)
    #trait_list()
    server.run()

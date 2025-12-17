"""
System prompt management for Iris v3
Retrieves system prompt from PostgreSQL database (system_instructions table)
"""

import psycopg2
from typing import Dict
import os
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from app import config
from database.character_traits import get_trait_list
from database.memory_loader_experimental import get_memories
import json


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

def get_system_prompt() -> str:
    """
    Retrieve active system instructions from database
    Concatenates all active instructions ordered by instruction_order
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query for active instructions ordered by instruction_order
        cursor.execute("""
            SELECT instruction_text 
            FROM system_instructions 
            WHERE active = true 
            ORDER BY instruction_order ASC
        """)
        
        results = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if results:
            # Concatenate all instructions with double newlines
            instructions = [row[0] for row in results]
            print(f"[system_prompt.py][get_system_prompt] Successfully loaded system instructions.")
            return "\n\n".join(instructions)
        else:
            # Fallback if no active instructions in database
            return get_fallback_prompt()
            
    except Exception as e:
        print(f"[system_prompt.py][get_system_prompt] Error retrieving system prompt from database: {e}")
        print(f"[system_prompt.py][get_system_prompt] Falling back to default prompt")
        return get_fallback_prompt()

def get_fallback_prompt() -> str:
    """Fallback system prompt if database is unavailable or empty"""
    return """You are Iris, an AI assistant having a conversation with Victor.

You are helpful, thoughtful, and engaging in conversation.
Respond naturally and conversationally."""

def build_system_message() -> Dict[str, str]:
    """
    Build the system message dict for Ollama
    Assembles sections based on config flags
    Returns: {"role": "system", "content": "..."}
    """
    sections = []
    
    # Base identity
    if config.SYSTEM_INSTRUCTIONS:
        base_prompt = get_system_prompt()
        sections.append(base_prompt)
    
    # Character traits
    if config.CHARACTER_TRAITS:
        traits = get_trait_list()
        sections.append(traits)
    
    if config.EPISODIC_MEMORIES:
        #memories = get_memories("structured")    # Format A
        #memories = get_memories("conversational")  # Format B  
        memories = get_memories("xml")  # Format C
        sections.append(memories)


    # Assemble with proper spacing
    full_prompt = "\n\n".join(sections)
    
    return {
        "role": "system",
        "content": full_prompt
    } 

"""
System prompt management for Iris v3
Retrieves system prompt from PostgreSQL database (system_instructions table)
Handles image loading for vision-enabled context
"""
from colorama import Fore, Back, Style, init
init(autoreset=True) # Resets styles after each print statement

import psycopg2
from typing import Dict, List, Tuple
import os
import sys
import os; PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..' if '__file__' in dir() else '.')); sys.path.insert(0, PROJECT_ROOT)
from app import config
from database.character_traits import get_trait_list
from database.memory_loader_experimental import get_memories

from core import attachments
import json
UNSUPPORTED_KEYS = {"title", "default", "anyOf"}

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
            print(f"[system_prompt.py][get_system_prompt]" + Style.BRIGHT + Fore.GREEN + " Successfully loaded system instructions.")
            return "\n\n".join(instructions)
        else:
            # Fallback if no active instructions in database
            return get_fallback_prompt()
            
    except Exception as e:
        print(f"[system_prompt.py][get_system_prompt]" + Style.BRIGHT + Fore.RED + f"  Error retrieving system prompt from database: {e}")
        print(f"[system_prompt.py][get_system_prompt] " + Style.BRIGHT + Fore.RED + " Falling back to default prompt")
        return get_fallback_prompt()

def get_fallback_prompt() -> str:
    """Fallback system prompt if database is unavailable or empty"""
    return """You are Iris, an AI assistant having a conversation with Victor.

You are helpful, thoughtful, and engaging in conversation.
Respond naturally and conversationally."""

def build_system_message() -> Dict[str, str]:
    print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " building the system message (system prompt)")
    """
    Build the system message dict for Ollama
    Assembles sections based on config flags
    Returns: {"role": "system", "content": "..."}
    """
    sections = []
    

    # Base identity
    if config.SYSTEM_INSTRUCTIONS:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Capturing base identity")
        base_prompt = get_system_prompt()
        sections.append(base_prompt)
    

    # Character traits
    if config.CHARACTER_TRAITS:
        print(f"[system_prompt.py][build_system_message] " + Style.BRIGHT + Fore.GREEN + " Capturing trait list")
        traits = get_trait_list()
        sections.append(traits)
    

    if config.EPISODIC_MEMORIES:
        print(f"[system_prompt.py][build_system_message]" + Style.BRIGHT + Fore.GREEN + "  Capturing episodic memories (xml parsing)")
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

def assemble_full_context(conversation) -> Tuple[List[Dict], Dict[str, int]]:
    """
    Assemble complete context for Ollama with vision support
    
    Loads images from attachments and formats messages properly for Qwen3-VL
    
    Args:
        conversation: ConversationHistory instance
        
    Returns:
        Tuple of (messages_with_images, budget_report)
    """
    print(f"[system_prompt.py][assemble_full_context] ┌── ASSEMBLING CONTEXT WITH VISION ──┐")
    
    messages = []
    image_count = 0
    
    # 1. System message (no images)
    system_msg = build_system_message()
    messages.append(system_msg)
    print(f"[system_prompt.py] System message assembled")
    
    # 2. Conversation history with images
    history = conversation.get_messages()
    print(f"[system_prompt.py] Processing {len(history)} conversation messages...")
    
    for msg in history:
        # Create base message
        formatted_msg = {
            "role": msg["role"],
            "content": msg["content"]
        }
        
        # Add tool-related fields if present
        # Add tool-related fields if present
        if "tool_calls" in msg:
            # Extract just the tool_calls array from stored Ollama response
            # Database stores full response: {"message": {"tool_calls": [...]}, ...}
            # Ollama expects just the array: [{"function": {...}}]
            stored_tool_calls = msg["tool_calls"]
            if isinstance(stored_tool_calls, dict) and "message" in stored_tool_calls:
                # Extract array from nested structure
                formatted_msg["tool_calls"] = stored_tool_calls["message"]["tool_calls"]
            else:
                # Already in correct format (or legacy data)
                formatted_msg["tool_calls"] = stored_tool_calls
        if "tool_name" in msg:
            formatted_msg["tool_name"] = msg["tool_name"]
        if "tool_call_id" in msg:
            formatted_msg["tool_call_id"] = msg["tool_call_id"]
        
        # Load and encode images if attachments present
        if "attachments" in msg:
            try:
                # Parse attachments JSON
                attachment_list = attachments.parse_attachments_json(msg["attachments"])
                
                if attachment_list:
                    # Load and encode all images
                    encoded_images = []
                    for att in attachment_list:
                        if att.get("type") == "image":
                            base64_img = attachments.load_and_encode(att["path"])
                            if base64_img:
                                encoded_images.append(base64_img)
                                image_count += 1
                    
                    # Add images to message in Ollama format
                    if encoded_images:
                        formatted_msg["images"] = encoded_images
                        #print(f"[system_prompt.py]   ✓ Loaded {len(encoded_images)} image(s) for {msg['role']} message")
            
            except Exception as e:
                print(f"[system_prompt.py][assemble_full_context]" + Style.BRIGHT + Fore.GREEN + "    ✗ Error loading attachments: {e}")
        
        messages.append(formatted_msg)
    
    # NOTE: Tools are now passed separately via routes_chat.py
    # They should NOT be appended to messages - Ollama expects them as a separate parameter
    
    # Budget report
    budget_report = {
        "message_count": len(messages),
        "image_count": image_count
    }
    
    print(f"[system_prompt.py] ┌────────────────────────┐")
    print(f"[system_prompt.py] CONTEXT: {len(messages)} messages, {image_count} images")
    print(f"[system_prompt.py] └────────────────────────┘")
    
    return messages, budget_report
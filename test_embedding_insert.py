#!/usr/bin/env python3
"""
Test script to verify embedding generation on message insert
"""
import os
import sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from database.persistence import save_message, get_or_create_session
import psycopg2
from app import config

def get_db_connection():
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

def test_embedding_insert():
    print("=" * 60)
    print("Testing embedding generation on message insert")
    print("=" * 60)

    # Get or create a session
    session_id = get_or_create_session()
    print(f"\nUsing session: {session_id}")

    # Insert a test message
    test_message = "This is a test message to verify that embeddings are being generated correctly during the INSERT operation."
    print(f"\nInserting test message: {test_message}")

    success = save_message(
        session_id=session_id,
        role='user',
        message=test_message
    )

    if success:
        print("\n✓ Message saved successfully")

        # Query the database to verify the embedding was created
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, role, LEFT(message, 50) as message_preview,
                   emb_message IS NOT NULL as has_embedding,
                   vector_dims(emb_message) as embedding_dim
            FROM chat_history
            WHERE message = %s
            ORDER BY c_timestamp DESC
            LIMIT 1
        """, (test_message,))

        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            msg_id, role, preview, has_embedding, dim = result
            print(f"\nVerification Results:")
            print(f"  Message ID: {msg_id}")
            print(f"  Role: {role}")
            print(f"  Preview: {preview}")
            print(f"  Has Embedding: {has_embedding}")
            print(f"  Embedding Dimensions: {dim}")

            if has_embedding and dim == 768:
                print("\n✓✓✓ SUCCESS! Embedding was generated correctly (768 dimensions)")
                return True
            else:
                print("\n✗ FAILED! Embedding was not generated properly")
                return False
        else:
            print("\n✗ Could not find the inserted message")
            return False
    else:
        print("\n✗ Failed to save message")
        return False

if __name__ == "__main__":
    try:
        result = test_embedding_insert()
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n✗ Error during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

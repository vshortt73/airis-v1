import hashlib

def get_stable_hash(text):
    # 1. Encode text to bytes (required for hashlib)
    text_bytes = text.encode('utf-8')
    
    # 2. Generate the hash
    hash_obj = hashlib.sha256(text_bytes)
    
    # 3. Return the hexadecimal string
    return hash_obj.hexdigest()

# Example usage
text_a = "Exact Text"
text_b = """Exact Text""" # Note the trailing space

print(f"Hash A: {get_stable_hash(text_a)}")
print(f"Hash B: {get_stable_hash(text_b)}")
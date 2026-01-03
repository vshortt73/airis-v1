import psycopg2
#from emotion_classifier import classify_emotion
#from valence_regressor import predict_valence
#from arousal_regressor import predict_arousal

# === CONFIG ===
DB_CONFIG = {
    "host": "localhost",
    "dbname": "irisdb",
    "user": "irisuser",
    "password": "yourpassword"
}

SELECT_QUERY = """
SELECT DISTINCT ON (mc.session_id, mc.segment_id, mc.topic_id)
    mc.session_id, 
    mc.segment_id, 
    mc.topic_id, 
    mc.transcript, 
    em.classification AS myc
FROM 
    memory_candidates mc
LEFT JOIN LATERAL (
    SELECT classification
    FROM evaluated_memories em
    WHERE em.session_id = mc.session_id
      AND em.segment_id = mc.segment_id
      AND em.topic_id = mc.topic_id
    LIMIT 1
) em ON TRUE
WHERE 
    mc.emotion_label IS NULL
    AND (em.classification NOT LIKE 'technical' AND em.classification IS NOT NULL)
ORDER BY 
    mc.session_id, mc.segment_id, mc.topic_id;
"""

UPSERT_QUERY = """
INSERT INTO evaluated_memories (
    session_id, segment_id, topic_id, emotion_label, valence_score, arousal_score
) VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (session_id, segment_id, topic_id) DO UPDATE
SET emotion_label = EXCLUDED.emotion_label,
    valence_score = EXCLUDED.valence_score,
    arousal_score = EXCLUDED.arousal_score;
"""

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Execute the SELECT query
    cur.execute(SELECT_QUERY)
    
    # Fetch all rows
    rows = cur.fetchall()
    
    # Process each row
    for row in rows:
        session_id = row[0]
        segment_id = row[1]
        topic_id = row[2]
        transcript = row[3]
        # myc = row[4]  # classification, if needed
        
        try:
            #emotion = classify_emotion(transcript)
            emotion = "pending"
            valence = 0
            arousal = 0
            
            cur.execute(UPSERT_QUERY, (
                session_id, segment_id, topic_id,
                emotion, valence, arousal
            ))
            print(f"✓ {session_id} / {segment_id} / {topic_id} — {emotion}, V={valence:.2f}, A={arousal:.2f}")
        except Exception as e:
            print(f"✗ Failed for {session_id}, {segment_id}, {topic_id}: {e}")
    
    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
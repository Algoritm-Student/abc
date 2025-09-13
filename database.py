import sqlite3

def init_db():
    conn = sqlite3.connect('images.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS image_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            prompt TEXT,
            style TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_image(user_id, username, prompt, style):
    conn = sqlite3.connect('images.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO image_history (user_id, username, prompt, style)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, prompt, style))
    conn.commit()
    conn.close()

def get_last_style(user_id):
    conn = sqlite3.connect('images.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT style, prompt FROM image_history 
        WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1
    ''', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result  # (style, prompt) yoki None

def get_stats():
    conn = sqlite3.connect('images.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM image_history')
    total = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT style, COUNT(*) as count FROM image_history 
        GROUP BY style ORDER BY count DESC LIMIT 5
    ''')
    top_styles = cursor.fetchall()
    
    cursor.execute('''
        SELECT prompt, COUNT(*) as count FROM image_history 
        GROUP BY prompt ORDER BY count DESC LIMIT 5
    ''')
    top_prompts = cursor.fetchall()
    
    conn.close()
    return {
        'total': total,
        'top_styles': top_styles,
        'top_prompts': top_prompts
    }
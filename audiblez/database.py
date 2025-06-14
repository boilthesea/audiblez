import sqlite3
import os

def connect_db():
    """Connects to the SQLite database.

    Creates the database file and directory if they don't exist.

    Returns:
        sqlite3.Connection: The database connection object.
    """
    app_dir = os.path.expanduser("~/.audiblez")
    if not os.path.exists(app_dir):
        os.makedirs(app_dir)

    db_path = os.path.join(app_dir, "audiblez.db")
    conn = sqlite3.connect(db_path)
    create_tables(conn)
    return conn

def create_tables(conn: sqlite3.Connection):
    """Creates the necessary tables in the database if they don't exist."""
    cursor = conn.cursor()

    # User Settings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            engine TEXT,
            voice TEXT,
            speed REAL,
            custom_rate INTEGER
        )
    """)

    # Staged Books Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staged_books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            source_path TEXT NOT NULL UNIQUE,
            output_folder TEXT,
            final_compilation BOOLEAN DEFAULT 0,
            added_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Staged Chapters Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staged_chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER,
            chapter_number INTEGER,
            title TEXT,
            text_content TEXT,
            status TEXT DEFAULT 'pending', -- e.g., pending, queued, processing, completed, error
            queued_order INTEGER, -- order in the main synthesis queue if applicable
            FOREIGN KEY (book_id) REFERENCES staged_books (id) ON DELETE CASCADE
        )
    """)

    # Synthesis Queue Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS synthesis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL, -- 'chapter' or 'book_compilation'
            item_id INTEGER NOT NULL, -- Foreign key to staged_chapters.id or staged_books.id
            engine TEXT,
            voice TEXT,
            speed REAL,
            output_folder TEXT, -- Can be different from staged_books.output_folder if overridden at queue time
            status TEXT DEFAULT 'pending', -- e.g., pending, processing, completed, error
            added_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processing_start_time TIMESTAMP,
            processing_end_time TIMESTAMP,
            scheduled_time TIMESTAMP -- For scheduled tasks
        )
    """)

    conn.commit()

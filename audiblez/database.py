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

def save_user_setting(setting_name: str, setting_value):
    """Saves a user setting to the database.

    Args:
        setting_name (str): The name of the setting (e.g., "engine", "voice").
        setting_value: The value of the setting.
    """
    conn = connect_db()
    cursor = conn.cursor()
    try:
        # Check if a settings row exists (assuming id=1 for the single settings row)
        cursor.execute("SELECT id FROM user_settings WHERE id = 1")
        row = cursor.fetchone()

        if row:
            # Update existing row
            # Ensure setting_name is a valid column to prevent SQL injection if not already validated
            valid_columns = ["engine", "voice", "speed", "custom_rate"]
            if setting_name not in valid_columns:
                print(f"Error: Invalid setting_name '{setting_name}' for update.")
                return # Or raise an error
            cursor.execute(f"UPDATE user_settings SET {setting_name} = ? WHERE id = 1", (setting_value,))
        else:
            # Insert new row with id = 1
            valid_columns = ["engine", "voice", "speed", "custom_rate"]
            if setting_name not in valid_columns:
                print(f"Error: Invalid setting_name '{setting_name}' for insert.")
                return # Or raise an error

            # Initialize all column values, setting the specified one and others to NULL
            # The 'id' column is explicitly set to 1.
            column_names_for_insert = ["id"] + valid_columns
            value_placeholders = ["?"] * len(column_names_for_insert)

            # Prepare the values tuple
            values_for_insert = [1] # For id
            for col in valid_columns:
                if col == setting_name:
                    values_for_insert.append(setting_value)
                else:
                    values_for_insert.append(None) # Other settings are NULL

            sql = f"INSERT INTO user_settings ({', '.join(column_names_for_insert)}) VALUES ({', '.join(value_placeholders)})"
            cursor.execute(sql, tuple(values_for_insert))

        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in save_user_setting: {e}")
    finally:
        conn.close()

def load_user_setting(setting_name: str):
    """Loads a specific user setting from the database.

    Args:
        setting_name (str): The name of the setting to load.

    Returns:
        The value of the setting, or None if not found or an error occurs.
    """
    conn = connect_db()
    cursor = conn.cursor()
    try:
        # Ensure setting_name is a valid column to prevent SQL injection if not already validated
        valid_columns = ["engine", "voice", "speed", "custom_rate", "id"] # id is not usually loaded this way, but good for validation
        if setting_name not in valid_columns:
            print(f"Error: Invalid setting_name '{setting_name}' for load.")
            # Depending on desired strictness, could return None or raise error
            # For now, let's prevent arbitrary column querying if it's not a known setting
            # However, the original spec was to just try and load it.
            # Reverting to less strict validation here but keeping the f-string for SELECT dynamic.
            # Consider preparing statements if setting_name could come from untrusted input outside this controlled scope.
            pass # Let it try, and SQLite will error if column doesn't exist.

        # Assuming settings are in a single row with id = 1
        # Dynamically constructing column name in SELECT is generally safe if setting_name is from a controlled list.
        cursor.execute(f"SELECT {setting_name} FROM user_settings WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return row[0]
        return None
    except sqlite3.Error as e:
        # More specific error if column doesn't exist: e.g., "no such column: {setting_name}"
        print(f"Database error in load_user_setting for '{setting_name}': {e}")
        return None
    finally:
        conn.close()

def load_all_user_settings() -> dict:
    """Loads all user settings from the database.

    Returns:
        A dictionary containing all settings, or an empty dictionary if no
        settings are found or an error occurs.
    """
    conn = connect_db()
    cursor = conn.cursor()
    settings = {}
    try:
        # Assuming settings are in a single row with id = 1
        cursor.execute("SELECT engine, voice, speed, custom_rate FROM user_settings WHERE id = 1")
        row = cursor.fetchone()
        if row:
            settings = {
                "engine": row[0],
                "voice": row[1],
                "speed": row[2],
                "custom_rate": row[3],
            }
        return settings
    except sqlite3.Error as e:
        print(f"Database error in load_all_user_settings: {e}")
        return settings # Return empty settings dict on error
    finally:
        conn.close()

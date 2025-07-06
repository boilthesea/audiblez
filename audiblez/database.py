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
    # print(f"DEBUG_DB: connect_db created connection object with id: {id(conn)} for path: {db_path}")
    create_tables(conn)
    # cursor = conn.cursor() # Create a cursor to query schema
    # try:
        # Log schema for synthesis_queue
        # cursor.execute('PRAGMA table_info(synthesis_queue)')
        # synthesis_queue_schema = cursor.fetchall()
        # print(f"DEBUG_DB: synthesis_queue table schema: {synthesis_queue_schema}")

        # Log schema for queued_chapters
        # cursor.execute('PRAGMA table_info(queued_chapters)')
        # queued_chapters_schema = cursor.fetchall()
        # print(f"DEBUG_DB: queued_chapters table schema: {queued_chapters_schema}")
    # except sqlite3.Error as e:
        # print(f"DEBUG_DB: Error fetching schema: {e}")
    # Do not close cursor here if conn is returned for other operations by the caller of create_tables
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
            custom_rate INTEGER,
            next_scheduled_run INTEGER, -- Stores Unix timestamp for next schedule
            calibre_ebook_convert_path TEXT, -- Stores path to ebook-convert
            m4b_assembly_method TEXT,
            dark_mode TEXT
        )
    """)

    # Add dark_mode column to user_settings if it doesn't exist for backward compatibility
    try:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN dark_mode TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            pass  # Column already exists, which is fine
        else:
            raise  # Re-raise other operational errors

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
            chapter_number INTEGER, -- Order within the book
            title TEXT,
            text_content TEXT,
            is_selected_for_synthesis BOOLEAN DEFAULT 1, -- Whether this chapter is selected for final compilation
            status TEXT DEFAULT 'pending', -- e.g., pending, queued, processing, completed, error
            queued_order INTEGER, -- order in the main synthesis queue if applicable
            FOREIGN KEY (book_id) REFERENCES staged_books (id) ON DELETE CASCADE
        )
    """)

    # Synthesis Queue Table (New Schema)
    # The following DROP TABLE line was causing data loss and has been removed.
    # cursor.execute("DROP TABLE IF EXISTS synthesis_queue")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS synthesis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staged_book_id INTEGER,
            book_title TEXT NOT NULL,
            source_path TEXT,
            synthesis_settings TEXT NOT NULL, -- JSON string: {voice, speed, engine, output_folder}
            status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'in_progress', 'completed', 'error'
            queue_order INTEGER NOT NULL,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (staged_book_id) REFERENCES staged_books (id) ON DELETE SET NULL
        )
    """)

    # Queued Chapters Table
    # The following DROP TABLE line was causing data loss and has been removed.
    # cursor.execute("DROP TABLE IF EXISTS queued_chapters")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS queued_chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_item_id INTEGER NOT NULL,
            staged_chapter_id INTEGER, -- FK to staged_chapters.id if item from staging
            chapter_title TEXT NOT NULL,
            chapter_order INTEGER NOT NULL, -- Order of this chapter within its parent queue item
            text_content TEXT, -- Full text, can be NULL if fetched on demand
            FOREIGN KEY (queue_item_id) REFERENCES synthesis_queue (id) ON DELETE CASCADE,
            FOREIGN KEY (staged_chapter_id) REFERENCES staged_chapters (id) ON DELETE SET NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_queued_chapters_queue_item_id ON queued_chapters (queue_item_id)")


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

        valid_columns = ["engine", "voice", "speed", "custom_rate", "next_scheduled_run", "calibre_ebook_convert_path", "m4b_assembly_method", "dark_mode"]
        if setting_name not in valid_columns:
            print(f"Error: Invalid setting_name '{setting_name}' for update/insert.")
            return # Or raise an error

        if row:
            # Update existing row
            cursor.execute(f"UPDATE user_settings SET {setting_name} = ? WHERE id = 1", (setting_value,))
        else:
            # Insert new row with id = 1
            # Initialize all column values, setting the specified one and others to NULL
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
        valid_columns = ["engine", "voice", "speed", "custom_rate", "next_scheduled_run", "calibre_ebook_convert_path", "m4b_assembly_method", "dark_mode", "id"] # id for validation
        if setting_name not in valid_columns:
            print(f"Error: Invalid setting_name '{setting_name}' for load.")
            # Pass to let SQLite handle "no such column" if it's truly an invalid/new column
            # vs. a typo in a known one. UI/logic should ensure only valid names are passed.
            pass

        cursor.execute(f"SELECT {setting_name} FROM user_settings WHERE id = 1")
        row = cursor.fetchone()
        if row:
            return row[0]
        return None
    except sqlite3.Error as e:
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
        cursor.execute("SELECT engine, voice, speed, custom_rate, next_scheduled_run, calibre_ebook_convert_path, m4b_assembly_method, dark_mode FROM user_settings WHERE id = 1")
        row = cursor.fetchone()
        if row:
            settings = {
                "engine": row[0],
                "voice": row[1],
                "speed": row[2],
                "custom_rate": row[3],
                "next_scheduled_run": row[4],
                "calibre_ebook_convert_path": row[5],
                "m4b_assembly_method": row[6],
                "dark_mode": row[7],
            }
        return settings
    except sqlite3.Error as e:
        print(f"Database error in load_all_user_settings: {e}")
        return settings # Return empty settings dict on error
    finally:
        conn.close()


def add_staged_book(title: str, author: str, source_path: str, output_folder: str, chapters: list) -> int | None:
    """Adds a book and its chapters to the staging tables.

    Args:
        title (str): Book title.
        author (str): Book author.
        source_path (str): Path to the source EPUB file.
        output_folder (str): Default output folder for this book.
        chapters (list): A list of dictionaries, where each dictionary represents a chapter
                         and contains 'chapter_number', 'title', 'text_content',
                         and 'is_selected_for_synthesis'.

    Returns:
        int | None: The ID of the newly added staged_book, or None if an error occurs.
    """
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO staged_books (title, author, source_path, output_folder, final_compilation)
            VALUES (?, ?, ?, ?, 0)
        """, (title, author, source_path, output_folder))
        book_id = cursor.lastrowid
        if not book_id:
            conn.rollback()
            return None

        staged_chapters_data = []
        for chap in chapters:
            staged_chapters_data.append((
                book_id,
                chap.get('chapter_number'),
                chap.get('title'),
                chap.get('text_content'),
                chap.get('is_selected_for_synthesis', 1) # Default to selected
            ))

        cursor.executemany("""
            INSERT INTO staged_chapters (book_id, chapter_number, title, text_content, is_selected_for_synthesis)
            VALUES (?, ?, ?, ?, ?)
        """, staged_chapters_data)

        conn.commit()
        return book_id
    except sqlite3.IntegrityError as e: # Handles UNIQUE constraint violation for source_path
        print(f"Database IntegrityError in add_staged_book (possibly duplicate source_path): {e}")
        conn.rollback()
        return None
    except sqlite3.Error as e:
        print(f"Database error in add_staged_book: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def get_staged_books_with_chapters() -> list:
    """Retrieves all staged books along with their chapters.

    Returns:
        list: A list of dictionaries, where each dictionary represents a book
              and contains 'id', 'title', 'author', 'source_path', 'output_folder',
              'final_compilation', and a 'chapters' list. Each chapter in the
              'chapters' list is a dictionary with its details.
              Returns an empty list if no books are staged or an error occurs.
    """
    conn = connect_db()
    cursor = conn.cursor()
    books_dict = {}
    try:
        # Fetch all books
        cursor.execute("SELECT id, title, author, source_path, output_folder, final_compilation FROM staged_books ORDER BY added_timestamp DESC")
        books_data = cursor.fetchall()

        for book_row in books_data:
            book_id, title, author, source_path, output_folder, final_compilation = book_row
            books_dict[book_id] = {
                'id': book_id,
                'title': title,
                'author': author,
                'source_path': source_path,
                'output_folder': output_folder,
                'final_compilation': bool(final_compilation),
                'chapters': []
            }

        # Fetch all chapters and assign them to their respective books
        cursor.execute("""
            SELECT book_id, id, chapter_number, title, text_content, is_selected_for_synthesis, status
            FROM staged_chapters ORDER BY book_id, chapter_number ASC
        """)
        chapters_data = cursor.fetchall()

        for chap_row in chapters_data:
            book_id, chap_id, chap_num, chap_title, chap_text, is_selected, status = chap_row
            if book_id in books_dict:
                books_dict[book_id]['chapters'].append({
                    'id': chap_id,
                    'chapter_number': chap_num,
                    'title': chap_title,
                    'text_content': chap_text, # Consider if text_content is always needed here or fetched on demand
                    'is_selected_for_synthesis': bool(is_selected),
                    'status': status
                })

        return list(books_dict.values())

    except sqlite3.Error as e:
        print(f"Database error in get_staged_books_with_chapters: {e}")
        return []
    finally:
        conn.close()

def update_staged_chapter_selection(chapter_id: int, is_selected: bool):
    """Updates the selection status of a staged chapter."""
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE staged_chapters SET is_selected_for_synthesis = ? WHERE id = ?", (is_selected, chapter_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in update_staged_chapter_selection: {e}")
    finally:
        conn.close()

def update_staged_book_final_compilation(book_id: int, final_compilation: bool):
    """Updates the final compilation status of a staged book."""
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE staged_books SET final_compilation = ? WHERE id = ?", (final_compilation, book_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in update_staged_book_final_compilation: {e}")
    finally:
        conn.close()

def save_schedule_time(timestamp: int | None):
    """Saves the next scheduled run time (Unix timestamp) to user settings.
       Pass None to clear the schedule."""
    save_user_setting('next_scheduled_run', timestamp)

def load_schedule_time() -> int | None:
    """Loads the next scheduled run time (Unix timestamp) from user settings.
       Returns None if not set or error."""
    return load_user_setting('next_scheduled_run')


# --- Queue Management Functions ---
import json

def get_max_queue_order(conn_param: sqlite3.Connection | None = None) -> int:
    """Gets the current maximum queue_order from the synthesis_queue table.
    Accepts an optional connection parameter."""
    conn_to_use = conn_param
    was_conn_provided = conn_param is not None

    if conn_to_use is None:
        conn_to_use = connect_db()

    # print(f"DEBUG_DB: get_max_queue_order using connection id: {id(conn_to_use)} (was_provided: {was_conn_provided})")
    cursor = conn_to_use.cursor()

    try:
        cursor.execute("SELECT MAX(queue_order) FROM synthesis_queue")
        result = cursor.fetchone()
        max_order = result[0] if result and result[0] is not None else 0
        return max_order
    except sqlite3.Error as e:
        print(f"Database error in get_max_queue_order: {e}")
        return 0  # Default to 0 if error or no items
    finally:
        if not was_conn_provided and conn_to_use: # Only close if created internally
            conn_to_use.close()

def add_item_to_queue(details: dict) -> int | None:
    """Adds an item and its chapters to the synthesis queue.

    Args:
        details (dict): A dictionary containing item details:
            {
                'staged_book_id': book_id_or_none,
                'book_title': 'Title',
                'source_path': path_or_none,
                'synthesis_settings': {'voice': 'v', 'speed': 1.0, ...},
                'chapters': [
                    {'staged_chapter_id': chap_id_or_none, 'title': 'Chap 1',
                     'text_content': '...', 'order': 0 (this is chapter_order within the queue item)},
                    ...
                ]
            }
    Returns:
        int | None: The ID of the newly added synthesis_queue item, or None if an error occurs.
    """
    conn = None # Initialize conn to None for the finally block
    try:
        conn = connect_db()
        # print(f"DEBUG_DB: add_item_to_queue using connection id: {id(conn)}")
        cursor = conn.cursor()
        # print(f"DEBUG_DB: add_item_to_queue received details: {details}")
        current_max_order = get_max_queue_order(conn) # Pass the connection
        new_queue_order = current_max_order + 1
        # print(f"DEBUG_DB: new_queue_order: {new_queue_order}")

        synthesis_settings_json = json.dumps(details.get('synthesis_settings', {}))
        # print(f"DEBUG_DB: synthesis_settings_json: {synthesis_settings_json}")

        cursor.execute("""
            INSERT INTO synthesis_queue
                (staged_book_id, book_title, source_path, synthesis_settings, status, queue_order)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            details.get('staged_book_id'),
            details.get('book_title'),
            details.get('source_path'),
            synthesis_settings_json,
            'pending', # Initial status
            new_queue_order
        ))
        queue_item_id = cursor.lastrowid
        # print(f"DEBUG_DB: synthesis_queue insert generated queue_item_id: {queue_item_id}")
        if not queue_item_id:
            conn.rollback()
            # print("DEBUG_DB: add_item_to_queue rolled back (no queue_item_id).")
            return None

        chapters_to_insert = []
        for chap_detail in details.get('chapters', []):
            chapters_to_insert.append((
                queue_item_id,
                chap_detail.get('staged_chapter_id'),
                chap_detail.get('title'),
                chap_detail.get('order'), # This is chapter_order for this queue item
                chap_detail.get('text_content') # May be null
            ))
        # print(f"DEBUG_DB: chapters_to_insert for queued_chapters: {chapters_to_insert}")

        if chapters_to_insert:
            cursor.executemany("""
                INSERT INTO queued_chapters
                    (queue_item_id, staged_chapter_id, chapter_title, chapter_order, text_content)
                VALUES (?, ?, ?, ?, ?)
            """, chapters_to_insert)

        conn.commit()
        # print("DEBUG_DB: add_item_to_queue committed successfully.")
        return queue_item_id
    except sqlite3.Error as e:
        # print(f"Database error in add_item_to_queue: {e}") # Keep this one? Or rely on default Python error handling?
        print(f"Database error in add_item_to_queue: {e}") # Let's keep it for now.
        conn.rollback()
        # print("DEBUG_DB: add_item_to_queue rolled back due to SQLite error.")
        return None
    finally:
        if conn:
            conn.close()

def get_queued_items() -> list:
    """Retrieves all items from synthesis_queue, ordered by queue_order, with their chapters."""
    conn = None # Initialize conn to None for the finally block
    try:
        conn = connect_db()
        # print(f"DEBUG_DB: get_queued_items using connection id: {id(conn)}")
        cursor = conn.cursor()
        queued_items_map = {}
        # print("DEBUG_DB: get_queued_items called.")
        # Fetch all queue items
        cursor.execute("""
            SELECT id, staged_book_id, book_title, source_path, synthesis_settings, status, queue_order, date_added
            FROM synthesis_queue ORDER BY queue_order ASC
        """)
        raw_queue_items = cursor.fetchall()
        # print(f"DEBUG_DB: Raw items from synthesis_queue: {raw_queue_items}")

        for item_row in raw_queue_items:
            item_id = item_row[0]
            settings_json = item_row[4]
            try:
                synthesis_settings = json.loads(settings_json)
            except json.JSONDecodeError:
                synthesis_settings = {} # Default if JSON is malformed

            queued_items_map[item_id] = {
                'id': item_id,
                'staged_book_id': item_row[1],
                'book_title': item_row[2],
                'source_path': item_row[3],
                'synthesis_settings': synthesis_settings,
                'status': item_row[5],
                'queue_order': item_row[6],
                'date_added': item_row[7],
                'chapters': []
            }

        if not queued_items_map:
            # print("DEBUG_DB: No items found in synthesis_queue table (queued_items_map is empty after initial fetch).")
            return []

        # Fetch all chapters and assign them to their respective queue items
        # Using IN clause to fetch chapters only for the items retrieved
        item_ids_placeholder = ','.join(['?'] * len(queued_items_map))
        # print(f"DEBUG_DB: Item IDs placeholder for chapter query: {item_ids_placeholder}")
        sql_chapters = f"""
            SELECT qc.id, qc.queue_item_id, qc.staged_chapter_id, qc.chapter_title,
                   qc.chapter_order, qc.text_content
            FROM queued_chapters qc
            WHERE qc.queue_item_id IN ({item_ids_placeholder})
            ORDER BY qc.queue_item_id, qc.chapter_order ASC
        """
        cursor.execute(sql_chapters, tuple(queued_items_map.keys()))
        chapters_data = cursor.fetchall()
        # print(f"DEBUG_DB: Chapters data from queued_chapters: {chapters_data}")

        for chap_row in chapters_data:
            queue_item_id = chap_row[1]
            if queue_item_id in queued_items_map:
                queued_items_map[queue_item_id]['chapters'].append({
                    'id': chap_row[0], # queued_chapters.id
                    'staged_chapter_id': chap_row[2],
                    'title': chap_row[3],
                    'order': chap_row[4],
                    'text_content': chap_row[5] # May be None
                })

        final_list = list(queued_items_map.values())
        # print(f"DEBUG_DB: Final items returned by get_queued_items: {final_list}")
        return final_list

    except sqlite3.Error as e:
        print(f"Database error in get_queued_items: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_queue_item_status(queue_item_id: int, status: str):
    """Updates the status of a specific queue item."""
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE synthesis_queue SET status = ? WHERE id = ?", (status, queue_item_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in update_queue_item_status: {e}")
    finally:
        conn.close()

def remove_queue_item(queue_item_id: int):
    """Removes a queue item and its associated chapters from the database."""
    conn = connect_db()
    cursor = conn.cursor()
    try:
        # Cascading delete should handle queued_chapters if ON DELETE CASCADE is effective.
        # Explicitly deleting chapters first can also be done if preferred or for compatibility.
        # cursor.execute("DELETE FROM queued_chapters WHERE queue_item_id = ?", (queue_item_id,))
        cursor.execute("DELETE FROM synthesis_queue WHERE id = ?", (queue_item_id,))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in remove_queue_item: {e}")
    finally:
        conn.close()

def update_staged_chapter_status_in_db(staged_chapter_id: int, status: str):
    """Updates the status of a specific staged chapter."""
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE staged_chapters SET status = ? WHERE id = ?", (status, staged_chapter_id))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error in update_staged_chapter_status_in_db: {e}")
    finally:
        conn.close()

def get_chapter_text_content(staged_chapter_id: int) -> str | None:
    """Retrieves text_content for a given staged_chapter_id."""
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT text_content FROM staged_chapters WHERE id = ?", (staged_chapter_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    except sqlite3.Error as e:
        print(f"Database error in get_chapter_text_content: {e}")
        return None
    finally:
        conn.close()

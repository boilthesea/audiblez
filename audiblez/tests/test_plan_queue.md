**Test Plan: Audiblez Queue Functionality**

**1. Objective:**
   Verify that the queue functionality in Audiblez allows users to add books/chapters, manage the queue, process items with correct settings, and that the queue state is persistent across application sessions.

**2. Scope:**
   *   Adding items to the queue from the "Chapters" tab.
   *   Adding items to the queue from the "Staging" tab.
   *   Display of queued items and their settings.
   *   Queue persistence (saving and loading across restarts).
   *   Processing of the queue ("Run Queue" button).
   *   Sequential processing of items with correct, per-item settings.
   *   Status updates (Pending, In Progress, Completed, Error).
   *   Removal of items from the queue.
   *   Fetching and processing of actual chapter text for items from the "Staging" tab.
   *   Error handling during processing.

**3. Test Cases:**

   **3.1. Adding Items to Queue:**
      *   **TC_ADD_001 (Chapters Tab - Single Chapter):**
          1. Open an EPUB.
          2. In "Chapters" tab, select one chapter.
          3. Change voice, speed, and output folder settings.
          4. Click "Queue Selected Book Portions".
          5. **Expected:** Item appears in "Queue" tab with correct book title, chapter name, and captured settings. Database reflects the new item.
      *   **TC_ADD_002 (Chapters Tab - Multiple Chapters):**
          1. Open an EPUB.
          2. In "Chapters" tab, select multiple (e.g., 3) non-contiguous chapters.
          3. Set specific synthesis settings.
          4. Click "Queue Selected Book Portions".
          5. **Expected:** Item in "Queue" tab shows correct book title, summary of chapters (e.g., "Selected chapters (3)"), and captured settings.
      *   **TC_ADD_003 (Staging Tab - Selected Chapters):**
          1. Open an EPUB, stage it.
          2. In "Staging" tab, select a few chapters for the staged book.
          3. Change global synthesis settings.
          4. Click "▶️ Queue Selected Chapters" for that book.
          5. **Expected:** Item in "Queue" tab shows correct book title, selected staged chapter titles, and captured global settings. Database reflects new item.
      *   **TC_ADD_004 (Multiple Books/Settings):**
          1. Queue item from Book A with Settings X (e.g., from Chapters tab).
          2. Open Book B (or use a different staged book).
          3. Queue item from Book B with Settings Y (different voice/speed).
          4. **Expected:** Both items appear in the queue correctly, each displaying its respective book title, chapters, and settings (X for item 1, Y for item 2).
      *   **TC_ADD_005 (Queue Unselected Chapters - Chapters Tab):**
          1. Open an EPUB.
          2. Do not select any chapters in the "Chapters" tab.
          3. Click "Queue Selected Book Portions".
          4. **Expected:** An error message is displayed; no item is added to the queue.
      *   **TC_ADD_006 (Queue Unselected Chapters - Staging Tab):**
          1. Open an EPUB and stage it.
          2. Do not select any chapters for the staged book in the "Staging" tab.
          3. Click "▶️ Queue Selected Chapters".
          4. **Expected:** An error message is displayed; no item is added to the queue.

   **3.2. Queue Display and Persistence:**
      *   **TC_DISP_001 (Verify Displayed Info):**
          1. Add an item to the queue.
          2. **Expected:** "Queue" tab accurately displays: Book Title, Chapter(s) summary/list, Engine, Voice, Speed, Output Folder, initial Status ("Pending"), and a "Remove" button.
      *   **TC_PERS_001 (Persistence Across Restart):**
          1. Add several items (from both Chapters and Staging tabs) to the queue.
          2. Close Audiblez.
          3. Reopen Audiblez.
          4. **Expected:** The "Queue" tab displays all previously added items in the same order and with the same details.
      *   **TC_PERS_002 (Empty Queue Persistence):**
          1. Ensure queue is empty.
          2. Close and reopen Audiblez.
          3. **Expected:** Queue remains empty.

   **3.3. Processing the Queue:**
      *   **TC_PROC_001 (Run Single Item Queue):**
          1. Add one item to the queue.
          2. Click "🚀 Run Queue".
          3. **Expected:** Item status changes: "Pending" -> "⏳ In Progress" -> "✅ Completed". Synthesis starts and completes. Output files are generated in the specified output folder using the item's settings. Global progress bar reflects current item. "Run Queue" button is disabled during processing.
      *   **TC_PROC_002 (Run Multi-Item Queue - Sequential Processing):**
          1. Add 2-3 items to the queue with different settings (e.g., different voices, speeds, output folders if possible).
          2. Click "🚀 Run Queue".
          3. **Expected:** Items are processed sequentially. Status updates occur for each item. Each item uses its own stored settings for synthesis. Output files for each item are correct.
      *   **TC_PROC_003 (Staged Item Processing - Text Fetch):**
          1. Stage a book. Queue some of its chapters.
          2. Ensure the chapter text in the database for these staged chapters is correct.
          3. Run the queue.
          4. **Expected:** The synthesis for the staged item uses the chapter text fetched from the database. Output is correct.
      *   **TC_PROC_004 (Queue Processing - UI Controls Disabled):**
          1. Start queue processing.
          2. **Expected:** "Run Queue" button, main "Start Audiobook Synthesis" button, and parameter panels (voice, speed, engine, output folder) are disabled during queue processing. They are re-enabled after the queue finishes.
      *   **TC_PROC_005 (Item Completion and Removal from Active Queue):**
          1. Run a queue with multiple items.
          2. **Expected:** After an item is "✅ Completed", it is removed from the `self.queue_items` list (or rather, the list is reloaded from DB after `_finalize_queue_processing` removes it from DB). The UI refreshes to show remaining items.

   **3.4. Removing Items from Queue:**
      *   **TC_REM_001 (Remove Pending Item):**
          1. Add an item to the queue. Status is "Pending".
          2. Click the "❌ Remove" button for that item. Confirm removal.
          3. **Expected:** Item is removed from the "Queue" tab display and the database.
      *   **TC_REM_002 (Attempt Remove In-Progress Item):**
          1. Add two items. Start queue processing.
          2. While the first item is "⏳ In Progress", attempt to click its "❌ Remove" button.
          3. **Expected:** Removal is prevented (button might be disabled or a message shown). The item continues processing.
      *   **TC_REM_003 (Remove Item After Queue Processed):**
          1. Process a queue. Items are "✅ Completed". (Note: `_finalize_queue_processing` should remove completed items. This test verifies if any completed items somehow remain and can be removed, or confirms they are auto-removed).
          2. If a completed item remains, attempt to remove it.
          3. **Expected:** Item is removed. (Or, confirm no completed items remain to be manually removed).
      *   **TC_REM_004 (Remove and Verify Persistence):**
          1. Add multiple items. Remove one.
          2. Close and reopen Audiblez.
          3. **Expected:** The removed item is not present. Other items are.

   **3.5. Error Handling:**
      *   **TC_ERR_001 (Synthesis Error in Queue Item):**
          1. Add multiple items. Ensure one item will cause a synthesis error (e.g., invalid voice for the engine, or simulate error in `core.main` if possible).
          2. Run the queue.
          3. **Expected:** The problematic item's status changes to "⚠️ Error". The queue continues to process subsequent items.
      *   **TC_ERR_002 (Error Item Persistence):**
          1. Let an item error out as in TC_ERR_001.
          2. Close and reopen Audiblez.
          3. **Expected:** The item with "⚠️ Error" status is still in the queue (or verify if `_finalize_queue_processing` removes error items from DB - current subtask report implies it does). If it's removed, this is also an expected outcome based on current implementation.
      *   **TC_ERR_003 (Staged Item Text Fetch Fail - During Add to Queue):**
          1. Simulate `db.get_chapter_text_content()` returning None/error when adding a staged chapter to queue (if `on_queue_selected_staged_chapters` tries to fetch text early).
          2. **Expected:** Handle gracefully. Item might not be added, or added with a warning. (Subtask report says "warning is logged, and text_content might be None (to be fetched again during processing)").
      *   **TC_ERR_004 (Staged Item Text Fetch Fail - During Processing):**
          1. Add a staged item where `text_content` is missing and `db.get_chapter_text_content()` will fail during `process_next_queue_item`.
          2. Run the queue.
          3. **Expected:** The item is marked as "⚠️ Error" in the UI and DB, and processing skips to the next item. (Subtask report confirms this: "item is marked as an error in the DB and skipped").

**4. Test Environment:**
   *   Application: Audiblez (current development version with queue feature)
   *   Operating System: (Specify OS if tests are platform-dependent, e.g., Windows, macOS, Linux)
   *   Dependencies: Python, wxPython, PyTorch, Kokoro, Spacy, Ebooklib, etc., as required by Audiblez.
   *   Sample EPUB files (varied content, some simple, some complex if possible).

**5. Test Data:**
   *   At least 2-3 different EPUB files.
   *   Staging at least one of these books.
   *   Various synthesis settings combinations (voices, speeds, CPU/CUDA if applicable).

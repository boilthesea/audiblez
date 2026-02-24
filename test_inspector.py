import os
import sys
from pathlib import Path

# Add the current directory to sys.path to import audiblez
sys.path.append(str(Path(__file__).parent.parent))

from audiblez.calibre_handler import open_book_experimental
from audiblez.inspector import generate_report

def main():
    book_path = "s:/Files/nexus/http/audiblez/sample.epub"
    report_path = "sample_report.html"
    
    print(f"Running structural analysis on {book_path}...")
    
    # Mocking the UI callback
    def mock_callback():
        return None

    # Use Method 1 (Ebooklib) for the test
    method_id, msg, chapters, metadata, cover = open_book_experimental(
        book_path, 
        ui_callback_for_path_selection=mock_callback, 
        method=1,
        include_skeleton=True
    )

    if chapters:
        print(f"Extracted {len(chapters)} sections.")
        section_data = []
        for ch in chapters:
            if isinstance(ch, dict):
                section_data.append(ch)
            else:
                section_data.append({
                    'title': getattr(ch, 'title', getattr(ch, 'get_name', lambda: 'Chapter')()),
                    'src': getattr(ch, 'src', getattr(ch, 'file_name', 'N/A')),
                    'pre_chars': getattr(ch, 'pre_chars', 0),
                    'post_chars': getattr(ch, 'post_chars', 0),
                    'skeleton': getattr(ch, 'skeleton', '')
                })

        # Metadata processing
        meta_dict = {}
        if isinstance(metadata, dict):
            meta_dict = metadata
        else:
            # Simple conversion for Ebooklib metadata
            meta_dict = {'title': 'Sample Book', 'creator': 'Sample Author'}

        generate_report(meta_dict, section_data, report_path)
        print(f"Report generated: {os.path.abspath(report_path)}")
    else:
        print(f"Failed to extract sections: {msg}")

if __name__ == "__main__":
    main()

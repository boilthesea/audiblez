
import zipfile
import xml.etree.ElementTree as ET
from ebooklib import epub
from audiblez.core import convert_ebook_with_calibre, extract_chapters_and_metadata_from_calibre_html
import os
from pathlib import Path
import tempfile
import shutil

def extract_chapters_with_calibre(chapters, epub_path, opf_dir, ui_callback_for_path_selection):
    temp_dir = tempfile.mkdtemp()
    with zipfile.ZipFile(epub_path, 'r') as z:
        z.extractall(temp_dir)

    extracted_chapters = []
    for chapter_info in chapters:
        html_path = os.path.join(temp_dir, opf_dir, chapter_info['src']).replace('\\', '/')
        if os.path.exists(html_path):
            # Using a simplified conversion to text. A more robust solution might convert to a clean HTML snippet first.
            text_content = convert_html_to_text(html_path, ui_callback_for_path_selection)
            chapter_info['extracted_text'] = text_content
            extracted_chapters.append(chapter_info)
        else:
            print(f"Warning: Chapter HTML file not found: {html_path}")

    shutil.rmtree(temp_dir)
    return extracted_chapters

def convert_html_to_text(html_path, ui_callback_for_path_selection):
    from audiblez.core import get_calibre_ebook_convert_path
    import subprocess

    ebook_convert_exe = get_calibre_ebook_convert_path(ui_callback_for_path_selection)
    if not ebook_convert_exe:
        print("ERROR: Calibre's ebook-convert command not found. Cannot convert HTML to text.")
        return ""

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as temp_txt_file:
        temp_txt_path = temp_txt_file.name
    
    command = [ebook_convert_exe, html_path, temp_txt_path]
    
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        with open(temp_txt_path, 'r', encoding='utf-8') as f:
            text = f.read()
        return text
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Calibre ebook-convert failed while converting HTML to text: {e}")
        print(f"Stderr: {e.stderr}")
        return ""
    finally:
        if os.path.exists(temp_txt_path):
            os.remove(temp_txt_path)

def open_book_experimental(file_path, ui_callback_for_path_selection):
    """
    Experimental function to open an ebook, with multiple fallbacks for TOC extraction.
    """
    print("Attempting to open book with experimental method...")

    # Method 1: Try ebooklib directly
    try:
        print("Parser: Attempting to use ebooklib directly.")
        book = epub.read_epub(file_path)
        toc = book.toc
        if toc:
            print("Parser: Successfully extracted TOC with ebooklib.")
            chapters = []
            for link in book.toc:
                item = book.get_item_with_href(link.href)
                chapters.append({'title': link.title, 'src': item.file_name, 'extracted_text': item.content})

            return "TOC extracted with ebooklib", chapters, book.metadata
    except Exception as e:
        print(f"Parser: ebooklib failed to open the book. Reason: {e}")

    # Method 2: Fallback to zip file extraction
    try:
        print("Parser: Attempting to extract TOC from zip archive.")
        with zipfile.ZipFile(file_path, 'r') as z:
            if 'META-INF/container.xml' in z.namelist():
                # Find the rootfile path from container.xml
                container = z.read('META-INF/container.xml')
                root = ET.fromstring(container)
                rootfile_path = root.find('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile').attrib['full-path']
                
                # Get the directory of the rootfile, which is needed to resolve relative paths in the OPF
                opf_dir = os.path.dirname(rootfile_path)

                # Read the rootfile to find the TOC
                rootfile = z.read(rootfile_path)
                root = ET.fromstring(rootfile)
                
                # Find the toc.ncx file path
                toc_id = root.find('.//*[@media-type="application/x-dtbncx+xml"]').attrib['id']
                toc_href = root.find(f'.//*[@id="{toc_id}"]').attrib['href']
                toc_path = os.path.join(opf_dir, toc_href).replace('\\', '/')
                
                # Extract and parse the toc.ncx
                toc_content = z.read(toc_path)
                toc_root = ET.fromstring(toc_content)
                
                chapters = []
                for nav_point in toc_root.findall('.//{http://www.daisy.org/z3986/2005/ncx/}navPoint'):
                    title = nav_point.find('.//{http://www.daisy.org/z3986/2005/ncx/}text').text
                    src = nav_point.find('.//{http://www.daisy.org/z3986/2005/ncx/}content').attrib['src']
                    chapters.append({'title': title, 'src': src})
                
                print("Parser: Successfully extracted and parsed toc.ncx from zip.")
                chapters_with_text = extract_chapters_with_calibre(chapters, file_path, opf_dir, ui_callback_for_path_selection)
                return "TOC extracted from zip", chapters_with_text, None

    except Exception as e:
        print(f"Parser: Failed to extract TOC from zip. Reason: {e}")

    # Method 3: Fallback to original Calibre method
    print("Parser: Falling back to Calibre-only method.")
    html_file_path, opf_file_path, cover_image_path = convert_ebook_with_calibre(
        file_path, 
        ui_callback_for_path_selection=ui_callback_for_path_selection
    )
    if html_file_path:
        chapters, metadata = extract_chapters_and_metadata_from_calibre_html(html_file_path, opf_file_path)
        return "Chapters extracted with Calibre", chapters, metadata

    return "Failed to open book", None, None

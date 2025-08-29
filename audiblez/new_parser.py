
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
        html_path = os.path.join(temp_dir, opf_dir, chapter_info['src'])
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
                if isinstance(link, epub.Link):
                    item = book.get_item_with_href(link.href)
                    chapters.append({'title': link.title, 'src': item.file_name})
                elif isinstance(link, tuple) and len(link) > 1 and hasattr(link[0], 'title') and hasattr(link[0], 'href'):
                    # Handle nested chapters, which ebooklib returns as tuples
                    item = book.get_item_with_href(link[0].href)
                    chapters.append({'title': link[0].title, 'src': item.file_name})
            
            # Find the opf file directory
            rootfile_path = book.opf_file
            opf_dir = os.path.dirname(rootfile_path)

            chapters_with_text = extract_chapters_with_calibre(chapters, file_path, opf_dir, ui_callback_for_path_selection)
            
            from audiblez.core import find_cover
            cover = find_cover(book)
            cover_info = None
            if cover and cover.content:
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_cover_file:
                    temp_cover_file.write(cover.content)
                    cover_info = {'type': 'path', 'content': temp_cover_file.name}

            return "TOC extracted with ebooklib", chapters_with_text, book.metadata, cover_info
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

                # Read the rootfile to find the TOC and metadata
                rootfile_content = z.read(rootfile_path)
                root = ET.fromstring(rootfile_content)
                
                # --- Metadata Extraction from OPF ---
                metadata = {}
                for meta_element in root.findall('.//{http://purl.org/dc/elements/1.1/}title'):
                    metadata['title'] = [meta_element.text]
                for meta_element in root.findall('.//{http://purl.org/dc/elements/1.1/}creator'):
                    metadata['creator'] = [meta_element.text]

                # --- Cover Extraction from OPF ---
                cover_info = None
                # Strategy 1: Look for <meta name="cover">
                meta_cover = root.find('.//meta[@name="cover"]')
                if meta_cover is not None:
                    cover_id = meta_cover.attrib['content']
                    cover_href_tag = root.find(f'.//*[@id="{cover_id}"]')
                    if cover_href_tag is not None:
                        cover_href = cover_href_tag.attrib['href']
                        cover_path = os.path.join(opf_dir, cover_href).replace('\\', '/')
                        if cover_path in z.namelist():
                            cover_content = z.read(cover_path)
                            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_cover_file:
                                temp_cover_file.write(cover_content)
                                cover_info = {'type': 'path', 'content': temp_cover_file.name}

                # Strategy 2: Look for item with id="cover"
                if not cover_info:
                    cover_item = root.find('.//*[@id="cover"]')
                    if cover_item is not None:
                        cover_href = cover_item.attrib['href']
                        cover_path = os.path.join(opf_dir, cover_href).replace('\\', '/')
                        if cover_path in z.namelist():
                            cover_content = z.read(cover_path)
                            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_cover_file:
                                temp_cover_file.write(cover_content)
                                cover_info = {'type': 'path', 'content': temp_cover_file.name}

                # Strategy 3: Look for item with "cover" in the href
                if not cover_info:
                    for item in root.findall('.//opf:item', namespaces={'opf': 'http://www.idpf.org/2007/opf'}):
                        if 'cover' in item.attrib.get('href', '').lower() and item.attrib.get('media-type', '').startswith('image'):
                            cover_href = item.attrib['href']
                            cover_path = os.path.join(opf_dir, cover_href).replace('\\', '/')
                            if cover_path in z.namelist():
                                cover_content = z.read(cover_path)
                                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_cover_file:
                                    temp_cover_file.write(cover_content)
                                    cover_info = {'type': 'path', 'content': temp_cover_file.name}
                                break

                # Strategy 4: Use Calibre to extract the cover
                if not cover_info:
                    print("Parser: Falling back to Calibre to extract cover.")
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_cover_file:
                            temp_cover_path = temp_cover_file.name
                        
                        from audiblez.core import get_calibre_ebook_convert_path
                        import subprocess
                        ebook_convert_exe = get_calibre_ebook_convert_path(ui_callback_for_path_selection)
                        if ebook_convert_exe:
                            command = [ebook_convert_exe, file_path, temp_cover_path]
                            subprocess.run(command, check=True, capture_output=True, text=True)
                            if os.path.exists(temp_cover_path):
                                # The cover is already at temp_cover_path, so just use it.
                                cover_info = {'type': 'path', 'content': temp_cover_path}
                    except Exception as e:
                        print(f"Parser: Calibre cover extraction failed: {e}")

                # Find the toc.ncx file path
                toc_id_element = root.find('.//*[@media-type="application/x-dtbncx+xml"]')
                if toc_id_element is not None:
                    toc_id = toc_id_element.attrib['id']
                    toc_href_element = root.find(f'.//*[@id="{toc_id}"]')
                    if toc_href_element is not None:
                        toc_href = toc_href_element.attrib['href']
                        toc_path = os.path.join(opf_dir, toc_href).replace('\\', '/')
                    else:
                        # Handle case where toc href is not found
                        print("Parser: Could not find toc href element.")
                        toc_path = None
                else:
                    # Handle case where toc id is not found
                    print("Parser: Could not find toc id element.")
                    toc_path = None
                
                # Extract and parse the toc.ncx
                toc_content = z.read(toc_path)
                toc_root = ET.fromstring(toc_content)
                
                chapters = []
                for nav_point in toc_root.findall('.//{http://www.daisy.org/z3986/2005/ncx/}navPoint'):
                    title = nav_point.find('.//{http://www.daisy.org/z3986/2005/ncx/}text').text
                    src_parts = nav_point.find('.//{http://www.daisy.org/z3986/2005/ncx/}content').attrib['src'].split('#')
                    src = src_parts[0]
                    chapters.append({'title': title, 'src': src})
                
                print("Parser: Successfully extracted and parsed toc.ncx from zip.")
                chapters_with_text = extract_chapters_with_calibre(chapters, file_path, opf_dir, ui_callback_for_path_selection)
                return "TOC extracted from zip", chapters_with_text, metadata, cover_info

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
        cover_info = {'type': 'path', 'content': cover_image_path} if cover_image_path else None
        return "Chapters extracted with Calibre", chapters, metadata, cover_info
    
    return "Failed to open book", None, None, None

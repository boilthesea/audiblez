import zipfile
import xml.etree.ElementTree as ET
from ebooklib import epub
import os
from pathlib import Path
import tempfile
import shutil
import platform
import re
import subprocess
from bs4 import BeautifulSoup
from types import SimpleNamespace
import traceback

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

def open_book_experimental(file_path, ui_callback_for_path_selection, method=None):
    """
    Experimental function to open an ebook, with multiple fallbacks for TOC extraction.
    If 'method' (1, 2, or 3) is provided, only that method is attempted.
    """
    print(f"Attempting to open book with experimental method (method override: {method})...")

    # Method 1: Try ebooklib directly
    if method is None or method == 1:
        try:
            print("Parser: Attempting to use ebooklib directly.")
            book = epub.read_epub(file_path)
            
            # Robust opf_dir detection from container.xml
            current_opf_dir = ""
            try:
                with zipfile.ZipFile(file_path, 'r') as z:
                    if 'META-INF/container.xml' in z.namelist():
                        container = z.read('META-INF/container.xml')
                        container_root = ET.fromstring(container)
                        rootfile_path = container_root.find('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile').attrib['full-path']
                        current_opf_dir = os.path.dirname(rootfile_path)
                        print(f"Parser: Detected opf_dir: '{current_opf_dir}'")
            except Exception as e_opf:
                print(f"Parser: Warning: Could not detect opf_dir from container.xml: {e_opf}")

            def flatten_toc(toc_list):
                flat = []
                for link in toc_list:
                    if isinstance(link, epub.Link):
                        href = link.href.split('#')[0]
                        item = book.get_item_with_href(href)
                        if item:
                            # ebooklib items often have paths relative to the OPF file.
                            # extract_chapters_with_calibre expects 'src' relative to opf_dir.
                            # item.file_name is the full path in the zip.
                            # So we strip the opf_dir from its beginning if it exists.
                            src = item.file_name
                            if current_opf_dir and src.startswith(current_opf_dir + '/'):
                                src = src[len(current_opf_dir) + 1:]
                            elif current_opf_dir and src.startswith(current_opf_dir + '\\'):
                                src = src[len(current_opf_dir) + 1:]
                                
                            flat.append({'title': link.title, 'src': src})
                    elif isinstance(link, tuple) and len(link) > 1:
                        # Handle nested chapters
                        if isinstance(link[0], epub.Link):
                            flat.extend(flatten_toc([link[0]]))
                        elif hasattr(link[0], 'title'):
                            # It's likely a Section, we'll skip adding the section itself
                            # as a chapter if it has no href, but process its children.
                            pass
                        flat.extend(flatten_toc(link[1]))
                return flat

            chapters = []
            if book.toc:
                print("Parser: Successfully extracted TOC with ebooklib.")
                chapters = flatten_toc(book.toc)
            
            # Fallback: If no chapters found via TOC, look for documents sequentially (like core.py)
            if not chapters:
                print("Parser: TOC empty or failed. Falling back to sequential document extraction.")
                from audiblez.core import is_chapter, find_document_chapters_and_extract_texts
                all_docs = find_document_chapters_and_extract_texts(book)
                for doc in all_docs:
                    if is_chapter(doc):
                        src = doc.file_name
                        if current_opf_dir and src.startswith(current_opf_dir + '/'):
                            src = src[len(current_opf_dir) + 1:]
                        elif current_opf_dir and src.startswith(current_opf_dir + '\\'):
                            src = src[len(current_opf_dir) + 1:]
                        chapters.append({'title': doc.get_name(), 'src': src})
            
            if not chapters:
                print("Parser: No chapters found with ebooklib.")
                if method == 1:
                    return 1, "No chapters found", None, None, None
            else:
                chapters_with_text = extract_chapters_with_calibre(chapters, file_path, current_opf_dir, ui_callback_for_path_selection)
                
                # Check if we actually got ANY text. If not, this method failed.
                has_text = any(ch.get('extracted_text') for ch in chapters_with_text)
                
                if not has_text:
                    print("Parser: ebooklib extraction succeeded but no text was found in any chapter. Method 1 FAILED.")
                    if method == 1:
                        return 1, "No text extracted from chapters", None, None, None
                    # If method is None, we implicitly fall through to Method 2.
                else:
                    from audiblez.core import find_cover
                    cover = find_cover(book)
                    cover_info = None
                    if cover and cover.content:
                        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_cover_file:
                            temp_cover_file.write(cover.content)
                            cover_info = {'type': 'path', 'content': temp_cover_file.name}

                    return 1, "TOC/Documents extracted with ebooklib", chapters_with_text, book.metadata, cover_info
        except Exception as e:
            print(f"Parser: ebooklib failed to open the book. Reason: {e}")
            traceback.print_exc()
            if method == 1:
                return 1, f"Method 1 failed: {e}", None, None, None

    # Method 2: Fallback to zip file extraction
    if method is None or method == 2:
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
                            
                            ebook_convert_exe = get_calibre_ebook_convert_path(ui_callback_for_path_selection)
                            if ebook_convert_exe:
                                command = [ebook_convert_exe, file_path, temp_cover_path]
                                # import pprint
                                # print("subprocess.run environment:")
                                # pprint.pprint(dict(os.environ))
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
                    if toc_path and toc_path in z.namelist():
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
                        return 2, "TOC extracted from zip", chapters_with_text, metadata, cover_info
                    else:
                        print(f"Parser: toc.ncx not found at {toc_path} or missing in zip.")

        except Exception as e:
            print(f"Parser: Failed to extract TOC from zip. Reason: {e}")
            if method == 2:
                return 2, f"Method 2 failed: {e}", None, None, None

    # Method 3: Fallback to original Calibre method
    if method is None or method == 3:
        print("Parser: Attempting Calibre-only method (Method 3).")
        try:
            # Create a temporary directory for Calibre output
            output_html_dir = tempfile.mkdtemp()
            html_file_path, opf_file_path, cover_image_path = convert_ebook_with_calibre(
                file_path, 
                output_html_dir,
                ui_callback_for_path_selection=ui_callback_for_path_selection
            )
            if html_file_path:
                chapters, metadata = extract_chapters_and_metadata_from_calibre_html(html_file_path, opf_file_path)
                cover_info = {'type': 'path', 'content': cover_image_path} if cover_image_path else None
                # We should probably return a cleanup function or handle it later. 
                # For now, it's consistent with others.
                return 3, "Chapters extracted with Calibre", chapters, metadata, cover_info
            else:
                print("Parser: Calibre conversion failed to produce HTML.")
        except Exception as e:
            print(f"Parser: Calibre-only method failed. Reason: {e}")
            if method == 3:
                return 3, f"Method 3 failed: {e}", None, None, None
    
    return None, "Failed to open book with any experimental parser", None, None, None



def get_calibre_ebook_convert_path(ui_callback_for_path_selection=None) -> str | None:
    """
    Finds the path to Calibre's ebook-convert executable.
    1. Checks the system PATH.
    2. Checks a stored path in the database.
    3. If not found, and ui_callback_for_path_selection is provided, calls it to ask the user.
    """
    # Try finding in PATH first
    ebook_convert_path = shutil.which("ebook-convert")
    if ebook_convert_path:
        # Further validation: check if calibre-debug is in the same directory
        # This helps confirm it's a full Calibre installation.
        calibre_dir = Path(ebook_convert_path).parent
        debug_exe_name = "calibre-debug.exe" if platform.system() == "Windows" else "calibre-debug"
        if (calibre_dir / debug_exe_name).exists():
            print(f"Found ebook-convert in PATH and validated: {ebook_convert_path}")
            return ebook_convert_path
        else:
            print(f"Found ebook-convert in PATH ({ebook_convert_path}), but {debug_exe_name} missing in parent directory. Will check DB/prompt.")

    # Try loading from database
    from audiblez.database import load_user_setting, save_user_setting # Local import
    stored_path_str = load_user_setting('calibre_ebook_convert_path')
    if stored_path_str:
        stored_path = Path(stored_path_str)
        calibre_dir = stored_path.parent
        debug_exe_name = "calibre-debug.exe" if platform.system() == "Windows" else "calibre-debug"
        if stored_path.exists() and stored_path.is_file() and (calibre_dir / debug_exe_name).exists():
            print(f"Using validated Calibre path from database: {stored_path_str}")
            return str(stored_path)
        else:
            print(f"Stored Calibre path '{stored_path_str}' is invalid or incomplete. Ignoring.")
            save_user_setting('calibre_ebook_convert_path', None) # Clear invalid path

    # If not found and callback is provided, ask the user
    if ui_callback_for_path_selection:
        print("Calibre 'ebook-convert' not found in PATH or DB. Prompting user for Calibre directory.")
        user_selected_calibre_dir_str = ui_callback_for_path_selection()
        if user_selected_calibre_dir_str:
            user_selected_calibre_dir = Path(user_selected_calibre_dir_str)
            exe_name = "ebook-convert.exe" if platform.system() == "Windows" else "ebook-convert"
            debug_exe_name = "calibre-debug.exe" if platform.system() == "Windows" else "calibre-debug"
            
            ebook_convert_path = user_selected_calibre_dir / exe_name
            calibre_debug_path = user_selected_calibre_dir / debug_exe_name

            if ebook_convert_path.exists() and ebook_convert_path.is_file() and calibre_debug_path.exists():
                found_path = str(ebook_convert_path)
                print(f"User selected Calibre directory. Validated ebook-convert at: {found_path}")
                save_user_setting('calibre_ebook_convert_path', found_path)
                return found_path
            else:
                # Provide more specific feedback if validation fails
                if not ebook_convert_path.exists():
                    print(f"Validation failed: '{exe_name}' not found in '{user_selected_calibre_dir}'.")
                if not calibre_debug_path.exists():
                    print(f"Validation failed: '{debug_exe_name}' not found in '{user_selected_calibre_dir}'.")
                
                # The UI itself should show an error message to the user.
                # This function's responsibility is to return None on failure.
                return None
    else:
        print("Calibre 'ebook-convert' not found in PATH or DB. No UI callback provided to ask user.")

    return None


def convert_ebook_with_calibre(input_ebook_path: str, output_html_dir: str, ui_callback_for_path_selection=None) -> str | None:
    """
    Converts an ebook to HTML using Calibre's ebook-convert.

    Args:
        input_ebook_path (str): Path to the input ebook file.
        output_html_dir (str): Directory where the HTML output should be saved.
                               The actual HTML file will be named 'output.html' inside this dir.
        ui_callback_for_path_selection: Function to call if Calibre path needs user selection.

    Returns:
        tuple[str | None, str | None, str | None]: Paths to the extracted HTML file,
                                                   metadata.opf file, and cover image file if successful,
                                                   otherwise (None, None, None).
    """
    ebook_convert_exe = get_calibre_ebook_convert_path(ui_callback_for_path_selection)
    if not ebook_convert_exe:
        print("ERROR: Calibre's ebook-convert command not found. Cannot convert ebook.")
        # UI should have already shown an error from get_calibre_ebook_convert_path if it prompted.
        return None

    input_path = Path(input_ebook_path)
    if not input_path.exists() or not input_path.is_file():
        print(f"ERROR: Input ebook file not found: {input_ebook_path}")
        return None

    output_dir = Path(output_html_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Define a predictable output HTMLZ filename within the output_html_dir
    output_htmlz_file = output_dir / "output.htmlz"
    # Define the expected name of the HTML file inside the HTMLZ archive
    extracted_html_filename = "index.html" # Common default, might need adjustment
    final_extracted_html_path = output_dir / extracted_html_filename
    extracted_opf_path = None
    extracted_cover_path = None

    # ebook-convert options:
    # --enable-heuristics: Useful for some conversions.
    # --keep-ligatures: Preserves ligatures.
    # --smarten-punctuation: Converts plain quotes, dashes, and ellipsis to typographic equivalents.
    # Consider adding more options as needed, e.g., for TOC generation, font embedding, etc.
    # For now, a basic conversion to HTML.
    # The output format is determined by the extension of the output file.
    # So, `output.html` implies HTML conversion.
    # Calibre might output a single HTML file or multiple files (e.g., for chapters)
    # depending on the input format and its internal logic.
    # Using a single output.html file is simpler to start with.
    # If Calibre splits it, we might need to find the main index file or process all HTML files.

    command = [
        ebook_convert_exe,
        str(input_path),
        str(output_htmlz_file), # Output to .htmlz
        # Example options (can be customized or made configurable):
        # "--enable-heuristics",
        # "--smarten-punctuation",
        # "--output-profile=tablet", # Generic profile
    ]

    print(f"Running Calibre conversion: {' '.join(command)}")
    try:
        # Using subprocess.run with capture_output=True to get stdout/stderr
        # Timeout can be added if conversions might hang indefinitely.
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8')

        if result.returncode == 0:
            print(f"Calibre conversion to HTMLZ successful. Output: {output_htmlz_file}")
            if output_htmlz_file.exists():
                # Unzip the HTMLZ file
                import zipfile
                try:
                    with zipfile.ZipFile(output_htmlz_file, 'r') as zip_ref:
                        # Try to find the common main HTML file names
                        # Calibre often uses 'index.html', 'content.html', or 'book.html'
                        # Sometimes it could also be titlepage.xhtml then main content is linked.
                        # For simplicity, we'll look for a few common ones.
                        # A more robust solution might inspect the OPF if present in the zip.
                        potential_html_files = [name for name in zip_ref.namelist() if name.lower().endswith(('.html', '.xhtml'))]

                        main_html_in_zip = None
                        if extracted_html_filename in potential_html_files: # Check our default first
                            main_html_in_zip = extracted_html_filename
                        elif 'content.html' in potential_html_files:
                            main_html_in_zip = 'content.html'
                        elif 'book.html' in potential_html_files:
                            main_html_in_zip = 'book.html'
                        elif potential_html_files: # Fallback to the first HTML/XHTML file found
                            main_html_in_zip = potential_html_files[0]
                            print(f"Warning: '{extracted_html_filename}' not found in HTMLZ. Using first HTML file found: '{main_html_in_zip}'")

                        if main_html_in_zip:
                            # Extract the specific HTML file to the target path
                            # Need to ensure the final_extracted_html_path is just the filename part
                            # and zip_ref.extract expects the member name and the output directory.
                            zip_ref.extract(main_html_in_zip, path=output_dir)
                            # Rename if necessary to the consistent final_extracted_html_path
                            extracted_file_from_zip = output_dir / main_html_in_zip
                            if extracted_file_from_zip != final_extracted_html_path:
                                extracted_file_from_zip.rename(final_extracted_html_path)

                            print(f"Successfully extracted '{main_html_in_zip}' to '{final_extracted_html_path}'")

                            # Clean up the HTMLZ file after successful extraction
                            # --- Start: Extract metadata.opf and cover image ---
                            opf_filename_in_zip = "metadata.opf" # Standard name
                            cover_filename_in_zip = None
                            temp_extracted_opf_path = None

                            if opf_filename_in_zip in zip_ref.namelist():
                                zip_ref.extract(opf_filename_in_zip, path=output_dir)
                                temp_extracted_opf_path = output_dir / opf_filename_in_zip
                                print(f"Successfully extracted '{opf_filename_in_zip}' to '{temp_extracted_opf_path}'")

                                # Parse OPF to find cover image filename
                                try:
                                    import xml.etree.ElementTree as ET
                                    tree = ET.parse(temp_extracted_opf_path)
                                    root = tree.getroot()
                                    # Namespace dictionary for OPF parsing
                                    ns = {
                                        'opf': 'http://www.idpf.org/2007/opf',
                                        'dc': 'http://purl.org/dc/elements/1.1/'
                                    }
                                    # Try to find cover image via <meta name="cover" content="ID_OF_COVER_ITEM" />
                                    # then find item with that ID, then get its href.
                                    # Or directly from <guide><reference type="cover" href="cover.jpg"/></guide>
                                    guide_cover_href = None
                                    for guide_ref in root.findall('.//opf:guide/opf:reference[@type="cover"]', ns):
                                        guide_cover_href = guide_ref.get('href')
                                        if guide_cover_href:
                                            break

                                    if guide_cover_href:
                                        cover_filename_in_zip = guide_cover_href
                                        print(f"Found cover image reference in OPF guide: '{cover_filename_in_zip}'")
                                    else: # Fallback: try to find meta tag for cover
                                        cover_meta_content_id = None
                                        for meta_tag in root.findall('.//opf:metadata/opf:meta[@name="cover"]', ns):
                                            cover_meta_content_id = meta_tag.get('content')
                                            if cover_meta_content_id:
                                                break
                                        if cover_meta_content_id:
                                            for item_tag in root.findall(f".//opf:manifest/opf:item[@id='{cover_meta_content_id}']", ns):
                                                cover_href = item_tag.get('href')
                                                if cover_href:
                                                    cover_filename_in_zip = cover_href
                                                    print(f"Found cover image reference in OPF manifest via meta tag: '{cover_filename_in_zip}'")
                                                    break

                                    if not cover_filename_in_zip:
                                        # Fallback: if no explicit cover in OPF, look for common names
                                        common_cover_names = ['cover.jpg', 'cover.jpeg', 'cover.png']
                                        for name in common_cover_names:
                                            if name in zip_ref.namelist():
                                                cover_filename_in_zip = name
                                                print(f"Found potential cover by common name: '{cover_filename_in_zip}'")
                                                break
                                except ET.ParseError as e_xml:
                                    print(f"Warning: Could not parse '{opf_filename_in_zip}' to find cover image: {e_xml}")
                                except Exception as e_opf_parse:
                                    print(f"Warning: Error processing '{opf_filename_in_zip}' for cover: {e_opf_parse}")


                            if cover_filename_in_zip and cover_filename_in_zip in zip_ref.namelist():
                                zip_ref.extract(cover_filename_in_zip, path=output_dir)
                                extracted_cover_path = output_dir / cover_filename_in_zip
                                print(f"Successfully extracted cover image '{cover_filename_in_zip}' to '{extracted_cover_path}'")
                            elif cover_filename_in_zip:
                                print(f"Warning: Cover image '{cover_filename_in_zip}' referenced in OPF but not found in HTMLZ archive.")
                            else:
                                print("Warning: Could not determine cover image filename from OPF or common names.")

                            if temp_extracted_opf_path and temp_extracted_opf_path.exists():
                                extracted_opf_path = temp_extracted_opf_path # Assign to the function's return variable
                            else:
                                print(f"Warning: '{opf_filename_in_zip}' not found or not extracted from HTMLZ.")
                            # --- End: Extract metadata.opf and cover image ---

                            # Clean up the HTMLZ file after successful extraction of all parts
                            try:
                                output_htmlz_file.unlink()
                            except OSError as e:
                                print(f"Warning: Could not delete HTMLZ file '{output_htmlz_file}': {e}")

                            return str(final_extracted_html_path), str(extracted_opf_path) if extracted_opf_path else None, str(extracted_cover_path) if extracted_cover_path else None
                        else:
                            print(f"ERROR: Could not find a suitable HTML/XHTML file (e.g., '{extracted_html_filename}', 'content.html') in '{output_htmlz_file}'.")
                            print(f"Files in archive: {zip_ref.namelist()}")
                            return None, None, None
                except zipfile.BadZipFile:
                    print(f"ERROR: Failed to unzip '{output_htmlz_file}'. File may be corrupted or not a valid zip archive.")
                    return None, None, None
                except KeyError as e_key:
                    print(f"ERROR: Assumed HTML file (or other critical file like '{str(e_key)}') not found within the HTMLZ archive '{output_htmlz_file}'.")
                    return None, None, None
                except Exception as e_zip:
                    print(f"ERROR: An error occurred during unzipping of '{output_htmlz_file}': {e_zip}")
                    traceback.print_exc()
                    return None, None, None
            else:
                # This case should be rare if returncode is 0, but good to check.
                print(f"ERROR: Calibre reported success, but output HTMLZ file '{output_htmlz_file}' not found.")
                print(f"Calibre stdout:\n{result.stdout}")
                print(f"Calibre stderr:\n{result.stderr}")
                return None, None, None
        else:
            print(f"ERROR: Calibre ebook-convert failed with return code {result.returncode}")
            print(f"Calibre stdout:\n{result.stdout}")
            print(f"Calibre stderr:\n{result.stderr}")
            # Potentially clean up output_htmlz_file if it was created but is incomplete/invalid
            if output_htmlz_file.exists():
                try:
                    output_htmlz_file.unlink()
                except OSError as e:
                    print(f"Warning: Could not delete incomplete output HTMLZ file '{output_htmlz_file}': {e}")
            return None, None, None

    except FileNotFoundError:
        # This would happen if ebook_convert_exe path was somehow invalid despite earlier checks.
        print(f"ERROR: ebook-convert executable not found at '{ebook_convert_exe}'. This shouldn't happen if get_calibre_ebook_convert_path worked.")
        return None, None, None
    except subprocess.TimeoutExpired:
        print("ERROR: Calibre conversion timed out.")
        return None, None, None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during Calibre conversion: {e}")
        traceback.print_exc()
        return None, None, None


def extract_chapters_and_metadata_from_calibre_html(html_file_path: str, opf_file_path: str | None) -> tuple[list, dict]:
    """
    Parses an HTML file (presumably generated by Calibre) and extracts chapters.
    Also parses the associated metadata.opf file for book metadata.
    Chapters are identified by h1 or h2 tags in the HTML.

    Args:
        html_file_path (str): Path to the HTML file.
        opf_file_path (str | None): Path to the metadata.opf file.

    Returns:
        tuple[list, dict]: A list of chapter objects (SimpleNamespace) and
                           a dictionary containing extracted metadata (e.g., title, creator).
    """
    chapters = []
    metadata = {
        'title': 'Untitled Book',
        'creator': 'Unknown Author',
        'language': 'en',
        'subjects': [],
        'rights': '',
        'publisher': '',
        'date': ''
    }
    
    # Parse metadata.opf first
    if opf_file_path and Path(opf_file_path).exists():
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(opf_file_path)
            root = tree.getroot()
            ns = {
                'opf': 'http://www.idpf.org/2007/opf',
                'dc': 'http://purl.org/dc/elements/1.1/'
            }

            title_tag = root.find('.//dc:title', ns)
            if title_tag is not None and title_tag.text:
                metadata['title'] = title_tag.text.strip()

            creator_tag = root.find('.//dc:creator[@opf:role="aut"]', ns)
            if creator_tag is None: # Fallback if role="aut" is not present
                creator_tag = root.find('.//dc:creator', ns)
            if creator_tag is not None and creator_tag.text:
                metadata['creator'] = creator_tag.text.strip()
                # Attempt to get file-as for sorting if present
                file_as = creator_tag.get('{http://www.idpf.org/2007/opf}file-as')
                if file_as:
                    metadata['creator_sort'] = file_as.strip()


            lang_tag = root.find('.//dc:language', ns)
            if lang_tag is not None and lang_tag.text:
                metadata['language'] = lang_tag.text.strip().lower()

            for subject_tag in root.findall('.//dc:subject', ns):
                if subject_tag.text:
                    metadata['subjects'].append(subject_tag.text.strip())

            rights_tag = root.find('.//dc:rights', ns)
            if rights_tag is not None and rights_tag.text:
                metadata['rights'] = rights_tag.text.strip()

            publisher_tag = root.find('.//dc:publisher', ns)
            if publisher_tag is not None and publisher_tag.text:
                metadata['publisher'] = publisher_tag.text.strip()

            date_tag = root.find('.//dc:date', ns)
            if date_tag is not None and date_tag.text:
                metadata['date'] = date_tag.text.strip()

            print(f"Successfully parsed metadata from '{opf_file_path}': {metadata['title']} by {metadata['creator']}")
        except ET.ParseError as e_xml:
            print(f"Warning: Could not parse '{opf_file_path}': {e_xml}")
        except Exception as e_opf:
            print(f"Warning: Error processing '{opf_file_path}': {e_opf}")
            traceback.print_exc()
    else:
        print(f"Warning: metadata.opf file not provided or not found at '{opf_file_path}'. Using default metadata.")


    # Now parse HTML for chapters
    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        # Use metadata title as book_overall_title if available, else from HTML title
        book_overall_title = metadata['title']
        if book_overall_title == 'Untitled Book': # Check if it's still the default
            html_title_tag = soup.find('title')
            if html_title_tag and html_title_tag.string:
                book_overall_title = html_title_tag.string.strip()


        content_body = soup.body if soup.body else soup

        if not content_body:
            print(f"Warning: Could not find <body> or main content in {html_file_path}. No chapters extracted.")
            return [], metadata

        # Relevant tags for content extraction, similar to EPUB processing
        # but chapters are delimited by h1/h2 in the flow of these tags.
        
        def create_chapter_object(title, text_content, index):
            chapter_obj = SimpleNamespace()
            chapter_obj.title = title # Used by core.main for file naming if get_name() not present
            chapter_obj.short_name = title.replace('/', '_').replace('\\', '_') # For UI display & internal use
            chapter_obj.extracted_text = text_content.strip()
            chapter_obj.is_selected = True  # Default to selected
            chapter_obj.chapter_index = index # For UI events and ordering
            # Mimic EbookLib item methods if needed by other parts of the code, e.g. get_name()
            chapter_obj.get_name = lambda: title # Simple mock
            chapter_obj.get_type = lambda: "calibre_html_chapter" # Dummy type
            return chapter_obj

        # New chapter splitting logic using find_next_siblings to avoid duplication
        chapter_headings = content_body.find_all(['h1', 'h2'])
        chapter_index_counter = 0

        for heading in chapter_headings:
            title = heading.get_text(strip=True)
            
            content_tags = []
            for sibling in heading.find_next_siblings():
                if sibling.name in ['h1', 'h2']:
                    break  # Stop at the next chapter heading
                content_tags.append(sibling)
            
            # Extract text from the collected tags for this chapter
            content = '\n'.join([tag.get_text(separator='\n', strip=True) for tag in content_tags]).strip()

            # Heuristics to identify real chapters
            is_likely_chapter = (
                re.search(r'^(chapter|part|book)\s*\d+', title, re.IGNORECASE) or
                re.search(r'^\d+', title) or
                len(content) > 500  # Assume long sections are chapters
            )
            
            is_likely_not_chapter = (
                'contents' in title.lower() or
                'title page' in title.lower() or
                'copyright' in title.lower() or
                'introduction' in title.lower() and len(content) < 1500 # Short intros are not chapters
            )

            if is_likely_chapter and not is_likely_not_chapter:
                chapters.append(create_chapter_object(title, content, chapter_index_counter))
                chapter_index_counter += 1

        # If no chapters were found, treat the whole content as one chapter
        if not chapters and content_body:
            all_text = content_body.get_text(separator='\n', strip=True)
            if all_text: # Ensure there's actual text before creating a chapter
                chapters.append(create_chapter_object(book_overall_title or "Full Text", all_text, 0))

        if chapters: # Only print if chapters were actually extracted
            print(f"Extracted {len(chapters)} chapters from Calibre HTML output.")
        elif not content_body:
            pass # Already warned about missing body
        else:
            print(f"No distinct chapters (h1/h2) found in HTML, and no fallback content extracted from {html_file_path}.")

        # Deselect chapters with "gutenberg" in the title
        for chapter in chapters:
            if 'gutenberg' in chapter.title.lower():
                chapter.is_selected = False
                print(f"Deselecting chapter '{chapter.title}' due to 'gutenberg' in title.")

        return chapters, metadata

    except FileNotFoundError:
        print(f"ERROR: HTML file not found for chapter extraction: {html_file_path}")
        return [], metadata # Return empty chapters list and current metadata
    except Exception as e:
        print(f"ERROR: Failed to parse or extract chapters from HTML file '{html_file_path}': {e}")
        traceback.print_exc()
        return [], metadata # Return empty chapters list and current metadata

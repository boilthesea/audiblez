import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

def find_cover(book):
    def is_image(item):
        return item is not None and item.media_type.startswith('image/')

    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        if is_image(item):
            return item

    for meta in book.get_metadata('OPF', 'cover'):
        if is_image(item := book.get_item_with_id(meta[1]['content'])):
            return item

    if is_image(item := book.get_item_with_id('cover')):
        return item

    for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        if 'cover' in item.get_name().lower() and is_image(item):
            return item

    return None

def find_document_chapters_and_extract_texts(book, include_skeleton=False):
    """Returns every chapter that is an ITEM_DOCUMENT and enriches each chapter with extracted_text."""
    document_chapters = []
    for chapter in book.get_items():
        if chapter.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        xml = chapter.get_body_content()
        chapter.pre_chars = len(xml)
        if include_skeleton:
            from audiblez.inspector import create_skeleton
            chapter.skeleton = create_skeleton(xml)
            
        soup = BeautifulSoup(xml, features='lxml')
        chapter.extracted_text = ''
        html_content_tags = ['title', 'p', 'h1', 'h2', 'h3', 'h4', 'li']
        for text in [c.text.strip() for c in soup.find_all(html_content_tags) if c.text]:
            if not text.endswith('.'):
                text += '.'
            chapter.extracted_text += text + '\n'
        chapter.post_chars = len(chapter.extracted_text)
        document_chapters.append(chapter)
    for i, c in enumerate(document_chapters):
        c.chapter_index = i  # this is used in the UI to identify chapters
    return document_chapters

def open_book_pure_python(file_path, include_skeleton=False):
    """
    Pure Python EPUB loader using ebooklib and BeautifulSoup.
    No Calibre dependency.
    """
    book = epub.read_epub(file_path)
    
    # Metadata
    title = "Untitled Book"
    meta_title_dc = book.get_metadata('DC', 'title')
    if meta_title_dc:
        title = meta_title_dc[0][0]
    
    author = "Unknown Author"
    meta_creator_dc = book.get_metadata('DC', 'creator')
    if meta_creator_dc:
        author = meta_creator_dc[0][0]
        
    # Cover
    cover_item = find_cover(book)
    cover_info = None
    if cover_item and cover_item.get_content():
        cover_info = {
            'type': 'epub_cover',
            'content': cover_item.get_content()
        }
        
    # Chapters
    raw_chapters = find_document_chapters_and_extract_texts(book, include_skeleton=include_skeleton)
    
    # Convert EpubHtml objects to dicts for UI consistency
    chapters = []
    for c in raw_chapters:
        chapter_dict = {
            'title': c.get_name() if hasattr(c, 'get_name') else getattr(c, 'title', 'Chapter'),
            'extracted_text': getattr(c, 'extracted_text', ''),
            'chapter_index': getattr(c, 'chapter_index', 0),
            'pre_chars': getattr(c, 'pre_chars', 0),
            'post_chars': getattr(c, 'post_chars', 0),
            'src': getattr(c, 'file_name', ''),
            'is_selected': True # Default to selected
        }
        if include_skeleton and hasattr(c, 'skeleton'):
            chapter_dict['skeleton'] = c.skeleton
        chapters.append(chapter_dict)
    
    # Format metadata as expected by the UI/Core
    metadata = {
        'title': title,
        'creator': author
    }
    
    return 1, "Chapters extracted with ebooklib (Pure Python)", chapters, metadata, cover_info

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# audiblez - A program to convert e-books into audiobooks using
# Kokoro-82M model for high-quality text-to-speech synthesis.
# by Claudio Santini 2025 - https://claudio.uk
import os
import traceback
from glob import glob

import torch.cuda
import spacy
import ebooklib
import soundfile
import numpy as np
import time
import shutil
import subprocess
import platform
import re
from io import StringIO
from types import SimpleNamespace
from tabulate import tabulate
from pathlib import Path
from string import Formatter
from bs4 import BeautifulSoup
from kokoro import KPipeline
from ebooklib import epub
from pick import pick
import importlib.resources # Added for accessing package data files
import markdown # Added for unmark function

from audiblez.database import load_user_setting # Added

sample_rate = 24000


def load_spacy():
    if not spacy.util.is_package("xx_ent_wiki_sm"):
        print("Downloading Spacy model xx_ent_wiki_sm...")
        spacy.cli.download("xx_ent_wiki_sm")


def set_espeak_library():
    """Find the espeak library path"""
    try:

        if os.environ.get('ESPEAK_LIBRARY'):
            library = os.environ['ESPEAK_LIBRARY']
        elif platform.system() == 'Darwin':
            from subprocess import check_output
            try:
                cellar = Path(check_output(["brew", "--cellar"], text=True).strip())
                pattern = cellar / "espeak-ng" / "*" / "lib" / "*.dylib"
                if not (library := next(iter(glob(str(pattern))), None)):
                    raise RuntimeError("No espeak-ng library found; please set the path manually")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                raise RuntimeError("Cannot locate Homebrew Cellar. Is 'brew' installed and in PATH?") from e
        elif platform.system() == 'Linux':
            library = glob('/usr/lib/*/libespeak-ng*')[0]
        elif platform.system() == 'Windows':
            library = 'C:\\Program Files*\\eSpeak NG\\libespeak-ng.dll'
        else:
            print('Unsupported OS, please set the espeak library path manually')
            return
        print('Using espeak library:', library)
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        EspeakWrapper.set_library(library)
    except Exception:
        traceback.print_exc()
        print("Error finding espeak-ng library:")
        print("Probably you haven't installed espeak-ng.")
        print("On Mac: brew install espeak-ng")
        print("On Linux: sudo apt install espeak-ng")


def main(file_path, voice, pick_manually, speed, output_folder='.',
         max_chapters=None, max_sentences=None, selected_chapters=None, post_event=None):
    if post_event: post_event('CORE_STARTED')
    load_spacy()
    if output_folder != '.':
        Path(output_folder).mkdir(parents=True, exist_ok=True)

    filename = Path(file_path).name

    extension = '.epub'
    book = epub.read_epub(file_path)
    meta_title = book.get_metadata('DC', 'title')
    title = meta_title[0][0] if meta_title else ''
    meta_creator = book.get_metadata('DC', 'creator')
    creator = meta_creator[0][0] if meta_creator else ''

    cover_maybe = find_cover(book)
    cover_image = cover_maybe.get_content() if cover_maybe else b""
    if cover_maybe:
        print(f'Found cover image {cover_maybe.file_name} in {cover_maybe.media_type} format')

    document_chapters = find_document_chapters_and_extract_texts(book)

    if not selected_chapters:
        if pick_manually is True:
            selected_chapters = pick_chapters(document_chapters)
        else:
            selected_chapters = find_good_chapters(document_chapters)
    print_selected_chapters(document_chapters, selected_chapters)
    texts = [c.extracted_text for c in selected_chapters]

    has_ffmpeg = shutil.which('ffmpeg') is not None
    if not has_ffmpeg:
        print('\033[91m' + 'ffmpeg not found. Please install ffmpeg to create mp3 and m4b audiobook files.' + '\033[0m')

    # Load custom rate from database and determine chars_per_sec for stats
    db_custom_rate = load_user_setting('custom_rate')
    default_chars_per_sec = 500 if torch.cuda.is_available() else 50
    current_chars_per_sec = default_chars_per_sec

    if db_custom_rate is not None:
        try:
            rate_from_db = int(db_custom_rate)
            if rate_from_db > 0:
                current_chars_per_sec = rate_from_db
                print(f"Using custom characters-per-second rate from database: {current_chars_per_sec}")
            else:
                print(f"Invalid custom rate from database ({db_custom_rate}), using default: {default_chars_per_sec}")
        except ValueError:
            print(f"Could not parse custom rate from database ('{db_custom_rate}'), using default: {default_chars_per_sec}")
    else:
        print(f"No custom rate in database, using default: {default_chars_per_sec}")

    stats = SimpleNamespace(
        total_chars=sum(map(len, texts)),
        processed_chars=0,
        chars_per_sec=current_chars_per_sec # Use the determined rate
    )
    print('Started at:', time.strftime('%H:%M:%S'))
    print(f'Total characters: {stats.total_chars:,}')
    print('Total words:', len(' '.join(texts).split()))
    eta = strfdelta((stats.total_chars - stats.processed_chars) / stats.chars_per_sec)
    print(f'Estimated time remaining (assuming {stats.chars_per_sec} chars/sec): {eta}')
    set_espeak_library()
    pipeline = KPipeline(lang_code=voice[0])  # a for american or b for british etc.

    chapter_wav_files = []
    for i, chapter in enumerate(selected_chapters, start=1):
        if max_chapters and i > max_chapters: break
        text = chapter.extracted_text
        # Use chapter.title if get_name() is not available (for ChapterForCore objects from queue)
        if hasattr(chapter, 'get_name'):
            original_name = chapter.get_name()
        elif hasattr(chapter, 'title'):
            original_name = chapter.title
        else:
            original_name = f"chapter_{i}" # Fallback if neither is present
        xhtml_file_name = original_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        chapter_wav_path = Path(output_folder) / filename.replace(extension, f'_chapter_{i}_{voice}_{xhtml_file_name}.wav')
        chapter_wav_files.append(chapter_wav_path)

        # Apply filters before checking length or existence, so stats are based on filtered text length
        # (though current stats.processed_chars uses pre-filter length if skipping)
        if i == 1:
            # add intro text
            text = f'{title} – {creator}.\n\n' + text

        # Apply filters to the chapter text
        # The default filter_file_path in apply_filters is "audiblez/filter.txt"
        filtered_text = apply_filters(text)
        # It might be useful to know if text changed:
        # if filtered_text != text:
        #    print(f"DEBUG: Filters applied to chapter {i}. Original length: {len(text)}, New length: {len(filtered_text)}")
        # text = filtered_text # Use filtered text from here

        if Path(chapter_wav_path).exists():
            print(f'File for chapter {i} already exists. Skipping')
            # Note: stats.processed_chars here will use original text length if we don't update 'text' var earlier
            stats.processed_chars += len(text) # Original text length for skip consistency
            if post_event:
                post_event('CORE_CHAPTER_FINISHED', chapter_index=chapter.chapter_index)
            continue

        # Use filtered text for length check and processing
        if len(filtered_text.strip()) < 10:
            print(f'Skipping empty chapter {i} (after filtering)')
            chapter_wav_files.remove(chapter_wav_path)
            # Potentially add original length to processed_chars if skipping here, or adjust logic
            # For now, skipping means it doesn't contribute to processed_chars beyond initial estimate
            continue

        start_time = time.time()
        if post_event: post_event('CORE_CHAPTER_STARTED', chapter_index=chapter.chapter_index)
        audio_segments = gen_audio_segments(
            pipeline, filtered_text, voice, speed, stats, post_event=post_event, max_sentences=max_sentences)
        if audio_segments:
            final_audio = np.concatenate(audio_segments)
            soundfile.write(chapter_wav_path, final_audio, sample_rate)
            end_time = time.time()
            delta_seconds = end_time - start_time
            chars_per_sec = len(text) / delta_seconds
            print('Chapter written to', chapter_wav_path)
            if post_event: post_event('CORE_CHAPTER_FINISHED', chapter_index=chapter.chapter_index)
            print(f'Chapter {i} read in {delta_seconds:.2f} seconds ({chars_per_sec:.0f} characters per second)')
        else:
            print(f'Warning: No audio generated for chapter {i}')
            chapter_wav_files.remove(chapter_wav_path)

    if has_ffmpeg:
        create_index_file(title, creator, chapter_wav_files, output_folder)
        create_m4b(chapter_wav_files, filename, cover_image, output_folder)
        if post_event: post_event('CORE_FINISHED')


def find_cover(book):
    def is_image(item):
        return item is not None and item.media_type.startswith('image/')

    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        if is_image(item):
            return item

    # https://idpf.org/forum/topic-715
    for meta in book.get_metadata('OPF', 'cover'):
        if is_image(item := book.get_item_with_id(meta[1]['content'])):
            return item

    if is_image(item := book.get_item_with_id('cover')):
        return item

    for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        if 'cover' in item.get_name().lower() and is_image(item):
            return item

    return None


def print_selected_chapters(document_chapters, chapters):
    ok = 'X' if platform.system() == 'Windows' else '✅'
    print(tabulate([
        [i, c.get_name(), len(c.extracted_text), ok if c in chapters else '', chapter_beginning_one_liner(c)]
        for i, c in enumerate(document_chapters, start=1)
    ], headers=['#', 'Chapter', 'Text Length', 'Selected', 'First words']))


def gen_audio_segments(pipeline, text, voice, speed, stats=None, max_sentences=None, post_event=None):
    nlp = spacy.load('xx_ent_wiki_sm')
    nlp.add_pipe('sentencizer')
    audio_segments = []
    doc = nlp(text)
    sentences = list(doc.sents)
    for i, sent in enumerate(sentences):
        if max_sentences and i > max_sentences: break
        for gs, ps, audio in pipeline(sent.text, voice=voice, speed=speed, split_pattern=r'\n\n\n'):
            audio_segments.append(audio)
        if stats:
            stats.processed_chars += len(sent.text)
            stats.progress = stats.processed_chars * 100 // stats.total_chars
            stats.eta = strfdelta((stats.total_chars - stats.processed_chars) / stats.chars_per_sec)
            if post_event: post_event('CORE_PROGRESS', stats=stats)
            print(f'Estimated time remaining: {stats.eta}')
            print('Progress:', f'{stats.progress}%\n')
    return audio_segments


def gen_text(text, voice='af_heart', output_file='text.wav', speed=1, play=False):
    lang_code = voice[:1]
    pipeline = KPipeline(lang_code=lang_code)
    load_spacy()
    audio_segments = gen_audio_segments(pipeline, text, voice=voice, speed=speed);
    final_audio = np.concatenate(audio_segments)
    soundfile.write(output_file, final_audio, sample_rate)
    if play:
        subprocess.run(['ffplay', '-autoexit', '-nodisp', output_file])


def find_document_chapters_and_extract_texts(book):
    """Returns every chapter that is an ITEM_DOCUMENT and enriches each chapter with extracted_text."""
    document_chapters = []
    for chapter in book.get_items():
        if chapter.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        xml = chapter.get_body_content()
        soup = BeautifulSoup(xml, features='lxml')
        chapter.extracted_text = ''
        html_content_tags = ['title', 'p', 'h1', 'h2', 'h3', 'h4', 'li']
        for text in [c.text.strip() for c in soup.find_all(html_content_tags) if c.text]:
            if not text.endswith('.'):
                text += '.'
            chapter.extracted_text += text + '\n'
        document_chapters.append(chapter)
    for i, c in enumerate(document_chapters):
        c.chapter_index = i  # this is used in the UI to identify chapters
    return document_chapters


def is_chapter(c):
    name = c.get_name().lower()
    has_min_len = len(c.extracted_text) > 100
    title_looks_like_chapter = bool(
        'chapter' in name.lower()
        or re.search(r'part_?\d{1,3}', name)
        or re.search(r'split_?\d{1,3}', name)
        or re.search(r'ch_?\d{1,3}', name)
        or re.search(r'chap_?\d{1,3}', name)
    )
    return has_min_len and title_looks_like_chapter


def chapter_beginning_one_liner(c, chars=20):
    s = c.extracted_text[:chars].strip().replace('\n', ' ').replace('\r', ' ')
    return s + '…' if len(s) > 0 else ''


def find_good_chapters(document_chapters):
    chapters = [c for c in document_chapters if c.get_type() == ebooklib.ITEM_DOCUMENT and is_chapter(c)]
    if len(chapters) == 0:
        print('Not easy to recognize the chapters, defaulting to all non-empty documents.')
        chapters = [c for c in document_chapters if c.get_type() == ebooklib.ITEM_DOCUMENT and len(c.extracted_text) > 10]
    return chapters


def pick_chapters(chapters):
    # Display the document name, the length and first 50 characters of the text
    chapters_by_names = {
        f'{c.get_name()}\t({len(c.extracted_text)} chars)\t[{chapter_beginning_one_liner(c, 50)}]': c
        for c in chapters}
    title = 'Select which chapters to read in the audiobook'
    ret = pick(list(chapters_by_names.keys()), title, multiselect=True, min_selection_count=1)
    selected_chapters_out_of_order = [chapters_by_names[r[0]] for r in ret]
    selected_chapters = [c for c in chapters if c in selected_chapters_out_of_order]
    return selected_chapters


def strfdelta(tdelta, fmt='{D:02}d {H:02}h {M:02}m {S:02}s'):
    remainder = int(tdelta)
    f = Formatter()
    desired_fields = [field_tuple[1] for field_tuple in f.parse(fmt)]
    possible_fields = ('W', 'D', 'H', 'M', 'S')
    constants = {'W': 604800, 'D': 86400, 'H': 3600, 'M': 60, 'S': 1}
    values = {}
    for field in possible_fields:
        if field in desired_fields and field in constants:
            values[field], remainder = divmod(remainder, constants[field])
    return f.format(fmt, **values)


def concat_wavs_with_ffmpeg(chapter_files, output_folder, filename):
    wav_list_txt = Path(output_folder) / filename.replace('.epub', '_wav_list.txt')
    with open(wav_list_txt, 'w') as f:
        for wav_file in chapter_files:
            f.write(f"file '{wav_file}'\n")
    concat_file_path = Path(output_folder) / filename.replace('.epub', '.tmp.mp4')
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', wav_list_txt, '-c', 'copy', concat_file_path])
    Path(wav_list_txt).unlink()
    return concat_file_path


def create_m4b(chapter_files, filename, cover_image, output_folder):
    concat_file_path = concat_wavs_with_ffmpeg(chapter_files, output_folder, filename)
    final_filename = Path(output_folder) / filename.replace('.epub', '.m4b')
    chapters_txt_path = Path(output_folder) / "chapters.txt"
    print('Creating M4B file...')

    if cover_image:
        cover_file_path = Path(output_folder) / 'cover'
        with open(cover_file_path, 'wb') as f:
            f.write(cover_image)
        cover_image_args = [
            '-i', f'{cover_file_path}',
            '-map', '2:v',  # Map cover image
            '-disposition:v', 'attached_pic',  # Ensure cover is embedded
            '-c:v', 'copy',  # Keep cover unchanged
        ]
    else:
        cover_image_args = []

    proc = subprocess.run([
        'ffmpeg',
        '-y',  # Overwrite output
        
        '-i', f'{concat_file_path}',  # Input audio
        '-i', f'{chapters_txt_path}',  # Input chapters
        *cover_image_args,  # Cover image (if provided)

        '-map', '0:a',  # Map audio
        '-c:a', 'aac',  # Convert to AAC
        '-b:a', '64k',  # Reduce bitrate for smaller size

        '-map_metadata', '1', # Map metadata

        '-f', 'mp4',  # Output as M4B
        f'{final_filename}'  # Output file
    ])

    Path(concat_file_path).unlink()
    if proc.returncode == 0:
        print(f'{final_filename} created. Enjoy your audiobook.')
        print('Feel free to delete the intermediary .wav chapter files, the .m4b is all you need.')


def probe_duration(file_name):
    args = ['ffprobe', '-i', file_name, '-show_entries', 'format=duration', '-v', 'quiet', '-of', 'default=noprint_wrappers=1:nokey=1']
    proc = subprocess.run(args, capture_output=True, text=True, check=True)
    return float(proc.stdout.strip())


def create_index_file(title, creator, chapter_mp3_files, output_folder):
    with open(Path(output_folder) / "chapters.txt", "w", encoding="utf-8") as f:
        f.write(f";FFMETADATA1\ntitle={title}\nartist={creator}\n\n")
        start = 0
        i = 0
        for c in chapter_mp3_files:
            duration = probe_duration(c)
            end = start + (int)(duration * 1000)
            f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start}\nEND={end}\ntitle=Chapter {i}\n\n")
            i += 1
            start = end


def unmark_element(element, stream=None):
    """auxiliarry function to unmark markdown text"""
    if stream is None:
        stream = StringIO()
    if element.text:
        stream.write(element.text)
    for sub in element:
        unmark_element(sub, stream)
    if element.tail:
        stream.write(element.tail)
    return stream.getvalue()


def unmark(text):
    """Unmark markdown text"""
    markdown.Markdown.output_formats["plain"] = unmark_element  # patching Markdown
    __md = markdown.Markdown(output_format="plain")
    __md.stripTopLevelTags = False
    return __md.convert(text)


def apply_filters(text: str, filter_file_path: str = "audiblez/filter.txt") -> str:
    """
    Applies text replacements based on rules defined in the filter_file.
    Each rule is pattern1,pattern2|replacement.
    Lines starting with # are comments.
    """
    filter_file_name_default = "filter.txt"  # The actual filename

    # This inner function now correctly encapsulates rule processing from a stream.
    def _process_rules_from_stream(stream, stream_description_for_debug):
        nonlocal text  # Allow modification of 'text' from the apply_filters scope
        rules = []
        for i, line_content in enumerate(stream):
            line = line_content.strip()
            if not line or line.startswith('#'):
                continue  # Correctly inside a loop
            if '|' not in line:
                # Corrected f-string and variable name
                print(f"DEBUG: Warning: Malformed rule in filter file (line {i + 1} of '{stream_description_for_debug}', missing '|'): {line}")
                continue  # Correctly inside a loop
            patterns_str, replacement = line.split('|', 1)
            patterns = [p.strip() for p in patterns_str.split(',') if p.strip()]
            if not patterns:
                # Corrected f-string and variable name
                print(f"DEBUG: Warning: No patterns for replacement '{replacement}' (line {i + 1} of '{stream_description_for_debug}'): {line}")
                continue  # Correctly inside a loop
            rules.append({'patterns': patterns, 'replacement': replacement, 'line_num': i + 1})

        if not rules:
            print(f"DEBUG: No valid filter rules found in '{stream_description_for_debug}'.")
            return False  # No rules to apply

        # Corrected f-string and variable name
        print(f"DEBUG: Loaded {len(rules)} filter rules from '{stream_description_for_debug}'.")
        text_changed_overall = False
        for rule_item in rules: # Changed 'rule' to 'rule_item' to avoid conflict if 'rule' is a var name
            for pattern in rule_item['patterns']:
                if pattern in text:
                    new_text = text.replace(pattern, rule_item['replacement'])
                    if new_text != text:
                        # Corrected f-string and variable names
                        print(f"DEBUG: Applied rule (line {rule_item['line_num']} from '{stream_description_for_debug}'): Replacing '{pattern}' with '{rule_item['replacement']}'.")
                        text = new_text
                        text_changed_overall = True

        if not text_changed_overall:
            print(f"DEBUG: No changes made to the text by filtering with rules from '{stream_description_for_debug}'.")
        else:
            print(f"DEBUG: Text was changed by filtering with rules from '{stream_description_for_debug}'.")
        return text_changed_overall

    # Main logic for apply_filters
    # resolved_filter_path_for_debug is defined here for use in outer error messages
    resolved_filter_path_for_debug = filter_file_path

    try:
        direct_path_obj = Path(filter_file_path)

        # Heuristic: if filter_file_path is not the default "audiblez/filter.txt" or "filter.txt",
        # it's likely a user-specified custom path.
        is_custom_path = (filter_file_path != f"audiblez/{filter_file_name_default}" and
                          filter_file_path != filter_file_name_default)

        if is_custom_path and direct_path_obj.is_file():
            resolved_filter_path_for_debug = str(direct_path_obj)
            print(f"DEBUG: Attempting to use user-specified direct filter file path: '{resolved_filter_path_for_debug}'")
            if os.path.getsize(direct_path_obj) == 0:
                print(f"DEBUG: Direct filter file '{resolved_filter_path_for_debug}' is empty. Skipping.")
                return text
            with open(direct_path_obj, 'r', encoding='utf-8') as f_stream:
                _process_rules_from_stream(f_stream, resolved_filter_path_for_debug)
            return text
        elif is_custom_path and not direct_path_obj.exists():
            # User specified a custom path, but it doesn't exist. Don't fall back to package resource.
            print(f"DEBUG: User-specified filter file path '{filter_file_path}' not found. Skipping filtering.")
            return text

        # If not a custom path, or custom path wasn't a file, try package resources for the default filename.
        package_name = __name__.split('.')[0]
        if package_name == "__main__" or package_name == "core": # Handle if run as script or __name__ is just 'core'
            package_name = "audiblez"
            print(f"DEBUG: __name__ is '{__name__}', adjusted package_name to '{package_name}' for resources.")

        resolved_filter_path_for_debug = f"package resource '{package_name}/{filter_file_name_default}'"
        print(f"DEBUG: Attempting to load filter '{filter_file_name_default}' from package '{package_name}' via importlib.resources.")

        resource_found_and_processed = False
        try:
            if hasattr(importlib.resources, 'files') and hasattr(importlib.resources.files(package_name), 'joinpath'):
                resource_file_traversable = importlib.resources.files(package_name).joinpath(filter_file_name_default)
                if resource_file_traversable.is_file():
                    resolved_filter_path_for_debug = str(resource_file_traversable) # More specific path
                    try:
                        file_size = resource_file_traversable.stat().st_size
                        if file_size == 0:
                            print(f"DEBUG: Package resource filter file '{resolved_filter_path_for_debug}' is empty. Skipping.")
                            return text
                    except Exception:
                        print(f"DEBUG: Could not determine size of resource '{resolved_filter_path_for_debug}' beforehand via .stat().")

                    with resource_file_traversable.open('r', encoding='utf-8') as f_stream:
                        _process_rules_from_stream(f_stream, resolved_filter_path_for_debug)
                    resource_found_and_processed = True
                else:
                    print(f"DEBUG: Filter file '{filter_file_name_default}' not found as a file in package '{package_name}' using importlib.resources.files().")

            if not resource_found_and_processed and hasattr(importlib.resources, 'open_text'):
                # Fallback for older Pythons or if .files() didn't find it / wasn't suitable
                resolved_filter_path_for_debug = f"package resource '{package_name}/{filter_file_name_default}' (via open_text)"
                with importlib.resources.open_text(package_name, filter_file_name_default, encoding='utf-8') as f_stream:
                    _process_rules_from_stream(f_stream, resolved_filter_path_for_debug)
                resource_found_and_processed = True

            if not resource_found_and_processed:
                # This block might be reached if no suitable importlib.resources API was found or worked.
                # Last resort: try relative path for running from source root.
                # This is now less likely to be needed due to more robust importlib.resources handling.
                fallback_path_str = f"audiblez/{filter_file_name_default}"
                fallback_path_obj = Path(fallback_path_str)
                if fallback_path_obj.is_file():
                    resolved_filter_path_for_debug = fallback_path_str
                    print(f"DEBUG: Last resort: attempting to read '{resolved_filter_path_for_debug}' as a relative path.")
                    if os.path.getsize(fallback_path_obj) == 0:
                         print(f"DEBUG: Last resort filter file '{resolved_filter_path_for_debug}' is empty. Skipping.")
                         return text
                    with open(fallback_path_obj, 'r', encoding='utf-8') as f_stream:
                        _process_rules_from_stream(f_stream, resolved_filter_path_for_debug)
                    resource_found_and_processed = True
                else:
                     print(f"DEBUG: Filter file also not found at last resort relative path '{fallback_path_str}'.")

            if not resource_found_and_processed:
                 print(f"DEBUG: Filter file '{filter_file_name_default}' could not be loaded from any source. Skipping filtering.")

            return text # Text is modified in-place by _process_rules_from_stream via nonlocal

        except FileNotFoundError:
            print(f"DEBUG: Filter file '{filter_file_name_default}' not found in package '{package_name}' via importlib.resources. Skipping filtering.")
        except ModuleNotFoundError:
            print(f"DEBUG: Package '{package_name}' not found by importlib.resources. Skipping filtering.")
        except Exception as e_pkg:
            # Corrected f-string
            print(f"DEBUG: Error loading filter file from package '{package_name}' via importlib.resources: {e_pkg}")
            traceback.print_exc()

        return text

    except Exception as e_outer:
        # Corrected f-string, using the most up-to-date path string for debug
        print(f"ERROR: Outer error in apply_filters (attempted path: '{resolved_filter_path_for_debug}'): {e_outer}")


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
            # Common locations for ebook-convert within a Calibre installation directory
            possible_locations = [
                user_selected_calibre_dir / "ebook-convert",
                user_selected_calibre_dir / "Calibre2" / "ebook-convert" # Windows common structure
            ]
            if platform.system() == "Windows":
                possible_locations = [
                    user_selected_calibre_dir / "ebook-convert.exe",
                    user_selected_calibre_dir / "Calibre2" / "ebook-convert.exe"
                ]

            found_path = None
            for loc in possible_locations:
                debug_exe_name = "calibre-debug.exe" if platform.system() == "Windows" else "calibre-debug"
                calibre_parent_dir = loc.parent
                if loc.exists() and loc.is_file() and (calibre_parent_dir / debug_exe_name).exists():
                    found_path = str(loc)
                    print(f"User selected Calibre directory. Validated ebook-convert at: {found_path}")
                    save_user_setting('calibre_ebook_convert_path', found_path)
                    return found_path

            if not found_path:
                 # Check if ebook-convert is directly in the selected folder, even if calibre-debug isn't (less strict)
                potential_exe = user_selected_calibre_dir / ("ebook-convert.exe" if platform.system() == "Windows" else "ebook-convert")
                if potential_exe.exists() and potential_exe.is_file():
                    print(f"User selected Calibre directory. Found ebook-convert at: {potential_exe}, but validation with calibre-debug failed. Using it anyway.")
                    save_user_setting('calibre_ebook_convert_path', str(potential_exe))
                    return str(potential_exe)

                print(f"ebook-convert or calibre-debug not found in the selected directory or common subdirectories: {user_selected_calibre_dir_str}")
                # wx.CallAfter(wx.MessageBox, f"Could not find 'ebook-convert' and 'calibre-debug' in the selected directory:\n{user_selected_calibre_dir_str}\nPlease ensure you select the main Calibre application folder.", "Calibre Verification Failed", wx.OK | wx.ICON_ERROR)
                # The UI callback should handle user feedback for this case.
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
        str | None: Path to the generated HTML file if successful, None otherwise.
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
    # Define a predictable output HTML filename within the output_html_dir
    output_html_file = output_dir / "output.html"

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
        str(output_html_file),
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
            print(f"Calibre conversion successful. Output HTML: {output_html_file}")
            if output_html_file.exists():
                return str(output_html_file)
            else:
                # This case should be rare if returncode is 0, but good to check.
                print(f"ERROR: Calibre reported success, but output file '{output_html_file}' not found.")
                print(f"Calibre stdout:\n{result.stdout}")
                print(f"Calibre stderr:\n{result.stderr}")
                return None
        else:
            print(f"ERROR: Calibre ebook-convert failed with return code {result.returncode}")
            print(f"Calibre stdout:\n{result.stdout}")
            print(f"Calibre stderr:\n{result.stderr}")
            # Potentially clean up output_html_file if it was created but is incomplete/invalid
            if output_html_file.exists():
                try:
                    output_html_file.unlink()
                except OSError as e:
                    print(f"Warning: Could not delete incomplete output file '{output_html_file}': {e}")
            return None

    except FileNotFoundError:
        # This would happen if ebook_convert_exe path was somehow invalid despite earlier checks.
        print(f"ERROR: ebook-convert executable not found at '{ebook_convert_exe}'. This shouldn't happen if get_calibre_ebook_convert_path worked.")
        return None
    except subprocess.TimeoutExpired:
        print("ERROR: Calibre conversion timed out.")
        return None
    except Exception as e:
        print(f"ERROR: An unexpected error occurred during Calibre conversion: {e}")
        traceback.print_exc()
        return None


def extract_chapters_from_calibre_html(html_file_path: str) -> list:
    """
    Parses an HTML file (presumably generated by Calibre) and extracts chapters.
    Chapters are identified by h1 or h2 tags.
    """
    chapters = []
    current_chapter_title = "Introduction" # Default for content before the first heading
    current_chapter_content = []
    chapter_index_counter = 0

    try:
        with open(html_file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser') # Using html.parser, can switch to lxml if needed

        # Try to get the main book title from <title> tag or first prominent <h1>
        book_title_tag = soup.find('title')
        book_overall_title = book_title_tag.string.strip() if book_title_tag else "Untitled Book"

        # Heuristic: Content often resides in <body> or a main <div role="main"> or <article>
        # For simplicity, we'll process all relevant tags within body.
        content_body = soup.body if soup.body else soup

        if not content_body:
            print(f"Warning: Could not find <body> or main content in {html_file_path}. No chapters extracted.")
            return []

        # Relevant tags for content extraction, similar to EPUB processing
        # but chapters are delimited by h1/h2 in the flow of these tags.
        content_tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'div'] # Added div for more general content blocks

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

        for element in content_body.find_all(True, recursive=True): # Iterate over all tags
            # Chapter demarcation: h1 or h2
            if element.name in ['h1', 'h2']:
                # If there's existing content, save it as the previous chapter
                if current_chapter_content:
                    text_for_prev_chapter = '\n'.join(current_chapter_content).strip()
                    if text_for_prev_chapter: # Only add if there's actual text
                        chapters.append(create_chapter_object(current_chapter_title, text_for_prev_chapter, chapter_index_counter))
                        chapter_index_counter += 1
                    current_chapter_content = [] # Reset for the new chapter

                new_chapter_title = element.get_text(separator=' ', strip=True)
                if new_chapter_title: # Only update if title is non-empty
                    current_chapter_title = new_chapter_title
                # Don't add the heading itself to chapter content if it's used as title
                continue # Move to next element

            # Content extraction from allowed tags
            if element.name in content_tags:
                # Heuristic: Avoid extracting text from divs that are just containers for other block elements
                # or from divs that seem like navigation, headers, footers. This is complex.
                # A simple check: if a div has other block elements as direct children, maybe skip its direct text.
                # For now, keep it simple: extract text from all specified content_tags.
                # Consider more specific class/id checks if Calibre output is consistent.

                text = element.get_text(separator=' ', strip=True)
                if text:
                    # Basic sentence-ending punctuation for consistency, if not already present
                    if not text.endswith(('.', '!', '?', ':', ';')):
                        text += '.'
                    current_chapter_content.append(text)

        # Add the last accumulated chapter
        if current_chapter_content:
            text_for_last_chapter = '\n'.join(current_chapter_content).strip()
            if text_for_last_chapter:
                chapters.append(create_chapter_object(current_chapter_title, text_for_last_chapter, chapter_index_counter))

        # If no chapters were found (e.g. no h1/h2 tags), treat the whole content as one chapter
        if not chapters and content_body:
            all_text = content_body.get_text(separator='\n', strip=True)
            if all_text:
                chapters.append(create_chapter_object(book_overall_title or "Full Text", all_text, 0))

        print(f"Extracted {len(chapters)} chapters from Calibre HTML output.")
        # For debugging, print chapter titles and lengths
        # for chap in chapters:
        #    print(f"  - Title: {chap.short_name}, Length: {len(chap.extracted_text)}")

        return chapters

    except FileNotFoundError:
        print(f"ERROR: HTML file not found for chapter extraction: {html_file_path}")
        return []
    except Exception as e:
        print(f"ERROR: Failed to parse or extract chapters from HTML file '{html_file_path}': {e}")
        traceback.print_exc()
        return []

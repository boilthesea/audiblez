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
         max_chapters=None, max_sentences=None, selected_chapters=None, post_event=None,
         calibre_metadata: dict | None = None, calibre_cover_image_path: str | None = None,
         m4b_assembly_method: str = 'original'):
    if post_event: post_event('CORE_STARTED')
    load_spacy()
    if output_folder != '.':
        Path(output_folder).mkdir(parents=True, exist_ok=True)

    filename = Path(file_path).name # Original filename, used for output naming
    title = "Untitled Book"
    creator = "Unknown Author"
    cover_image = b""
    document_chapters = [] # Will be populated by EPUB or pre-set by Calibre workflow

    # Determine if this is a Calibre workflow or EPUB workflow for metadata/cover
    is_calibre_workflow = bool(calibre_metadata)

    if is_calibre_workflow:
        print("Processing with Calibre-derived data.")
        title = calibre_metadata.get('title', title)
        creator = calibre_metadata.get('creator', creator)
        # Language from Calibre metadata could be used by KPipeline if needed, but KPipeline sets lang by voice.
        # For now, primarily for M4B metadata.

        if calibre_cover_image_path and Path(calibre_cover_image_path).exists():
            try:
                with open(calibre_cover_image_path, 'rb') as f_cover:
                    cover_image = f_cover.read()
                print(f"Loaded cover image from Calibre path: {calibre_cover_image_path}")
            except Exception as e:
                print(f"Error reading Calibre cover image from '{calibre_cover_image_path}': {e}")
                cover_image = b""

        # For Calibre workflow, `selected_chapters` are already provided and are SimpleNamespace objects.
        # `document_chapters` is not strictly needed if `selected_chapters` is always given.
        # However, `print_selected_chapters` expects `document_chapters` for context.
        # If `selected_chapters` is what we operate on, `document_chapters` can be set to it.
        if selected_chapters:
            document_chapters = selected_chapters # Use the pre-processed chapters
        else:
            print("Warning: Calibre workflow initiated but no selected_chapters provided to core.main.")
            # This case should ideally not happen if UI passes chapters.
            # If it does, we can't proceed without chapters.
            if post_event: post_event('CORE_FINISHED', error_message="No chapters provided for Calibre book.")
            return


    else: # Standard EPUB workflow
        print("Processing with EPUB data.")
        book = epub.read_epub(file_path)
        meta_title_dc = book.get_metadata('DC', 'title')
        title = meta_title_dc[0][0] if meta_title_dc else title
        meta_creator_dc = book.get_metadata('DC', 'creator')
        creator = meta_creator_dc[0][0] if meta_creator_dc else creator

        cover_maybe = find_cover(book)
        cover_image = cover_maybe.get_content() if cover_maybe else b""
        if cover_maybe:
            print(f'Found cover image {cover_maybe.file_name} in {cover_maybe.media_type} format')

        document_chapters = find_document_chapters_and_extract_texts(book)
        # Chapter selection logic for EPUBs remains
        if not selected_chapters: # If UI didn't pre-select
            if pick_manually is True: # CLI option
                selected_chapters = pick_chapters(document_chapters)
            else: # Default chapter finding for EPUB
                selected_chapters = find_good_chapters(document_chapters)

    if not selected_chapters: # Catch-all if no chapters ended up selected
        print("Error: No chapters selected or found for processing.")
        if post_event: post_event('CORE_FINISHED', error_message="No chapters selected.")
        return
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
        # Use chapter.title if get_name() is not available (for ChapterForCore objects from queue or Calibre)
        if hasattr(chapter, 'get_name') and callable(chapter.get_name): # For EPUB chapters
            original_name = chapter.get_name()
        elif hasattr(chapter, 'title') and chapter.title: # For Calibre SimpleNamespace chapters or queued chapters
            original_name = chapter.title
        else:
            original_name = f"chapter_{i}" # Fallback if neither is present

        # Sanitize original_name for use in filename
        # Replace common problematic characters, limit length
        safe_original_name = re.sub(r'[^\w\s-]', '', original_name) # Keep word chars, whitespace, hyphens
        safe_original_name = re.sub(r'\s+', '_', safe_original_name).strip('_') # Replace whitespace with underscore
        safe_original_name = safe_original_name[:50] # Limit length to avoid overly long filenames

        # Determine output filename based on original input filename's stem
        base_filename_stem = Path(filename).stem # e.g., "mybook" from "mybook.epub" or "mybook.mobi"

        chapter_wav_path = Path(output_folder) / f'{base_filename_stem}_chapter_{i}_{voice}_{safe_original_name}.wav'
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
        # Use the original input filename (which includes original extension) for M4B naming logic
        create_index_file(title, creator, chapter_wav_files, output_folder)
        create_m4b(chapter_wav_files, Path(file_path).name, cover_image, output_folder, m4b_assembly_method)
        if post_event: post_event('CORE_FINISHED')
    else:
        if post_event: post_event('CORE_FINISHED', error_message="ffmpeg not found, M4B not created.")


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
            # Use floating point division for more accurate progress percentage
            if stats.total_chars > 0:
                stats.progress = int((stats.processed_chars / stats.total_chars) * 100)
            else:
                stats.progress = 100
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


def concat_wavs_with_ffmpeg_crispy(chapter_files: list[Path], output_folder: str, temp_concat_filename: str) -> Path:
    """
    Concatenates WAV files into a single temporary WAV file using relative paths.
    This is the 'Extra Crispy' method, designed to be more robust on Windows.
    """
    output_path = Path(output_folder)
    wav_list_filename = "crispy_wav_list.txt"
    wav_list_path = output_path / wav_list_filename
    temp_concat_wav_path = output_path / temp_concat_filename

    try:
        with open(wav_list_path, 'w', encoding='utf-8') as f:
            for wav_file_abs in chapter_files:
                # Use relative paths in the list file
                wav_file_relative = wav_file_abs.relative_to(output_path)
                # Escape single quotes for ffmpeg concat demuxer, which uses a shell-like syntax.
                # A single quote is escaped by ending the string, adding an escaped quote, and starting a new string.
                # e.g., "it's" becomes "it'\''s"
                safe_path = wav_file_relative.as_posix().replace("'", r"'\''")
                f.write(f"file '{safe_path}'\n")

        command = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', wav_list_filename,
            '-c', 'copy', temp_concat_filename
        ]

        print(f"Executing 'Extra Crispy' WAV concatenation in '{output_folder}': {' '.join(command)}")
        # Execute ffmpeg with cwd=output_folder to use relative paths
        proc = subprocess.run(command, cwd=output_folder, capture_output=True, text=True, check=True)
        print("Concatenation successful.")

    except subprocess.CalledProcessError as e:
        print(f"ERROR: 'Extra Crispy' WAV concatenation failed with exit code {e.returncode}.")
        print(f"ffmpeg stdout:\n{e.stdout}")
        print(f"ffmpeg stderr:\n{e.stderr}")
        raise  # Re-raise the exception to be caught by create_m4b
    except Exception as e:
        print(f"An unexpected error occurred during 'Extra Crispy' concatenation: {e}")
        raise
    finally:
        # Clean up the list file
        if wav_list_path.exists():
            try:
                wav_list_path.unlink()
            except OSError as e:
                print(f"Warning: Could not delete temp list file '{wav_list_path}': {e}")

    return temp_concat_wav_path


def create_m4b(chapter_files: list[str], original_input_filename: str, cover_image: bytes | None, output_folder: str, assembly_method: str = 'original'):
    if not chapter_files:
        print("No chapter files to process for M4B creation.")
        return

    concat_file_path = None
    temp_m4b_filepath = None
    temp_cover_file_path = None

    try:
        if assembly_method == 'crispy':
            print("Using 'Extra Crispy' M4B assembly method.")
            chapter_paths = [Path(f) for f in chapter_files]
            concat_file_path = concat_wavs_with_ffmpeg_crispy(chapter_paths, output_folder, "temp_concat.wav")
        else:
            print("Using 'Original' M4B assembly method.")
            concat_file_path = concat_wavs_with_ffmpeg(chapter_files, output_folder, original_input_filename)

        if not concat_file_path or not concat_file_path.exists():
            raise RuntimeError(f"Concatenated audio file was not created: {concat_file_path}")

        output_path = Path(output_folder)
        final_m4b_basename = Path(original_input_filename).stem + ".m4b"
        final_filename = output_path / final_m4b_basename
        temp_m4b_basename = "temp_output_for_m4b.m4b"
        temp_m4b_filepath = output_path / temp_m4b_basename
        chapters_txt_path = output_path / "chapters.txt"
        print(f"Creating M4B file: {final_filename}")

        ffmpeg_command = [
            'ffmpeg', '-y',
            '-i', str(concat_file_path.relative_to(output_path).as_posix()),
            '-i', str(chapters_txt_path.relative_to(output_path).as_posix()),
        ]
        cover_input_index = 2

        if cover_image:
            temp_cover_filename_in_output = "temp_cover_for_m4b.jpg"
            temp_cover_file_path = output_path / temp_cover_filename_in_output
            try:
                with open(temp_cover_file_path, 'wb') as f_cover:
                    f_cover.write(cover_image)
                ffmpeg_command.extend(['-i', str(temp_cover_file_path.relative_to(output_path).as_posix())])
            except Exception as e:
                print(f"Warning: Could not write temporary cover file: {e}. Proceeding without cover.")
                temp_cover_file_path = None
                cover_image = None

        ffmpeg_command.extend(['-map', '0:a', '-map_metadata', '1'])

        if cover_image and temp_cover_file_path:
            ffmpeg_command.extend([
                '-map', f'{cover_input_index}:v',
                '-disposition:v', 'attached_pic',
                '-c:v', 'mjpeg',
            ])

        ffmpeg_command.extend([
            '-c:a', 'aac', '-b:a', '64k', '-f', 'mp4',
            str(temp_m4b_filepath.relative_to(output_path).as_posix())
        ])

        print(f"Executing ffmpeg command in '{output_folder}': {' '.join(ffmpeg_command)}")
        proc = subprocess.run(ffmpeg_command, cwd=output_folder, capture_output=True, text=True, check=True)

        if temp_m4b_filepath.exists():
            if final_filename.exists():
                final_filename.unlink()
            temp_m4b_filepath.rename(final_filename)
            print(f"'{final_filename}' created successfully. Enjoy your audiobook.")
            print("Feel free to delete the intermediary .wav chapter files; the .m4b is all you need.")
        else:
            raise RuntimeError(f"ffmpeg seemed to succeed but the output file '{temp_m4b_filepath}' was not found.")

    except (subprocess.CalledProcessError, RuntimeError, FileNotFoundError) as e:
        print(f"ERROR: M4B creation failed. Reason: {e}")
        if isinstance(e, subprocess.CalledProcessError):
            print(f"ffmpeg stdout:\n{e.stdout}")
            print(f"ffmpeg stderr:\n{e.stderr}")
    finally:
        print("Cleaning up temporary files...")
        if concat_file_path and concat_file_path.exists():
            try:
                concat_file_path.unlink()
            except OSError as e:
                print(f"Warning: Could not delete temp concat file '{concat_file_path}': {e}")
        if temp_cover_file_path and temp_cover_file_path.exists():
            try:
                temp_cover_file_path.unlink()
            except OSError as e:
                print(f"Warning: Could not delete temporary cover file '{temp_cover_file_path}': {e}")
        if temp_m4b_filepath and temp_m4b_filepath.exists():
            try:
                temp_m4b_filepath.unlink()
            except OSError as e:
                print(f"Warning: Could not delete temporary m4b file '{temp_m4b_filepath}': {e}")


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
        for rule_item in rules:  # Changed 'rule' to 'rule_item' to avoid conflict if 'rule' is a var name
            for pattern in rule_item['patterns']:
                # Use negative lookarounds to ensure we match whole words/abbreviations only.
                # This prevents matching a filter pattern inside another word (e.g. "rd." in "word.").
                regex_pattern = r'(?<!\w)' + re.escape(pattern) + r'(?!\w)'
                new_text, count = re.subn(regex_pattern, rule_item['replacement'], text, flags=re.IGNORECASE)
                if count > 0:
                    # Corrected f-string and variable names
                    print(f"DEBUG: Applied rule (line {rule_item['line_num']} from '{stream_description_for_debug}'): Replacing '{pattern}' with '{rule_item['replacement']}' ({count} occurrences).")
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




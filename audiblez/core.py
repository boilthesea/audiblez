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
from ebooklib import epub
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
import audiblez.engines as engines
from audiblez.epub_handler import find_cover, find_document_chapters_and_extract_texts
from pick import pick
import importlib.resources
import markdown

from audiblez.database import load_user_setting

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


def _get_chapter_text(c):
    """Helper to safely get text from either a dict or an object."""
    if isinstance(c, dict):
        return c.get('extracted_text', '')
    return getattr(c, 'extracted_text', '')

def _get_chapter_title(c, fallback="chapter"):
    """Helper to safely get title from either a dict or an object."""
    if isinstance(c, dict):
        return c.get('title') or fallback
    if hasattr(c, 'get_name') and callable(c.get_name):
        return c.get_name()
    return getattr(c, 'title', fallback)

def main(file_path, voice, pick_manually, speed, output_folder='.',
         max_chapters=None, max_sentences=None, selected_chapters=None, post_event=None,
         calibre_metadata: dict | None = None, calibre_cover_image_path: str | None = None,
         m4b_assembly_method: str = 'original', engine_device=None, custom_rate=None,
         tts_model='kokoro', reference_wav=None, num_steps=4, max_chunk_len=900,
         guidance_scale=3.0, t_shift=0.5, rms=0.1, duration=5.0, return_smooth=False, seed=None):


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

        if calibre_cover_image_path and Path(calibre_cover_image_path).exists():
            try:
                with open(calibre_cover_image_path, 'rb') as f_cover:
                    cover_image = f_cover.read()
                print(f"Loaded cover image from Calibre path: {calibre_cover_image_path}")
            except Exception as e:
                print(f"Error reading Calibre cover image from '{calibre_cover_image_path}': {e}")
                cover_image = b""

        if selected_chapters:
            document_chapters = selected_chapters # Use the pre-processed chapters
        else:
            print("Warning: Calibre workflow initiated but no selected_chapters provided to core.main.")
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
    texts = [_get_chapter_text(c) for c in selected_chapters]

    has_ffmpeg = shutil.which('ffmpeg') is not None
    if not has_ffmpeg:
        print('\033[91m' + 'ffmpeg not found. Please install ffmpeg to create mp3 and m4b audiobook files.' + '\033[0m')

    # Determine chars_per_sec for stats. Try parameter first, then database, then default.
    default_chars_per_sec = 500 if torch.cuda.is_available() else 50
    current_chars_per_sec = default_chars_per_sec

    # Use explicitly passed custom_rate if provided
    rate_to_use = custom_rate
    if rate_to_use is None:
        # Fallback to database if not passed (legacy/other UIs)
        rate_to_use = load_user_setting('custom_rate')

    if rate_to_use is not None:
        try:
            rate_val = int(rate_to_use)
            if rate_val > 0:
                current_chars_per_sec = rate_val
                print(f"Using characters-per-second rate: {current_chars_per_sec}")
            else:
                print(f"Invalid custom rate ({rate_to_use}), using default: {default_chars_per_sec}")
        except ValueError:
            print(f"Could not parse custom rate ('{rate_to_use}'), using default: {default_chars_per_sec}")
    else:
        print(f"No custom rate provided, using default: {default_chars_per_sec}")


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
    
    # Initialize the selected engine
    active_engine = engines.get_engine(tts_model, engine_device)
    engine_kwargs = {
        'voice': voice,
        'speed': speed,
        'reference_wav': reference_wav,
        'num_steps': num_steps,
        'max_chunk_len': max_chunk_len,
        'guidance_scale': guidance_scale,
        't_shift': t_shift,
        'rms': rms,
        'duration': duration,
        'return_smooth': return_smooth,
        'seed': seed
    }

    chapter_wav_files = []
    skipped_chapters = []
    carry_over_text = ""
    
    # Calculate the total number of chapters to process
    chapters_to_process = selected_chapters
    if max_chapters:
        chapters_to_process = selected_chapters[:max_chapters]
    
    total_to_process = len(chapters_to_process)

    for i, chapter in enumerate(chapters_to_process, start=1):
        # Access attributes safely as chapter might be a dict (from CTK UI) or an object (EpubHtml/SimpleNamespace)
        text = _get_chapter_text(chapter)
        original_name = _get_chapter_title(chapter, fallback=f"chapter_{i}")
        chapter_index = chapter.get('chapter_index', i - 1) if isinstance(chapter, dict) else getattr(chapter, 'chapter_index', i - 1)

        # Sanitize original_name for use in filename
        # Replace common problematic characters, limit length
        safe_original_name = re.sub(r'[^\w\s-]', '', original_name) # Keep word chars, whitespace, hyphens
        safe_original_name = re.sub(r'\s+', '_', safe_original_name).strip('_') # Replace whitespace with underscore
        safe_original_name = safe_original_name[:50] # Limit length to avoid overly long filenames

        # Determine output filename based on original input filename's stem
        base_filename_stem = Path(filename).stem # e.g., "mybook" from "mybook.epub" or "mybook.mobi"

        chapter_wav_path = Path(output_folder) / f'{base_filename_stem}_chapter_{i}_{voice}_{safe_original_name}.wav'
        chapter_wav_files.append(chapter_wav_path)

        if i == 1:
            # add intro text
            text = f'{title} – {creator}.\n\n' + text

        # Apply filters to the chapter text
        filtered_text = apply_filters(text)
        
        # Prepend carried over text if any
        if carry_over_text:
            filtered_text = carry_over_text + "\n\n" + filtered_text
            carry_over_text = ""

        # Carry-over logic: if chapter is too small, carry it over to the next one
        # unless it's the very last chapter.
        is_last_chapter = (i == total_to_process)
        if len(filtered_text.strip()) < 100 and not is_last_chapter:
            print(f'Chapter {i} ("{original_name}") is very short ({len(filtered_text)} chars). Carrying over to next chapter.')
            carry_over_text = filtered_text
            chapter_wav_files.remove(chapter_wav_path)
            if post_event:
                post_event('CORE_CHAPTER_FINISHED', chapter_index=chapter_index)
            continue
            
        # For the last chapter, if it's still too short, add a friendly buffer
        if is_last_chapter and len(filtered_text.strip()) < 100:
            print(f'Final chapter {i} is short. Adding concluding buffer.')
            filtered_text += "\n\nThe End, thank you for listening."

        if Path(chapter_wav_path).exists():
            print(f'File for chapter {i} already exists. Skipping')
            stats.processed_chars += len(text) # Original text length for skip consistency
            if post_event:
                post_event('CORE_CHAPTER_FINISHED', chapter_index=chapter_index)
            continue

        if len(filtered_text.strip()) < 10:
            print(f'Skipping empty chapter {i} (after filtering)')
            chapter_wav_files.remove(chapter_wav_path)
            continue

        start_time = time.time()
        if post_event: post_event('CORE_CHAPTER_STARTED', chapter_index=chapter_index)
        
        # Synthesis using the engine interface
        try:
            audio_data, current_sample_rate = active_engine.generate(filtered_text, **engine_kwargs)
            
            if audio_data.size > 0:
                soundfile.write(chapter_wav_path, audio_data, current_sample_rate)
                end_time = time.time()
                delta_seconds = end_time - start_time
                chars_per_sec = len(text) / delta_seconds
                print('Chapter written to', chapter_wav_path)
                
                # Progress tracking
                if stats:
                    stats.processed_chars += len(filtered_text)
                    if stats.total_chars > 0:
                        stats.progress = int((stats.processed_chars / stats.total_chars) * 100)
                    else:
                        stats.progress = 100
                    stats.eta = strfdelta((stats.total_chars - stats.processed_chars) / stats.chars_per_sec)
                    if post_event: post_event('CORE_PROGRESS', stats=stats)
                    print(f'Estimated time remaining: {stats.eta}')
                    print('Progress:', f'{stats.progress}%\n')

                if post_event: post_event('CORE_CHAPTER_FINISHED', chapter_index=chapter_index)
                print(f'Chapter {i} read in {delta_seconds:.2f} seconds ({chars_per_sec:.0f} characters per second)')
            else:
                print(f'Warning: No audio generated for chapter {i}')
                skipped_chapters.append((i, original_name, "No audio generated"))
                if chapter_wav_path in chapter_wav_files:
                    chapter_wav_files.remove(chapter_wav_path)
        except Exception as e:
            print(f'Error generating audio for chapter {i}: {e}')
            skipped_chapters.append((i, original_name, str(e)))
            if chapter_wav_path in chapter_wav_files:
                chapter_wav_files.remove(chapter_wav_path)

    if skipped_chapters:
        print("\n" + "="*60)
        print("SUMMARY OF SKIPPED CHAPTERS")
        print("-"*60)
        for idx, name, err in skipped_chapters:
            print(f"Chapter {idx:3} | {name[:30]:30} | {err}")
        print("="*60 + "\n")

    if has_ffmpeg:
        create_index_file(title, creator, chapter_wav_files, output_folder)
        create_m4b(chapter_wav_files, Path(file_path).name, cover_image, output_folder, m4b_assembly_method)
        if post_event: post_event('CORE_FINISHED', skipped_chapters=skipped_chapters)
    else:
        if post_event: post_event('CORE_FINISHED', error_message="ffmpeg not found, M4B not created.", skipped_chapters=skipped_chapters)


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


def print_selected_chapters(document_chapters, chapters):
    ok = 'X' if platform.system() == 'Windows' else '✅'
    print(tabulate([
        [i, _get_chapter_title(c), len(_get_chapter_text(c)), ok if c in chapters else '', chapter_beginning_one_liner(c)]
        for i, c in enumerate(document_chapters, start=1)
    ], headers=['#', 'Chapter', 'Text Length', 'Selected', 'First words']))


def gen_text(text, voice='af_heart', output_file='text.wav', speed=1, play=False, engine_device=None,
             tts_model='kokoro', reference_wav=None, num_steps=4, max_chunk_len=900,
             guidance_scale=3.0, t_shift=0.5, rms=0.1, duration=5.0, return_smooth=False, seed=None):
    load_spacy()
    set_espeak_library()
    active_engine = engines.get_engine(tts_model, engine_device)
    engine_kwargs = {
        'voice': voice,
        'speed': speed,
        'reference_wav': reference_wav,
        'num_steps': num_steps,
        'max_chunk_len': max_chunk_len,
        'guidance_scale': guidance_scale,
        't_shift': t_shift,
        'rms': rms,
        'duration': duration,
        'return_smooth': return_smooth,
        'seed': seed
    }
    audio_data, current_sample_rate = active_engine.generate(text, **engine_kwargs)
    if audio_data.size > 0:
        soundfile.write(output_file, audio_data, current_sample_rate)
        if play:
            subprocess.run(['ffplay', '-autoexit', '-nodisp', output_file])


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


def is_chapter(c):
    name = _get_chapter_title(c).lower()
    has_min_len = len(_get_chapter_text(c)) > 100
    title_looks_like_chapter = bool(
        'chapter' in name.lower()
        or re.search(r'part_?\d{1,3}', name)
        or re.search(r'split_?\d{1,3}', name)
        or re.search(r'ch_?\d{1,3}', name)
        or re.search(r'chap_?\d{1,3}', name)
    )
    return has_min_len and title_looks_like_chapter


def chapter_beginning_one_liner(c, chars=20):
    text = _get_chapter_text(c)
    s = text[:chars].strip().replace('\n', ' ').replace('\r', ' ')
    return s + '…' if len(s) > 0 else ''


def find_good_chapters(document_chapters):
    chapters = [c for c in document_chapters if c.get_type() == ebooklib.ITEM_DOCUMENT and is_chapter(c)]
    if len(chapters) == 0:
        print('Not easy to recognize the chapters, defaulting to all non-empty documents.')
        chapters = [c for c in document_chapters if c.get_type() == ebooklib.ITEM_DOCUMENT and len(_get_chapter_text(c)) > 10]
    return chapters


def pick_chapters(chapters):
    # Display the document name, the length and first 50 characters of the text
    chapters_by_names = {
        f'{_get_chapter_title(c)}\t({len(_get_chapter_text(c))} chars)\t[{chapter_beginning_one_liner(c, 50)}]': c
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
    output_path = Path(output_folder)
    wav_list_filename = "crispy_wav_list.txt"
    wav_list_path = output_path / wav_list_filename
    temp_concat_wav_path = output_path / temp_concat_filename

    try:
        with open(wav_list_path, 'w', encoding='utf-8') as f:
            for wav_file_abs in chapter_files:
                wav_file_relative = wav_file_abs.relative_to(output_path)
                safe_path = wav_file_relative.as_posix().replace("'", r"'\''")
                f.write(f"file '{safe_path}'\n")

        command = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', wav_list_filename,
            '-c', 'copy', temp_concat_filename
        ]

        print(f"Executing 'Extra Crispy' WAV concatenation in '{output_folder}': {' '.join(command)}")
        proc = subprocess.run(command, cwd=output_folder, capture_output=True, text=True, check=True)
        print("Concatenation successful.")

    except subprocess.CalledProcessError as e:
        print(f"ERROR: 'Extra Crispy' WAV concatenation failed with exit code {e.returncode}.")
        raise
    except Exception as e:
        print(f"An unexpected error occurred during 'Extra Crispy' concatenation: {e}")
        raise
    finally:
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
        try:
            proc = subprocess.run(ffmpeg_command, cwd=output_folder, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            if cover_image:
                print(f"Warning: M4B assembly with cover image failed. Retrying without cover. Reason: {e}")
                ffmpeg_command_no_cover = [
                    'ffmpeg', '-y',
                    '-i', str(concat_file_path.relative_to(output_path).as_posix()),
                    '-i', str(chapters_txt_path.relative_to(output_path).as_posix()),
                    '-map', '0:a', '-map_metadata', '1',
                    '-c:a', 'aac', '-b:a', '64k', '-f', 'mp4',
                    str(temp_m4b_filepath.relative_to(output_path).as_posix())
                ]
                proc = subprocess.run(ffmpeg_command_no_cover, cwd=output_folder, capture_output=True, text=True, check=True)
            else:
                raise

        if temp_m4b_filepath.exists():
            if final_filename.exists():
                final_filename.unlink()
            temp_m4b_filepath.rename(final_filename)
            print(f"'{final_filename}' created successfully. Enjoy your audiobook.")
        else:
            raise RuntimeError(f"ffmpeg seemed to succeed but the output file '{temp_m4b_filepath}' was not found.")

    except (subprocess.CalledProcessError, RuntimeError, FileNotFoundError) as e:
        print(f"ERROR: M4B creation failed. Reason: {e}")
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
    markdown.Markdown.output_formats["plain"] = unmark_element
    __md = markdown.Markdown(output_format="plain")
    __md.stripTopLevelTags = False
    return __md.convert(text)


def apply_filters(text: str, filter_file_path: str = "audiblez/filter.txt") -> str:
    filter_file_name_default = "filter.txt"

    def _process_rules_from_stream(stream, stream_description_for_debug):
        nonlocal text
        rules = []
        for i, line_content in enumerate(stream):
            line = line_content.strip()
            if not line or line.startswith('#'):
                continue
            if '|' not in line:
                print(f"DEBUG: Warning: Malformed rule in filter file (line {i + 1} of '{stream_description_for_debug}', missing '|'): {line}")
                continue
            patterns_str, replacement = line.split('|', 1)
            patterns = [p.strip() for p in patterns_str.split(',') if p.strip()]
            if not patterns:
                print(f"DEBUG: Warning: No patterns for replacement '{replacement}' (line {i + 1} of '{stream_description_for_debug}'): {line}")
                continue
            rules.append({'patterns': patterns, 'replacement': replacement, 'line_num': i + 1})

        if not rules:
            return False

        for rule_item in rules:
            for pattern in rule_item['patterns']:
                if "*" in pattern:
                    regex_pattern = re.escape(pattern).replace(r'\*', r'\w*')
                else:
                    regex_pattern = r'(?<!\w)' + re.escape(pattern) + r'(?!\w)'

                new_text, count = re.subn(regex_pattern, rule_item['replacement'], text, flags=re.IGNORECASE)
                if count > 0:
                    text = new_text
        return True

    try:
        direct_path_obj = Path(filter_file_path)
        is_custom_path = (filter_file_path != f"audiblez/{filter_file_name_default}" and
                          filter_file_path != filter_file_name_default)

        if is_custom_path and direct_path_obj.is_file():
            with open(direct_path_obj, 'r', encoding='utf-8') as f_stream:
                _process_rules_from_stream(f_stream, str(direct_path_obj))
            return text
        elif is_custom_path and not direct_path_obj.exists():
            return text

        package_name = "audiblez"
        resource_found_and_processed = False
        try:
            if hasattr(importlib.resources, 'files'):
                resource_file_traversable = importlib.resources.files(package_name).joinpath(filter_file_name_default)
                if resource_file_traversable.is_file():
                    with resource_file_traversable.open('r', encoding='utf-8') as f_stream:
                        _process_rules_from_stream(f_stream, str(resource_file_traversable))
                    resource_found_and_processed = True

            if not resource_found_and_processed and hasattr(importlib.resources, 'open_text'):
                with importlib.resources.open_text(package_name, filter_file_name_default, encoding='utf-8') as f_stream:
                    _process_rules_from_stream(f_stream, f"{package_name}/{filter_file_name_default}")
                resource_found_and_processed = True

            if not resource_found_and_processed:
                fallback_path_str = f"audiblez/{filter_file_name_default}"
                fallback_path_obj = Path(fallback_path_str)
                if fallback_path_obj.is_file():
                    with open(fallback_path_obj, 'r', encoding='utf-8') as f_stream:
                        _process_rules_from_stream(f_stream, fallback_path_str)
                    resource_found_and_processed = True

            return text

        except Exception:
            return text

    except Exception:
        return text

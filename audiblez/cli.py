# -*- coding: utf-8 -*-
import argparse
import sys
import torch

from audiblez.voices import voices, available_voices_str
from audiblez.database import load_all_user_settings

def cli_main():
    voices_str = ', '.join(voices)
    epilog = ('example:\n' +
              '  audiblez book.epub -l en-us -v af_sky\n\n' +
              'to run GUI just run:\n'
              '  audiblez-ui\n\n' +
              'available voices:\n' +
              available_voices_str)

    # Load settings from database
    db_settings = load_all_user_settings()
    if not db_settings:
        db_settings = {}

    default_voice_from_db = db_settings.get('voice', 'af_sky')
    default_speed_from_db = db_settings.get('speed', 1.0)
    default_model = db_settings.get('tts_model', 'kokoro')
    default_ref_wav = db_settings.get('luxtts_reference_wav', '')
    default_steps = db_settings.get('luxtts_num_steps', 4)
    default_chunk_len = db_settings.get('luxtts_max_chunk_len', 900)

    try:
        default_speed_from_db = float(default_speed_from_db) if default_speed_from_db is not None else 1.0
    except ValueError:
        default_speed_from_db = 1.0


    parser = argparse.ArgumentParser(epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('epub_file_path', help='Path to the epub file')
    parser.add_argument('-v', '--voice', default=default_voice_from_db, help=f'Choose narrating voice: {voices_str} (default: {default_voice_from_db})')
    parser.add_argument('-p', '--pick', default=False, help=f'Interactively select which chapters to read in the audiobook', action='store_true')
    parser.add_argument('-s', '--speed', default=default_speed_from_db, help=f'Set speed from 0.5 to 2.0 (default: {default_speed_from_db})', type=float)
    parser.add_argument('-c', '--cuda', default=False, help=f'Use GPU via Cuda in Torch if available', action='store_true')
    parser.add_argument('-o', '--output', default='.', help='Output folder for the audiobook and temporary files', metavar='FOLDER')
    
    # LuxTTS specific arguments
    parser.add_argument('-m', '--model', default=default_model, choices=['kokoro', 'luxtts'], help=f'TTS model to use (default: {default_model})')
    parser.add_argument('--ref-wav', default=default_ref_wav, help='Reference WAV file for LuxTTS voice cloning')
    parser.add_argument('--steps', default=default_steps, type=int, help=f'Inference steps for LuxTTS (default: {default_steps})')
    parser.add_argument('--chunk-len', default=default_chunk_len, type=int, help=f'Max chunk length for LuxTTS (default: {default_chunk_len})')

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()

    # CUDA/Engine Handling Logic
    engine_device = 'cpu'
    if args.cuda:
        if torch.cuda.is_available():
            engine_device = 'cuda'
        else:
            print('CUDA GPU not available (specified by user via --cuda, but unavailable). Defaulting to CPU.')
    elif db_settings.get('engine') == 'cuda':
        if torch.cuda.is_available():
            engine_device = 'cuda'
        else:
            print('CUDA GPU not available (from database settings, but unavailable). Defaulting to CPU.')

    print(f"Using device: {engine_device}")

    from audiblez.core import main
    
    main(
        file_path=args.epub_file_path, 
        voice=args.voice, 
        pick_manually=args.pick, 
        speed=args.speed, 
        output_folder=args.output,
        engine_device=engine_device,
        tts_model=args.model,
        reference_wav=args.ref_wav,
        num_steps=args.steps,
        max_chunk_len=args.chunk_len
    )


if __name__ == '__main__':
    cli_main()

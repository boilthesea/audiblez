# -*- coding: utf-8 -*-
import argparse
import sys
import torch # Added for torch.set_default_device and torch.cuda.is_available

from audiblez.voices import voices, available_voices_str
from audiblez.database import load_all_user_settings # Added

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
    if not db_settings: # Ensure it's a dict
        db_settings = {}

    default_voice_from_db = db_settings.get('voice', 'af_sky')
    default_speed_from_db = db_settings.get('speed', 1.0)
    try:
        # Ensure speed is float, as DB might store as REAL or text if schema is loose
        default_speed_from_db = float(default_speed_from_db) if default_speed_from_db is not None else 1.0
    except ValueError:
        default_speed_from_db = 1.0


    parser = argparse.ArgumentParser(epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('epub_file_path', help='Path to the epub file')
    parser.add_argument('-v', '--voice', default=default_voice_from_db, help=f'Choose narrating voice: {voices_str} (default: {default_voice_from_db})')
    parser.add_argument('-p', '--pick', default=False, help=f'Interactively select which chapters to read in the audiobook', action='store_true')
    parser.add_argument('-s', '--speed', default=default_speed_from_db, help=f'Set speed from 0.5 to 2.0 (default: {default_speed_from_db})', type=float)
    # For CUDA, default is False. We handle DB setting after parsing args.
    parser.add_argument('-c', '--cuda', default=False, help=f'Use GPU via Cuda in Torch if available', action='store_true')
    parser.add_argument('-o', '--output', default='.', help='Output folder for the audiobook and temporary files', metavar='FOLDER')

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()

    # CUDA/Engine Handling Logic
    use_cuda_from_cli = args.cuda # True if --cuda is present
    engine_from_db = db_settings.get('engine')

    if use_cuda_from_cli:
        if torch.cuda.is_available():
            print('CUDA GPU available (specified by user via --cuda). Using CUDA.')
            torch.set_default_device('cuda')
        else:
            print('CUDA GPU not available (specified by user via --cuda, but unavailable). Defaulting to CPU.')
            torch.set_default_device('cpu')
    elif engine_from_db == 'cuda':
        if torch.cuda.is_available():
            print('CUDA GPU available (from database settings). Using CUDA.')
            torch.set_default_device('cuda')
        else:
            print('CUDA GPU not available (from database settings, but unavailable). Defaulting to CPU.')
            torch.set_default_device('cpu')
    else:
        # Default to CPU if --cuda not used and DB setting is not 'cuda' or not present
        print('Defaulting to CPU (no CUDA specified by user and not set to CUDA in DB).')
        torch.set_default_device('cpu')


    from core import main # Consider moving core import to top if it's safe / no circular deps
    # Pass the potentially modified args.voice and args.speed
    main(file_path=args.epub_file_path, voice=args.voice, pick_manually=args.pick, speed=args.speed, output_folder=args.output)


if __name__ == '__main__':
    cli_main()

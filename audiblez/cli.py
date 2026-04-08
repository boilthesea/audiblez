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
    default_guidance = db_settings.get('luxtts_guidance', 3.0)
    default_t_shift = db_settings.get('luxtts_t_shift', 0.5)
    default_lux_speed = db_settings.get('luxtts_speed', 1.0)
    default_rms = db_settings.get('luxtts_rms', 0.1)
    default_duration = db_settings.get('luxtts_duration', 5.0)
    default_smooth = db_settings.get('luxtts_smooth', False)
    default_seed = db_settings.get('luxtts_seed')

    try:
        default_speed_from_db = float(default_speed_from_db) if default_speed_from_db is not None else 1.0
    except ValueError:
        default_speed_from_db = 1.0


    parser = argparse.ArgumentParser(epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('epub_file_path', help='Path to the epub file')
    parser.add_argument('-v', '--voice', default=default_voice_from_db, help=f'Choose narrating voice: {voices_str} (default: {default_voice_from_db})')
    parser.add_argument('-p', '--pick', default=False, help=f'Interactively select which chapters to read in the audiobook', action='store_true')
    parser.add_argument('-s', '--speed', default=None, help=f'Set speed from 0.5 to 2.0 (default from DB or 1.0)', type=float)
    parser.add_argument('-c', '--cuda', default=False, help=f'Use GPU via Cuda in Torch if available', action='store_true')
    parser.add_argument('-o', '--output', default='.', help='Output folder for the audiobook and temporary files', metavar='FOLDER')
    
    # LuxTTS specific arguments
    parser.add_argument('-m', '--model', default=default_model, choices=['kokoro', 'luxtts'], help=f'TTS model to use (default: {default_model})')
    parser.add_argument('--ref-wav', default=default_ref_wav, help='Reference WAV file for LuxTTS voice cloning')
    parser.add_argument('--steps', default=default_steps, type=int, help=f'Inference steps for LuxTTS (default: {default_steps})')
    parser.add_argument('--chunk-len', default=default_chunk_len, type=int, help=f'Max chunk length for LuxTTS (default: {default_chunk_len})')
    parser.add_argument('--guidance', default=default_guidance, type=float, help=f'Guidance scale for LuxTTS (default: {default_guidance})')
    parser.add_argument('--t-shift', default=default_t_shift, type=float, help=f'T-Shift for LuxTTS (default: {default_t_shift})')
    parser.add_argument('--rms', default=default_rms, type=float, help=f'Target RMS for LuxTTS (default: {default_rms})')
    parser.add_argument('--duration', default=default_duration, type=float, help=f'Prompt duration for LuxTTS (default: {default_duration})')
    parser.add_argument('--smooth', action='store_true', default=default_smooth, help=f'Enable vocos smoothing (default: {default_smooth})')
    parser.add_argument('--seed', default=default_seed, type=int, help=f'Fixed seed for LuxTTS')

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()

    # Determine final speed based on model
    final_speed = args.speed
    if final_speed is None:
        if args.model == 'luxtts':
            final_speed = default_lux_speed
        else:
            final_speed = default_speed_from_db

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
        speed=final_speed, 
        output_folder=args.output,
        engine_device=engine_device,
        tts_model=args.model,
        reference_wav=args.ref_wav,
        num_steps=args.steps,
        max_chunk_len=args.chunk_len,
        guidance_scale=args.guidance,
        t_shift=args.t_shift,
        rms=args.rms,
        duration=args.duration,
        return_smooth=args.smooth,
        seed=args.seed
    )


if __name__ == '__main__':
    cli_main()

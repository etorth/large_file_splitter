#!/usr/bin/env python3
import os
import sys
import zipfile
import shutil
from pathlib import Path
import argparse

MAX_SIZE = 1024 * 1024  # 1 MByte
CHUNK_SIZE = 1024 * 1024  # 1 MByte for split files

def split_file(zip_path, output_dir, max_chunk_size=CHUNK_SIZE, verbose=False):
    """Split a zip file into chunks smaller than max_chunk_size"""
    chunk_num = 1
    with open(zip_path, 'rb') as f:
        while True:
            chunk = f.read(max_chunk_size)
            if not chunk:
                break
            chunk_path = output_dir / f"{zip_path.name}.{chunk_num}"
            with open(chunk_path, 'wb') as chunk_file:
                chunk_file.write(chunk)
            if verbose:
                print(f"  Created chunk: {chunk_path} ({len(chunk)} bytes)")
            chunk_num += 1

def compress_and_split(file_path, auto_remove=False, verbose=False):
    """Compress a file and split it if necessary"""
    file_size = file_path.stat().st_size

    if file_size <= MAX_SIZE:
        if verbose:
            print(f"Skipping {file_path} (size: {file_size} bytes <= 1MB)")
        return

    print(f"Processing {file_path} (size: {file_size} bytes)")

    # Create directory for split files
    dir_name = file_path.parent / f"{file_path.name}.dir"
    dir_name.mkdir(exist_ok=True)
    if verbose:
        print(f"  Created directory: {dir_name}")

    # Create zip file
    zip_path = file_path.parent / f"{file_path.name}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(file_path, file_path.name)
    if verbose:
        print(f"  Compressed to: {zip_path} ({zip_path.stat().st_size} bytes)")

    # Split zip file into chunks
    split_file(zip_path, dir_name, verbose=verbose)

    # Remove the temporary zip file
    zip_path.unlink()
    if verbose:
        print(f"  Removed temporary zip: {zip_path}")

    # Remove original file if auto_remove is enabled
    if auto_remove:
        file_path.unlink()
        if verbose:
            print(f"  Removed original file: {file_path}")

def recover_file(dir_path, auto_remove=False, verbose=False):
    """Recover a file from its .dir directory"""
    dir_name = dir_path.name

    # The original filename is everything before .dir
    if not dir_name.endswith('.dir'):
        return

    original_name = dir_name[:-4]  # Remove .dir suffix
    original_path = dir_path.parent / original_name

    print(f"Recovering {original_name} from {dir_path}")

    # Find all split chunks
    zip_chunks = sorted(dir_path.glob(f"{original_name}.zip.*"),
                       key=lambda x: int(x.suffix[1:]))

    if not zip_chunks:
        print(f"  Warning: No split files found in {dir_path}")
        return

    # Concatenate chunks into a single zip file
    zip_path = dir_path.parent / f"{original_name}.zip"
    with open(zip_path, 'wb') as outf:
        for chunk in zip_chunks:
            if verbose:
                print(f"  Concatenating {chunk.name}")
            with open(chunk, 'rb') as inf:
                shutil.copyfileobj(inf, outf)

    if verbose:
        print(f"  Created: {zip_path} ({zip_path.stat().st_size} bytes)")

    # Extract the zip file
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(dir_path.parent)
    if verbose:
        print(f"  Extracted to: {original_path}")

    # Remove the temporary zip file
    zip_path.unlink()
    if verbose:
        print(f"  Removed temporary zip: {zip_path}")

    # Remove the .dir directory if auto_remove is enabled
    if auto_remove:
        shutil.rmtree(dir_path)
        if verbose:
            print(f"  Removed directory: {dir_path}")

def scan_directory(root_dir, recover_mode=False, auto_remove=False, verbose=False):
    """Recursively scan directory and process files"""
    root_path = Path(root_dir)

    if recover_mode:
        # Find all .dir directories and recover files
        for item in root_path.rglob('*.dir'):
            if item.is_dir():
                try:
                    recover_file(item, auto_remove=auto_remove, verbose=verbose)
                except Exception as e:
                    print(f"Error recovering from {item}: {e}")
    else:
        # Get all files, excluding .dir directories and .zip files we create
        for item in root_path.rglob('*'):
            # Skip directories
            if item.is_dir():
                continue

            # Skip files in .dir directories (already processed)
            if any(part.endswith('.dir') for part in item.parts):
                continue

            # Skip .zip files (temporary files)
            if item.suffix == '.zip' and item.with_suffix('').exists():
                continue

            # Skip the script itself
            if item.name == 'large_file_splitter.py':
                continue

            try:
                compress_and_split(item, auto_remove=auto_remove, verbose=verbose)
            except Exception as e:
                print(f"Error processing {item}: {e}")

def main():
    parser = argparse.ArgumentParser(description='Compress and split large files, or recover them.')
    parser.add_argument('--recover', action='store_true',
                       help='Recover files from .dir directories')
    parser.add_argument('--auto-remove', action='store_true',
                       help='Automatically remove original files after compression and splitting')
    parser.add_argument('--verbose', action='store_true',
                       help='Show detailed logging information')
    args = parser.parse_args()

    verbose = args.verbose

    current_dir = os.getcwd()
    print(f"Scanning directory: {current_dir}")

    if args.recover:
        print("Mode: RECOVER")
        if args.auto_remove:
            print("Auto-remove: ENABLED (.dir directories will be deleted after recovery)")
    else:
        print(f"Mode: COMPRESS AND SPLIT")
        print(f"Maximum file size: {MAX_SIZE} bytes (1 MByte)")
        if args.auto_remove:
            print("Auto-remove: ENABLED (original files will be deleted after splitting)")

    if verbose:
        print("Verbose: ENABLED")

    print("-" * 60)
    scan_directory(current_dir, recover_mode=args.recover, auto_remove=args.auto_remove, verbose=verbose)
    print("-" * 60)
    print("Done!")

if __name__ == "__main__":
    main()

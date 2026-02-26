#!/usr/bin/env python3
import os
import sys
import zipfile
import shutil
import argparse
import stat
from pathlib import Path


def set_file_permissions(file_path, mode):
    try:
        if sys.platform == 'win32':
            if not (mode & stat.S_IWUSR):
                file_path.chmod(stat.S_IREAD)
            else:
                file_path.chmod(stat.S_IREAD | stat.S_IWRITE)
        else:
            file_path.chmod(mode)
    except Exception as e:
        pass


def get_file_permissions(file_path):
    try:
        return file_path.stat().st_mode
    except Exception:
        return stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH


def split_file(zip_path, output_dir, max_chunk_size, file_mode, verbose=False):
    file_size = zip_path.stat().st_size

    total_chunks = (file_size + max_chunk_size - 1) // max_chunk_size
    padding_width = len(str(total_chunks - 1))

    chunk_num = 0
    with open(zip_path, 'rb') as f:
        while True:
            chunk = f.read(max_chunk_size)
            if not chunk:
                break
            chunk_suffix = str(chunk_num).zfill(padding_width)
            chunk_path = output_dir / f"{zip_path.name}.{chunk_suffix}"
            with open(chunk_path, 'wb') as chunk_file:
                chunk_file.write(chunk)

            set_file_permissions(chunk_path, file_mode)
            if verbose:
                print(f"  Created chunk: {chunk_path} ({len(chunk)} bytes)")
            chunk_num += 1


def compress_and_split(file_path, max_size, auto_remove=False, verbose=False):
    file_size = file_path.stat().st_size

    if file_size <= max_size:
        if verbose:
            print(f"Skipping {file_path} (size: {file_size} bytes <= {max_size} bytes)")
        return

    print(f"Processing {file_path} (size: {file_size} bytes)")

    file_mode = get_file_permissions(file_path)
    dir_name = file_path.parent / f"{file_path.name}.dir"
    dir_name.mkdir(exist_ok=True)

    if verbose:
        print(f"  Created directory: {dir_name}")

    zip_path = file_path.parent / f"{file_path.name}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(file_path, file_path.name)

    if verbose:
        print(f"  Compressed to: {zip_path} ({zip_path.stat().st_size} bytes)")

    split_file(zip_path, dir_name, max_chunk_size=max_size, file_mode=file_mode, verbose=verbose)

    zip_path.unlink()
    if verbose:
        print(f"  Removed temporary zip: {zip_path}")

    if auto_remove:
        file_path.unlink()
        if verbose:
            print(f"  Removed original file: {file_path}")


def recover_file(dir_path, auto_remove=False, verbose=False):
    dir_name = dir_path.name

    if not dir_name.endswith('.dir'):
        return

    original_name = dir_name[:-4]
    original_path = dir_path.parent / original_name

    print(f"Recovering {original_name} from {dir_path}")

    zip_chunks = sorted(dir_path.glob(f"{original_name}.zip.*"),
                        key=lambda x: int(x.suffix[1:]) if x.suffix[1:].isdigit() else 0)

    if not zip_chunks:
        print(f"  Warning: No split files found in {dir_path}")
        return

    chunk_mode = get_file_permissions(zip_chunks[0])
    zip_path = dir_path.parent / f"{original_name}.zip"

    with open(zip_path, 'wb') as outf:
        for chunk in zip_chunks:
            if verbose:
                print(f"  Concatenating {chunk.name}")
            with open(chunk, 'rb') as inf:
                shutil.copyfileobj(inf, outf)

    if verbose:
        print(f"  Created: {zip_path} ({zip_path.stat().st_size} bytes)")

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(dir_path.parent)
    if verbose:
        print(f"  Extracted to: {original_path}")

    set_file_permissions(original_path, chunk_mode)
    if verbose:
        print(f"  Restored permissions: {oct(chunk_mode)}")

    zip_path.unlink()
    if verbose:
        print(f"  Removed temporary zip: {zip_path}")

    if auto_remove:
        shutil.rmtree(dir_path)
        if verbose:
            print(f"  Removed directory: {dir_path}")


def check_for_symlinks(root_dir, verbose=False):
    root_path = Path(root_dir)

    for item in root_path.rglob('*'):
        if any(part.endswith('.dir') for part in item.parts):
            continue
        if any(part.endswith('.git') for part in item.parts):
            continue

        if item.is_symlink():
            return True, item

    return False, None


def scan_directory(root_dir, max_size, recover_mode=False, auto_remove=False, verbose=False):
    root_path = Path(root_dir)

    if recover_mode:
        for item in root_path.rglob('*.dir'):
            if item.is_dir():
                try:
                    recover_file(item, auto_remove=auto_remove, verbose=verbose)
                except Exception as e:
                    print(f"Error recovering from {item}: {e}")
    else:
        has_symlinks, first_symlink = check_for_symlinks(root_dir, verbose=verbose)
        if has_symlinks:
            print(f"Error: Found symlink {first_symlink}. Symlinks are not supported.")
            print("Please remove all symlinks before running this tool.")
            sys.exit(1)

        for item in root_path.rglob('*'):
            if item.is_dir():
                continue

            if any(part.endswith('.dir') for part in item.parts):
                continue

            if any(part.endswith('.git') for part in item.parts):
                continue

            if item.suffix == '.zip' and item.with_suffix('').exists():
                continue

            if item.name == 'large_file_splitter.py':
                continue

            try:
                compress_and_split(item, max_size=max_size, auto_remove=auto_remove, verbose=verbose)
            except Exception as e:
                print(f"Error processing {item}: {e}")


def main():
    parser = argparse.ArgumentParser(description='Large file splitting/recovery.')
    parser.add_argument('--verbose', action='store_true', help='Show logging information')
    parser.add_argument('--recover', action='store_true', help='Recover <file> from <file>.dir directories')
    parser.add_argument('--auto-remove', action='store_true', help='Automatically remove original files after compression and splitting')
    parser.add_argument('--max-size', type=int, required=True, help='Maximum chunk size in bytes (must be positive)')
    args = parser.parse_args()

    if args.max_size <= 0:
        print("Error: --max-size must be a positive number")
        sys.exit(1)

    if args.max_size < 1024:
        print(f"Warning: file chunk is small: {args.max_size}")

    current_dir = os.getcwd()
    print(f"Scanning directory: {current_dir}")

    if args.recover:
        print("Mode: RECOVER")
        if args.auto_remove:
            print("Auto-remove: ENABLED, <file>.dir directories will be deleted after recovery")
    else:
        print(f"Mode: COMPRESS AND SPLIT")
        print(f"Maximum file size: {args.max_size} bytes")
        if args.auto_remove:
            print("Auto-remove: ENABLED (original files will be deleted after splitting)")

    if args.verbose:
        print("Verbose: ENABLED")

    print("-" * 60)
    scan_directory(current_dir, max_size=args.max_size, recover_mode=args.recover, auto_remove=args.auto_remove, verbose=args.verbose)
    print("-" * 60)
    print("Done!")


if __name__ == "__main__":
    main()

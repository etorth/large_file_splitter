#!/usr/bin/env python3
import os
import sys
import zipfile
import shutil
import argparse
import stat
import hashlib
from pathlib import Path


def calculate_md5(file_path):
    md5_hash = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


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


def compress_and_split(file_path, output_path, max_size, split_suffix='dir', verbose=False):
    file_size = file_path.stat().st_size

    if file_size <= max_size:
        print(f"Copying {file_path} (size: {file_size} bytes <= {max_size} bytes)")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, output_path)
        if verbose:
            print(f"  Copied to: {output_path}")
        return

    print(f"Processing {file_path} (size: {file_size} bytes)")

    if verbose:
        print(f"  Calculating MD5 checksum...")
    original_md5 = calculate_md5(file_path)
    if verbose:
        print(f"  MD5: {original_md5}")

    file_mode = get_file_permissions(file_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dir_name = output_path.parent / f"{output_path.name}.{split_suffix}"
    dir_name.mkdir(exist_ok=True)

    if verbose:
        print(f"  Created directory: {dir_name}")

    md5_file = dir_name / f"{output_path.name}.md5"
    with open(md5_file, 'w') as f:
        f.write(f"{original_md5}  {output_path.name}\n")
    if verbose:
        print(f"  Saved checksum to: {md5_file}")

    zip_path = output_path.parent / f"{output_path.name}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(file_path, output_path.name)

    if verbose:
        print(f"  Compressed to: {zip_path} ({zip_path.stat().st_size} bytes)")

    split_file(zip_path, dir_name, max_chunk_size=max_size, file_mode=file_mode, verbose=verbose)

    zip_path.unlink()
    if verbose:
        print(f"  Removed temporary zip: {zip_path}")


def recover_file(dir_path, output_path, split_suffix, max_size=None, verbose=False):
    dir_name = dir_path.name

    expected_suffix = f'.{split_suffix}'
    if not dir_name.endswith(expected_suffix):
        return

    original_name = dir_name[:-len(expected_suffix)]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Recovering {original_name} from {dir_path}")

    all_chunks = list(dir_path.glob(f"{original_name}.zip.*"))

    if not all_chunks:
        print(f"  Error: No split files found in {dir_path}")
        return

    valid_chunks = []
    chunk_numbers = []
    non_numeric = []

    for chunk in all_chunks:
        suffix = chunk.suffix[1:]
        if suffix.isdigit():
            valid_chunks.append(chunk)
            chunk_numbers.append(int(suffix))
        else:
            non_numeric.append(chunk)

    if not valid_chunks:
        print(f"  Error: No valid chunk files found (files must end with .zip.0, .zip.1, etc.)")
        return

    if non_numeric and verbose:
        print(f"  Warning: Found {len(non_numeric)} non-chunk files in directory (will be ignored)")

    chunk_numbers.sort()
    valid_chunks.sort(key=lambda x: int(x.suffix[1:]))

    expected_chunks = list(range(len(chunk_numbers)))
    if chunk_numbers != expected_chunks:
        print(f"  Error: Missing or non-sequential chunks detected")
        print(f"    Expected: {expected_chunks}")
        print(f"    Found:    {chunk_numbers}")

        missing = [i for i in expected_chunks if i not in chunk_numbers]
        if missing:
            print(f"    Missing chunks: {missing}")

        unexpected = [i for i in chunk_numbers if i >= len(expected_chunks)]
        if unexpected:
            print(f"    Unexpected chunks: {unexpected}")

        print(f"  Cannot recover: chunk sequence is incomplete or corrupted")
        return

    if chunk_numbers[0] != 0:
        print(f"  Error: First chunk should be .0, but found .{chunk_numbers[0]}")
        return

    expected_last = len(chunk_numbers) - 1
    if chunk_numbers[-1] != expected_last:
        print(f"  Error: Last chunk should be .{expected_last}, but found .{chunk_numbers[-1]}")
        return

    if verbose:
        print(f"  Validated {len(valid_chunks)} chunks (sequential from 0 to {expected_last})")

    if max_size is not None:
        oversized_chunks = []
        for chunk in valid_chunks:
            chunk_size = chunk.stat().st_size
            if chunk_size > max_size:
                oversized_chunks.append((chunk.name, chunk_size))

        if oversized_chunks:
            print(f"  Error: Found {len(oversized_chunks)} chunk(s) larger than max-size ({max_size} bytes):")
            for chunk_name, size in oversized_chunks[:5]:
                print(f"    - {chunk_name}: {size} bytes (exceeds limit by {size - max_size} bytes)")
            if len(oversized_chunks) > 5:
                print(f"    ... and {len(oversized_chunks) - 5} more")
            print(f"  Cannot recover: chunk sizes are invalid")
            return
        elif verbose:
            print(f"  All chunks are within size limit ({max_size} bytes)")

    chunk_mode = get_file_permissions(valid_chunks[0])
    zip_path = output_path.parent / f"{output_path.name}.zip"

    with open(zip_path, 'wb') as outf:
        for chunk in valid_chunks:
            if verbose:
                print(f"  Concatenating {chunk.name}")
            with open(chunk, 'rb') as inf:
                shutil.copyfileobj(inf, outf)

    if verbose:
        print(f"  Created: {zip_path} ({zip_path.stat().st_size} bytes)")

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        zipf.extractall(output_path.parent)
    if verbose:
        print(f"  Extracted to: {output_path}")

    set_file_permissions(output_path, chunk_mode)
    if verbose:
        print(f"  Restored permissions: {oct(chunk_mode)}")

    md5_file = dir_path / f"{original_name}.md5"
    if md5_file.exists():
        try:
            with open(md5_file, 'r') as f:
                md5_line = f.read().strip()
                expected_md5 = md5_line.split()[0]

            if verbose:
                print(f"  Verifying MD5 checksum...")

            actual_md5 = calculate_md5(output_path)

            if actual_md5 == expected_md5:
                print(f"  ✓ MD5 verification passed: {actual_md5}")
            else:
                print(f"  ✗ MD5 verification FAILED!")
                print(f"    Expected: {expected_md5}")
                print(f"    Actual:   {actual_md5}")
                print(f"  WARNING: Recovered file may be corrupted!")
        except Exception as e:
            print(f"  Warning: Could not verify MD5 checksum: {e}")
    else:
        if verbose:
            print(f"  Note: No MD5 checksum file found (older split or missing file)")

    zip_path.unlink()
    if verbose:
        print(f"  Removed temporary zip: {zip_path}")


def check_for_symlinks(root_dir, verbose=False):
    """Check if there are any symlinks in the directory"""
    root_path = Path(root_dir)

    for item in root_path.rglob('*'):
        if any(part.endswith('.dir') for part in item.parts):
            continue
        if any(part.endswith('.git') for part in item.parts):
            continue

        if item.is_symlink():
            return True, item

    return False, None


def check_for_conflicts(root_dir, split_suffix='dir', verbose=False):
    """Check for files that already have corresponding split directories"""
    root_path = Path(root_dir)
    conflicts = []

    for item in root_path.rglob('*'):
        if item.is_dir():
            continue

        if any(part.endswith(f'.{split_suffix}') for part in item.parts):
            continue

        if any(part.endswith('.git') for part in item.parts):
            continue

        if item.name == 'large_file_splitter.py':
            continue

        dir_name = item.parent / f"{item.name}.{split_suffix}"
        if dir_name.exists() and dir_name.is_dir():
            conflicts.append((item, dir_name))

    return conflicts


def scan_directory(input_dir, output_dir, max_size, split_suffix='dir', recover_mode=False, verbose=False):
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    if verbose:
        print("Creating directory structure...")

    for item in input_path.rglob('*'):
        if item.is_dir():
            if recover_mode and item.name.endswith(f'.{split_suffix}'):
                continue

            if any(part.endswith('.git') for part in item.parts):
                continue

            if any(part.endswith(f'.{split_suffix}') for part in item.parts):
                continue

            rel_path = item.relative_to(input_path)
            output_dir_path = output_path / rel_path
            output_dir_path.mkdir(parents=True, exist_ok=True)
            if verbose:
                print(f"  Created directory: {output_dir_path}")

    if recover_mode:
        for item in input_path.rglob(f'*.{split_suffix}'):
            if item.is_dir():
                try:
                    rel_path = item.relative_to(input_path)
                    original_name = item.name[:-len(f'.{split_suffix}')]
                    output_file = output_path / rel_path.parent / original_name
                    recover_file(item, output_file, split_suffix, max_size=max_size, verbose=verbose)
                except Exception as e:
                    print(f"Error recovering from {item}: {e}")

        for item in input_path.rglob('*'):
            if item.is_dir():
                continue

            if any(part.endswith(f'.{split_suffix}') for part in item.parts):
                continue

            if any(part.endswith('.git') for part in item.parts):
                continue

            try:
                rel_path = item.relative_to(input_path)
                output_file = output_path / rel_path
                output_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, output_file)
                if verbose:
                    print(f"Copying {item} to {output_file}")
            except Exception as e:
                print(f"Error copying {item}: {e}")
    else:
        has_symlinks, first_symlink = check_for_symlinks(input_dir, verbose=verbose)
        if has_symlinks:
            print(f"Error: Found symlink {first_symlink}. Symlinks are not supported.")
            print("Please remove all symlinks before running this tool.")
            sys.exit(1)

        conflicts = check_for_conflicts(input_dir, split_suffix=split_suffix, verbose=verbose)
        if conflicts:
            print(f"Error: Found {len(conflicts)} file(s) with existing .{split_suffix} directories:")
            for file_path, dir_path in conflicts[:5]:
                print(f"  - {file_path} (has {dir_path})")
            if len(conflicts) > 5:
                print(f"  ... and {len(conflicts) - 5} more")
            print(f"\nPlease remove the .{split_suffix} directories or the files before running.")
            print("This prevents accidental overwrites and data corruption.")
            sys.exit(1)

        for item in input_path.rglob('*'):
            if item.is_dir():
                continue

            if any(part.endswith(f'.{split_suffix}') for part in item.parts):
                continue

            if any(part.endswith('.git') for part in item.parts):
                continue

            if item.suffix == '.zip' and item.with_suffix('').exists():
                continue

            if item.name == 'large_file_splitter.py':
                continue

            try:
                rel_path = item.relative_to(input_path)
                output_file = output_path / rel_path
                compress_and_split(item, output_file, max_size=max_size, split_suffix=split_suffix, verbose=verbose)
            except Exception as e:
                print(f"Error processing {item}: {e}")


def main():
    parser = argparse.ArgumentParser(description='Large file splitting/recovery.')
    parser.add_argument('--input-dir', required=True, help='Input directory to process')
    parser.add_argument('--output-dir', required=True, help='Output directory for results')
    parser.add_argument('--split-dir-suffix', default='dir', help='Suffix for split directories (default: "dir", creates filename.dir)')
    parser.add_argument('--verbose', action='store_true', help='Show logging information')
    parser.add_argument('--recover', action='store_true', help='Recover files from split directories')
    parser.add_argument('--max-size', type=int, help='Maximum chunk size in bytes (required for split mode, optional for recovery mode)')
    args = parser.parse_args()

    input_path = Path(args.input_dir)
    if not input_path.exists():
        print(f"Error: Input directory does not exist: {args.input_dir}")
        sys.exit(1)
    if not input_path.is_dir():
        print(f"Error: Input path is not a directory: {args.input_dir}")
        sys.exit(1)

    output_path = Path(args.output_dir)
    if output_path.exists():
        print(f"Error: Output directory already exists: {args.output_dir}")
        print("Please remove it or choose a different output directory.")
        sys.exit(1)

    if not args.recover:
        if args.max_size is None:
            print("Error: --max-size is required for split mode")
            print("Usage: --max-size <bytes>")
            sys.exit(1)

        if args.max_size <= 0:
            print("Error: --max-size must be a positive number")
            sys.exit(1)

        if args.max_size < 1024:
            print(f"Warning: file chunk is small: {args.max_size}")

    print(f"Input directory: {input_path.absolute()}")
    print(f"Output directory: {output_path.absolute()}")
    print(f"Split directory suffix: .{args.split_dir_suffix}")

    if args.recover:
        print("Mode: RECOVER")
    else:
        print(f"Mode: COMPRESS AND SPLIT")
        print(f"Maximum file size: {args.max_size} bytes")

    if args.verbose:
        print("Verbose: ENABLED")

    print("-" * 60)
    scan_directory(args.input_dir, args.output_dir, max_size=args.max_size, split_suffix=args.split_dir_suffix, recover_mode=args.recover, verbose=args.verbose)
    print("-" * 60)
    print("Done!")


if __name__ == "__main__":
    main()

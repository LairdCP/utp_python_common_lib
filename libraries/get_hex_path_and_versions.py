#!/usr/bin/env python3

import argparse
from lc_util import logger_setup, logger_get
import os
import subprocess

logger = logger_get(__name__)


def get_hex_path_and_versions(build_dir: str, board_name: str, suffix: str = "", hex_name: str = "merged.hex"):
    """ 
    Helper function to find the hex file for a board in the build directory.
    Extract short version number and long version number from the folder name.
    This makes assumptions about the folder structure and naming conventions.
    """
    partial_folder_name = board_name + suffix

    # From the build directory,
    # recursively find a folder with the partial name of the board (using regex).
    result = subprocess.run(
        ['find', build_dir, '-type', 'd', '-regex',
            f'.*{partial_folder_name}.*'],
        stdout=subprocess.PIPE,
        text=True
    )
    sub_folder = result.stdout.strip()
    logger.debug(f"{sub_folder=}")

    # Example folder names:
    # lyra24_p10_mcuboot_0.1.99_1721932245
    #
    # The zephyr name is generated by twister.
    # sera_nx040_dvk/build.sera_nx040_dvk_1.1.99.1724698148/zephyr
    #
    # The last value is a timestamp. Since the build is multi-threaded,
    # it may not match for all folders.
    #
    if len(sub_folder) == 0:
        logger.error(
            f"Build folder with partial name {partial_folder_name} not found")
        empty = ""
        print(f"{empty},{empty},{empty}")
        return empty, empty, empty

    # Handle differences between Lyra and Zephyr output folder structures
    #
    # If the result contains newlines, split the string
    hex_folder = sub_folder
    sub_folder_list = sub_folder.split('\n')
    logger.debug(f"{sub_folder_list=}")
    if len(sub_folder_list) > 1:
        # If there is a folder with build.*_1.2.3.4 in its name, then it is a candidate
        for folder in sub_folder_list:
            if os.path.basename(folder) != "zephyr" or folder.count('.') < 4:
                sub_folder_list.remove(folder)

        # Use the shortest name because it is the most likely to be the correct one
        logger.debug(f"{sub_folder_list=}")
        sub_folder = min(sub_folder_list, key=len)
        logger.debug(f"shortest: {sub_folder=}")
        # Need original folder name for hex file search
        hex_folder = sub_folder
        # Remove the 'build.' prefix and the 'zephyr' suffix for easier version extraction
        sub_folder = sub_folder.replace('build.', '').replace('/zephyr', '')
        # Replace the last '.' with '_' so
        # that the version number can be extracted the same as Lyra
        sub_folder = sub_folder.rsplit('.', 1)[0] + '_' + sub_folder.rsplit('.', 1)[1]

    short_version = ""
    long_version = ""
    try:
        split = os.path.basename(sub_folder).split('_')
        logger.debug(f"{split=}")
        short_version = os.path.basename(sub_folder).split('_')[-2]
        logger.debug(f"{short_version=}")
        long_version = short_version + "+" + split[-1]
    except:
        logger.error(
            f"Error extracting versions from folder name: {sub_folder}")

    # Recursively find the hex file in the sub_folder
    result = subprocess.run(
        ['find', hex_folder, '-type', 'f', '-name', hex_name],
        stdout=subprocess.PIPE,
        text=True
    )
    hex_path = os.path.abspath(result.stdout.strip())

    # Values must be printed to use them in a GitHub action
    print(f"{hex_path},{short_version},{long_version}")

    return hex_path, short_version, long_version


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Find programming hex file full path and extract version number')

    parser.add_argument('--debug', action='store_true', default=False,
                        help="Enable verbose debug messages")
    parser.add_argument('-o', '--output_dir', required=True,
                        help="Build output directory")
    parser.add_argument('-b', '--board_name', required=True, help="Board name")
    parser.add_argument('-s', '--board_name_suffix',
                        default="", help="Board name suffix")
    parser.add_argument('-f', '--file_name',
                        default="merged.hex", help="Programming file name")
    args = parser.parse_args()

    logger = logger_setup(__file__, args.debug)

    if "bl5340" in args.board_name.casefold():
        if args.file_name == "merged.hex":
            args.file_name = "merged_domains.hex"

    get_hex_path_and_versions(build_dir=args.output_dir, board_name=args.board_name,
                              suffix=args.board_name_suffix, hex_name=args.file_name)

"""Locate an activation asset using this installation's Python interpreter."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shell", choices=("bash", "powershell"))
    args = parser.parse_args()
    filename = "sp.sh" if args.shell == "bash" else "sp.ps1"
    print(Path(__file__).resolve().with_name(filename))


if __name__ == "__main__":
    main()

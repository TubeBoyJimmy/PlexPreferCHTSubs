"""Quick-start entry point — run directly without pip install.

Usage:
    python run.py --dry-run
    python run.py --help
"""

import sys
from pathlib import Path

# Add src/ to Python path so imports work without installation
sys.path.insert(0, str(Path(__file__).parent / "src"))

from plexchtsubs.cli import main

if __name__ == "__main__":
    main()

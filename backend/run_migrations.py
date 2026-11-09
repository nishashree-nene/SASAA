"""
SASAA – Migration Runner
=========================
Run this script to generate and apply all database migrations.

Usage (from the backend/ directory):
    python run_migrations.py

What this does:
  1. Checks the database connection
  2. Generates an initial migration from your ORM models
  3. Applies it to create all tables in sasaa_db

After running this, open pgAdmin and expand:
  Servers > PostgreSQL 18 > Databases > sasaa_db > Schemas > public > Tables
You should see all 16 SASAA tables listed there.
"""

import subprocess
import sys
import os
from pathlib import Path

# Make sure we're in the backend directory
os.chdir(Path(__file__).parent)

def run(cmd: list[str], description: str) -> bool:
    """Run a command, print the result, return True if it succeeded."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print(f"\n  ERROR: {description} failed (exit code {result.returncode})")
        return False
    return True

def main():
    print("\nSASAA – Database Migration Runner")
    print("===================================")

    # Step 1: Generate the initial migration
    print("\nStep 1: Generating initial migration from ORM models...")
    success = run(
        [sys.executable, "-m", "alembic", "revision",
         "--autogenerate", "-m", "initial_schema_all_tables"],
        "alembic revision --autogenerate"
    )
    if not success:
        print("\nMigration generation failed.")
        print("Most likely cause: DATABASE_URL in .env still has YOUR_PASSWORD placeholder.")
        print("Fix: Open .env and replace YOUR_PASSWORD with your PostgreSQL password.")
        sys.exit(1)

    # Step 2: Apply the migration
    print("\nStep 2: Applying migration to sasaa_db...")
    success = run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        "alembic upgrade head"
    )
    if not success:
        print("\nMigration apply failed.")
        sys.exit(1)

    # Step 3: Show what was created
    print("\nStep 3: Migration history:")
    subprocess.run([sys.executable, "-m", "alembic", "history", "--verbose"])

    print("\n" + "="*60)
    print("  SUCCESS: All tables created in sasaa_db")
    print("="*60)
    print("\nNext steps:")
    print("  1. Open pgAdmin 4")
    print("  2. Navigate to: sasaa_db > Schemas > public > Tables")
    print("  3. You should see 16 tables plus alembic_version")
    print("\nNow run the FastAPI server:")
    print("  python -m uvicorn app.main:app --reload --port 8000")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
One-time migration script: Move all knowledge from SQLite to ChromaDB
"""
import sys
import asyncio
from storage import migrate_knowledge_to_chromadb, get_knowledge_count

def main():
    print(f"Current knowledge count in SQLite: {get_knowledge_count()}")
    print("\nStarting migration to ChromaDB...")

    try:
        migrated_count = migrate_knowledge_to_chromadb()
        print(f"✓ Successfully migrated {migrated_count} knowledge entries to ChromaDB")
        return 0
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Fix duplicate accounts in the database.

This script:
1. Finds duplicate account numbers
2. Keeps the account with the most references (journal_lines + expenses)
3. Updates all child records to point to the kept account
4. Deletes duplicate accounts
5. Adds a unique constraint on accounts.number if missing
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, select
from app.database import AsyncSessionLocal
from app.models.accounting import Account


async def fix_duplicate_accounts():
    async with AsyncSessionLocal() as session:
        async with session.begin():
            print("Checking for duplicate accounts...")
            
            # Find duplicate account numbers
            dup_result = await session.execute(
                text("""
                    SELECT number, COUNT(*) as cnt, array_agg(id) as ids
                    FROM accounts
                    GROUP BY number
                    HAVING COUNT(*) > 1
                """)
            )
            duplicates = dup_result.all()
            
            if not duplicates:
                print("No duplicate accounts found. Great!")
            else:
                print(f"Found {len(duplicates)} account number(s) with duplicates.")
                
                for dup in duplicates:
                    number = dup.number
                    ids = dup.ids
                    print(f"\n  Account #{number}: {len(ids)} duplicates (IDs: {ids})")
                    
                    # Count references for each duplicate
                    ref_counts = {}
                    for account_id in ids:
                        jl_count = await session.execute(
                            text("SELECT COUNT(*) FROM journal_lines WHERE account_id = :aid"),
                            {"aid": account_id}
                        )
                        exp_count = await session.execute(
                            text("SELECT COUNT(*) FROM expenses WHERE account_id = :aid"),
                            {"aid": account_id}
                        )
                        total = jl_count.scalar() + exp_count.scalar()
                        ref_counts[account_id] = total
                        print(f"    ID {account_id}: {total} references ({jl_count.scalar()} journal_lines, {exp_count.scalar()} expenses)")
                    
                    # Keep the account with the most references
                    keep_id = max(ref_counts, key=ref_counts.get)
                    delete_ids = [i for i in ids if i != keep_id]
                    
                    print(f"  -> Keeping ID {keep_id} (most references)")
                    print(f"  -> Updating references from {delete_ids} to {keep_id}")
                    
                    # Update journal_lines
                    for del_id in delete_ids:
                        await session.execute(
                            text("UPDATE journal_lines SET account_id = :keep WHERE account_id = :del"),
                            {"keep": keep_id, "del": del_id}
                        )
                    
                    # Update expenses
                    for del_id in delete_ids:
                        await session.execute(
                            text("UPDATE expenses SET account_id = :keep WHERE account_id = :del"),
                            {"keep": keep_id, "del": del_id}
                        )
                    
                    # Update parent_id references (self-referencing)
                    for del_id in delete_ids:
                        await session.execute(
                            text("UPDATE accounts SET parent_id = :keep WHERE parent_id = :del"),
                            {"keep": keep_id, "del": del_id}
                        )
                    
                    # Delete duplicate accounts
                    for del_id in delete_ids:
                        await session.execute(
                            text("DELETE FROM accounts WHERE id = :del"),
                            {"del": del_id}
                        )
                        print(f"  -> Deleted account ID {del_id}")
            
            # Check if unique constraint exists
            constraint_result = await session.execute(
                text("""
                    SELECT COUNT(*) FROM pg_indexes
                    WHERE indexname = 'ix_accounts_number'
                    AND tablename = 'accounts'
                """)
            )
            has_index = constraint_result.scalar() > 0
            
            constraint_result2 = await session.execute(
                text("""
                    SELECT COUNT(*) FROM pg_constraint
                    WHERE conname = 'uq_accounts_number'
                    AND conrelid = 'accounts'::regclass
                """)
            )
            has_constraint = constraint_result2.scalar() > 0
            
            if not has_constraint:
                print("\nAdding unique constraint on accounts.number...")
                try:
                    await session.execute(
                        text("ALTER TABLE accounts ADD CONSTRAINT uq_accounts_number UNIQUE (number)")
                    )
                    print("Unique constraint added successfully.")
                except Exception as e:
                    print(f"Warning: Could not add unique constraint: {e}")
                    print("This may be because duplicates still exist or the constraint already exists.")
            else:
                print("\nUnique constraint already exists.")
            
            print("\nDone!")


if __name__ == "__main__":
    asyncio.run(fix_duplicate_accounts())

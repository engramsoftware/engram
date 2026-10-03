"""
Reset an account's password from the server's command line.

Engram has no self-service "forgot password" (it let anyone on the network
take over an account by typing its email). Admins reset passwords in
Settings > Users; this script is for when no admin can sign in.

Usage (Docker):
    docker exec -it engram python reset_password.py you@example.com
    docker exec -it engram python reset_password.py you@example.com --make-admin

Usage (without Docker), from the backend folder:
    python reset_password.py you@example.com

The new password is typed twice (hidden). The account is signed out
everywhere and its API tokens are revoked. --make-admin also gives the
account admin rights.
"""

import argparse
import asyncio
import getpass
import os
import sys

from config import SQLITE_DB_PATH


def _run_as_database_owner() -> None:
    """When started as root (docker exec's default), switch to the user that owns
    the database, so any files SQLite creates keep the owner the app runs as."""
    if os.name != "posix" or os.geteuid() != 0 or not SQLITE_DB_PATH.exists():
        return
    st = SQLITE_DB_PATH.stat()
    if st.st_uid != 0:
        os.setgroups([])
        os.setgid(st.st_gid)
        os.setuid(st.st_uid)


async def _reset(email: str, password: str, make_admin: bool) -> int:
    # Imported here, after switching user, so nothing is created as root.
    # bcrypt directly (same scheme as routers.auth.hash_password): importing the
    # routers package would load the whole app.
    import bcrypt
    from sqlite_db import SQLiteDatabase, ObjectId

    db = SQLiteDatabase(str(SQLITE_DB_PATH))
    await db.connect()
    try:
        user = await db.users.find_one({"email": email})
        if not user or "passwordHash" not in user:
            print(f"No account with the email {email}.", file=sys.stderr)
            return 1
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        update = {"$set": {"passwordHash": password_hash}, "$inc": {"tokenVersion": 1}}
        if make_admin:
            update["$set"]["isAdmin"] = True
        await db.users.update_one({"_id": ObjectId(str(user["_id"]))}, update)
        await db.api_tokens.delete_many({"userId": str(user["_id"])})
    finally:
        await db.close()
    print(f"Password reset for {email}." + (" It is now an admin." if make_admin else "")
          + " It has been signed out everywhere and its API tokens were revoked.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset an Engram account's password.")
    parser.add_argument("email", help="the account's email address")
    parser.add_argument("--make-admin", action="store_true", help="also give the account admin rights")
    args = parser.parse_args()

    if not SQLITE_DB_PATH.exists():
        print(f"No database at {SQLITE_DB_PATH}.", file=sys.stderr)
        return 1
    _run_as_database_owner()

    password = getpass.getpass("New password (8+ characters): ")
    if len(password) < 8:
        print("The password must be at least 8 characters.", file=sys.stderr)
        return 1
    if getpass.getpass("Type it again: ") != password:
        print("The passwords don't match.", file=sys.stderr)
        return 1
    return asyncio.run(_reset(args.email, password, args.make_admin))


if __name__ == "__main__":
    sys.exit(main())

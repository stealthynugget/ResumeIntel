"""Create the first local admin without putting a password in shell history."""
import argparse
import getpass

from .auth import HASHER
from .db import connect, init_db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    init_db()
    password = getpass.getpass("New admin password (12+ characters): ")
    confirm = getpass.getpass("Confirm password: ")
    if len(password) < 12 or password != confirm:
        parser.error("Passwords must match and have at least 12 characters")
    with connect() as db:
        if db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone():
            parser.error("An active admin already exists; use the admin page")
        db.execute("INSERT INTO users(email,display_name,password_hash,role) VALUES(?,?,?,'admin')",
                   (args.email.strip().lower(), args.name.strip(), HASHER.hash(password)))
    print("Admin created")


if __name__ == "__main__":
    main()

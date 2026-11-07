"""Initialize Railway database and the first administrator from an owner-set secret.
Runs at boot, idempotently. Never logs credentials or modifies existing accounts.
"""
import os
import sys

import stometric.web  # register routers first, as required by installation
from stometric import db
from scripts.bootstrap import create

def main():
    db.migrate()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    email = os.environ.get("FIRST_ADMIN_EMAIL", "").strip().lower()
    if not password:
        print("Admin bootstrap: INITIAL_ADMIN_PASSWORD not set; existing accounts unchanged.",flush=True)
        return
    if len(password) < 12 or len(password) > 256 or "@" not in email:
        print("Admin bootstrap: invalid initial admin settings.",file=sys.stderr,flush=True)
        raise SystemExit(1)
    with db.connect() as c:
        # Only bootstrap a truly empty installation.
        if c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            print("Admin bootstrap: administrator already present; unchanged.",flush=True)
            return
        create(c, email, password, "My Seller Analytics")
    print("Admin bootstrap: first administrator created.",flush=True)

if __name__=="__main__":
    main()

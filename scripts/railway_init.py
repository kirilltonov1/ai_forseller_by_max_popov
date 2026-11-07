"""Initialize Railway schema and owner-supplied administrator password.
Existing users are not changed except with an explicit single-use password repair flag.
Never log secrets.
"""
import os
import sys

import stometric.web
from stometric import db, auth
from scripts.bootstrap import create

def main():
    db.migrate()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    email = os.environ.get("FIRST_ADMIN_EMAIL", "").strip().lower()
    if not password:
        print("Admin bootstrap: no initial password configured.", flush=True)
        return
    if len(password) < 12 or len(password) > 256 or "@" not in email:
        print("Admin bootstrap: invalid credentials configuration.", file=sys.stderr, flush=True)
        raise SystemExit(1)
    with db.connect() as c:
        if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            create(c, email, password, "My Seller Analytics")
            print("Admin bootstrap: first administrator created.", flush=True)
            return

        if os.environ.get("RESET_INITIAL_ADMIN_PASSWORD") != "1":
            print("Admin bootstrap: existing account unchanged.", flush=True)
            return

        # This table prevents accidental repeated password changes if a flag remains set.
        c.execute("""CREATE TABLE IF NOT EXISTS installation_repair_events
                   (event text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())""")
        c.execute("SELECT pg_advisory_xact_lock(11990071)")
        if c.execute("SELECT 1 FROM installation_repair_events WHERE event='first_admin_password_repair_v1'").fetchone():
            print("Admin repair: already completed, no changes.", flush=True)
            return
        user = c.execute("SELECT id FROM users WHERE lower(email)=%s AND is_superadmin=true AND is_active=true", (email,)).fetchone()
        if not user:
            print("Admin repair: configured owner email does not match an existing administrator.", file=sys.stderr, flush=True)
            raise SystemExit(1)
        c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (auth.hash_password(password), user["id"]))
        c.execute("INSERT INTO installation_repair_events(event) VALUES ('first_admin_password_repair_v1')")
        c.commit()
    print("Admin repair: password synchronized with Railway variable.", flush=True)

if __name__ == "__main__":
    main()

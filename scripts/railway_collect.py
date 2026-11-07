"""Railway background collector: initialize recent history, then update due data.

Runs separately from the web container using Railway Cron. No shell/systemd needed.
Only reads marketplace APIs. Processing is serialized by DB advisory lock.
"""
import json
import sys

import stometric.web  # ensure all routers/models registered
from stometric import db

def main():
    with db.connect() as c:
        # Ensure a single collector job globally, even if Railway overlaps deployments.
        got = c.execute("SELECT pg_try_advisory_lock(529038144) locked").fetchone()["locked"]
        if not got:
            print("Collector already active; skip.", flush=True)
            return
        try:
            shops = c.execute("SELECT * FROM accounts WHERE is_active ORDER BY id").fetchall()
            if not shops:
                print("No active shops.", flush=True)
                return
            for acc in shops:
                try:
                    if acc["marketplace"] == "ozon":
                        from stometric import collectors_ozon as collectors
                    elif acc["marketplace"] == "ym":
                        from stometric import collectors_ym as collectors
                    else:
                        from stometric import collectors as collectors
                    account_id = acc["id"]
                    print(f"Collecting {acc['marketplace']} account {account_id}", flush=True)
                    if acc["marketplace"] == "ozon":
                        state = {x["collector"] for x in c.execute(
                            "SELECT collector FROM collector_state WHERE account_id=%s AND last_ok_at IS NOT NULL", (account_id,)
                        )}
                        names = [n for n in collectors.FIRST_LOAD if n not in state]
                        names += [n for n in collectors.due(c, account_id) if n not in names]
                        for name in names:
                            try:
                                result = collectors.run_one(c, acc, name)
                                result.pop("trace", None)
                                print(json.dumps({"account_id": account_id, **result}, default=str, ensure_ascii=False), flush=True)
                            except Exception as ex:
                                c.rollback()
                                print(f"Collector {name} failed: {type(ex).__name__} (check collector_state)", flush=True)
                    elif acc["marketplace"] == "ym":
                        for name in collectors.due(c, account_id):
                            try:
                                result = collectors.run_one(c, acc, name)
                                result.pop("trace", None)
                                print(json.dumps({"account_id": account_id, **result}, default=str, ensure_ascii=False), flush=True)
                            except Exception as ex:
                                c.rollback()
                                print(f"Collector {name} failed: {type(ex).__name__}", flush=True)
                    else:
                        # WB uses its existing single-store workflow with internal due planning,
                        # materialization and guarded advisory locking.
                        from stometric.__main__ import _collect_shop
                        _collect_shop(acc["name"])
                except Exception as ex:
                    c.rollback()
                    print(f"Account {acc['id']} failed: {type(ex).__name__}", flush=True)
        finally:
            c.execute("SELECT pg_advisory_unlock(529038144)")
            c.commit()

if __name__ == "__main__":
    main()

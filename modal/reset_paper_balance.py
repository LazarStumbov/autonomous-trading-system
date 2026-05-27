"""One-off: reset paper_balance_usd on the Modal volume to $5000.

Run with: python3 -m modal run modal/reset_paper_balance.py
"""

import modal

app = modal.App("reset-paper-balance")
image = modal.Image.debian_slim().pip_install("sqlite-utils")
data_volume = modal.Volume.from_name("trading-data")


@app.function(image=image, volumes={"/app/data": data_volume})
def reset(target: float = 5000.0) -> dict:
    import sqlite3
    from pathlib import Path

    db_path = Path("/app/data/db/trading.db")
    if not db_path.exists():
        return {"ok": False, "reason": f"no db at {db_path}"}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    before = cur.execute(
        "SELECT value FROM system_state WHERE key='paper_balance_usd'"
    ).fetchone()
    before_val = float(before[0]) if before else None

    cur.execute(
        "INSERT INTO system_state(key, value) VALUES('paper_balance_usd', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(target),),
    )
    conn.commit()

    after = cur.execute(
        "SELECT value FROM system_state WHERE key='paper_balance_usd'"
    ).fetchone()
    conn.close()

    data_volume.commit()
    return {"ok": True, "before": before_val, "after": float(after[0])}


@app.local_entrypoint()
def main(target: float = 5000.0):
    result = reset.remote(target)
    print(result)

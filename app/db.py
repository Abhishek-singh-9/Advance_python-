import sqlite3
import pathlib
import pandas as pd

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "echoguard.db"


def get_con():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS sessions (
        session_id INTEGER PRIMARY KEY, start_time TEXT, end_time TEXT,
        profile_id TEXT, volume_step INTEGER, max_step INTEGER, label TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY, fired_at TEXT, threshold INTEGER, message TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY, value TEXT)""")
    con.commit()
    return con


def seed_from_csv_once(csv_path):
    """Load the sample sessions into the database the first time only."""
    con = get_con()
    seeded = con.execute("SELECT value FROM meta WHERE key = 'seeded'").fetchone()
    if not seeded:
        pd.read_csv(csv_path).to_sql("sessions", con, if_exists="append", index=False)
        con.execute("INSERT INTO meta (key, value) VALUES ('seeded', '1')")
        con.commit()
    con.close()


def insert_session(start_time, end_time, profile_id, volume_step, max_step,
                   label="simulated"):
    con = get_con()
    con.execute(
        "INSERT INTO sessions (start_time, end_time, profile_id, volume_step, "
        "max_step, label) VALUES (?, ?, ?, ?, ?, ?)",
        (start_time, end_time, profile_id, volume_step, max_step, label))
    con.commit()
    con.close()


def read_sessions():
    con = get_con()
    df = pd.read_sql_query("SELECT * FROM sessions ORDER BY start_time", con,
                           parse_dates=["start_time", "end_time"])
    con.close()
    return df


def fired_thresholds(day):
    """Thresholds already fired on this day (so each fires only once)."""
    con = get_con()
    rows = con.execute("SELECT threshold FROM alerts WHERE fired_at LIKE ?",
                       (f"{day}%",)).fetchall()
    con.close()
    return {r[0] for r in rows}


def insert_alert(fired_at, threshold, message):
    con = get_con()
    con.execute("INSERT INTO alerts (fired_at, threshold, message) VALUES (?, ?, ?)",
                (fired_at, threshold, message))
    con.commit()
    con.close()


def read_alerts(limit=5):
    """Newest alerts first, as (fired_at, threshold, message)."""
    con = get_con()
    rows = con.execute("SELECT fired_at, threshold, message FROM alerts "
                       "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return rows


def delete_all():
    """Remove every session and alert. Sample data will NOT come back on restart."""
    con = get_con()
    con.execute("DELETE FROM sessions")
    con.execute("DELETE FROM alerts")
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seeded', '1')")
    con.commit()
    con.close()


def reload_samples(csv_path):
    """Delete everything, then load the sample sessions again (for demo resets)."""
    delete_all()
    con = get_con()
    pd.read_csv(csv_path).to_sql("sessions", con, if_exists="append", index=False)
    con.commit()
    con.close()
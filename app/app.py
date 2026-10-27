import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go

from src.level_estimator import estimate_level
from src.dose_calculator import dose_percent
from app import db

st.set_page_config(page_title="EchoGuard", layout="wide")
st.title("EchoGuard")
st.caption("Estimated exposure. Not a medical device.")

model = st.sidebar.selectbox("Reference model", ["niosh", "who"])
profile_id = st.sidebar.selectbox("Headphone profile", ["generic_earbuds"])

# --- Settings (the widgets live in the Settings tab; defaults are used until changed) ---
BREAK_MINUTES = st.session_state.get("break_minutes", 60)
THRESHOLDS = sorted({st.session_state.get("thr_1", 50),
                     st.session_state.get("thr_2", 80),
                     st.session_state.get("thr_3", 100)})


def safe_estimate(volume_step, max_step, profile_id):
    """Call the estimator, but return 'unavailable' when the volume is missing."""
    if pd.isna(volume_step) or pd.isna(max_step):
        return {"level_dba": None, "margin_db": None,
                "method": "none", "label": "unavailable"}
    return estimate_level(int(volume_step), int(max_step), profile_id)


# --- Load sessions and compute levels ---
csv_path = pathlib.Path(__file__).resolve().parent.parent / "data" / "sample_sessions.csv"
db.seed_from_csv_once(csv_path)
df = db.read_sessions()
has_data = not df.empty

if has_data:
    df["hours"] = (df.end_time - df.start_time).dt.total_seconds() / 3600

    est = [safe_estimate(r.volume_step, r.max_step, r.profile_id)
           for r in df.itertuples()]
    df["level_dba"] = pd.to_numeric(
        pd.Series([e["level_dba"] for e in est], index=df.index), errors="coerce")
    df["margin_db"] = pd.to_numeric(
        pd.Series([e["margin_db"] for e in est], index=df.index), errors="coerce")
    df["label"] = [e["label"] for e in est]

    # Dose for the most recent day in the data ("today")
    df["date"] = df.start_time.dt.date
    today = df["date"].max()
    today_df = df[df["date"] == today]

    known = today_df[today_df.level_dba.notna()]
    dose_known = not known.empty
    dose = (dose_percent(list(zip(known.level_dba, known.hours)), model)
            if dose_known else 0.0)
    unknown_hours = today_df.loc[today_df.level_dba.isna(), "hours"].sum()
    top = known.loc[known.level_dba.idxmax()] if dose_known else None
    labels_today = ", ".join(sorted(set(today_df.label)))


def gauge(dose, model):
    return go.Figure(go.Indicator(
        mode="gauge+number",
        value=min(dose, 150),
        number={"suffix": "%"},
        title={"text": f"Today's dose (%) - {model.upper()} reference"},
        gauge={"axis": {"range": [0, 150]},
               "bar": {"color": "#37474f"},
               "steps": [
                   {"range": [0, 50], "color": "#c8e6c9"},
                   {"range": [50, 80], "color": "#fff9c4"},
                   {"range": [80, 100], "color": "#ffe0b2"},
                   {"range": [100, 150], "color": "#ffcdd2"}]}))


# --- Alerts ---
def check_alerts(dose, fired, model, margin, label):
    new = []
    for limit in THRESHOLDS:
        if dose >= limit and limit not in fired:
            msg = (f"Your estimated exposure today reached {limit}% of the "
                   f"{model.upper()} reference limit ({label}, about ± {margin:.0f} dB). "
                   f"This is the total of all your listening today. "
                   f"Lowering the volume a few steps would slow it down.")
            new.append((limit, msg))
    for r in today_df.itertuples():
        minutes = r.hours * 60
        key = -r.session_id  # negative number = break reminder for that session
        if minutes > BREAK_MINUTES and key not in fired:
            msg = (f"Session {r.session_id} lasted {minutes:.0f} minutes, longer than "
                   f"your {BREAK_MINUTES}-minute limit. Long sessions add up your "
                   f"exposure. Taking a short break would reduce it.")
            new.append((key, msg))
        key = 1000 + r.session_id  # 1000+ = data-quality note for that session
        if pd.isna(r.level_dba) and key not in fired:
            msg = (f"Session {r.session_id} has no readable volume, so its sound level "
                   f"is unavailable (label: unavailable). It is not counted in your "
                   f"dose, so your real exposure may be higher than shown.")
            new.append((key, msg))
    return new


if has_data:
    day_str = str(today)
    fired = db.fired_thresholds(day_str)
    margin_for_alert = top.margin_db if top is not None else 0
    label_for_alert = top.label if top is not None else "unavailable"
    for threshold, msg in check_alerts(dose, fired, model,
                                       margin_for_alert, label_for_alert):
        db.insert_alert(f"{day_str} {datetime.now():%H:%M:%S}", threshold, msg)

tabs = st.tabs(["Today", "Timeline", "Sessions", "Simulator", "Settings", "About"])

with tabs[0]:
    if not has_data:
        st.info("No listening data yet. Add a session in the Simulator tab.")
    else:
        if unknown_hours > 0:
            st.warning(f"{unknown_hours:.1f} h of today's listening has an unavailable "
                       f"level. It is not included in the dose, so the dose shown is "
                       f"a lower bound.")

        if dose_known:
            if dose < 50:
                st.success(f"Status: your listening so far today is low compared with "
                           f"the {model.upper()} reference limit ({dose:.0f}%).")
            elif dose < 80:
                st.info(f"Status: you have used about {dose:.0f}% of today's "
                        f"{model.upper()} reference limit. Keep an eye on the volume.")
            elif dose < 100:
                st.warning(f"Status: you are close to today's {model.upper()} reference "
                           f"limit ({dose:.0f}%). Lowering the volume would slow it down.")
            else:
                st.error(f"Status: you have reached today's {model.upper()} reference "
                         f"limit ({dose:.0f}%). Consider lowering the volume or taking a break.")
        left, right = st.columns([2, 1])
        with left:
            if dose_known:
                st.plotly_chart(gauge(dose, model), use_container_width=True)
                st.write(f"Your estimated exposure today is {dose:.0f} percent "
                         f"of the {model.upper()} reference limit.")
            else:
                st.info("No level could be estimated for today's sessions, so no dose "
                        "can be shown (unavailable).")
            st.caption(f"Label: {labels_today}")
        with right:
            st.metric("Listening time today", f"{today_df.hours.sum():.1f} h")
            st.caption(f"Label: {labels_today}")
            st.metric("Sessions today", len(today_df))
            st.caption(f"Label: {labels_today}")
            if top is not None:
                st.metric("Highest estimated level",
                          f"{top.level_dba:.0f} dBA (± {top.margin_db:.0f} dB)")
                st.caption(f"Label: {top.label}")
            else:
                st.metric("Highest estimated level", "unavailable")
                st.caption("Label: unavailable")

        st.subheader("Recent alerts")
        recent = db.read_alerts(5)
        if not recent:
            st.info("No alerts yet.")
        for fired_at, threshold, message in recent:
            text = f"{fired_at[11:16]} | {message}"
            if 80 <= threshold < 1000:
                st.warning(text)
            else:
                st.info(text)

with tabs[1]:
    st.subheader("Estimated level over time")
    if not has_data:
        st.info("No listening data yet. Add a session in the Simulator tab.")
    else:
        days = sorted(df["date"].unique(), reverse=True)
        day = st.selectbox("Day", days)
        day_df = df[df["date"] == day]

        fig = go.Figure(go.Bar(
            x=day_df.start_time + (day_df.end_time - day_df.start_time) / 2,
            y=day_df.level_dba,
            width=(day_df.end_time - day_df.start_time).dt.total_seconds() * 1000,
            error_y=dict(type="data", array=day_df.margin_db),
            customdata=day_df[["label", "margin_db"]],
            hovertemplate="Level: %{y} dBA (± %{customdata[1]} dB)<br>"
                          "Label: %{customdata[0]}<extra></extra>",
            marker_color="#4f8bc9"))
        fig.update_layout(xaxis_title="Time of day",
                          yaxis_title="Estimated level (dBA)",
                          yaxis_range=[0, 110])
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Each bar is one session: its width is the duration, its height is "
                   "the estimated level, and the black line is the error margin. "
                   "Times with no bar are gaps, not zero.")
        n_missing = int(day_df.level_dba.isna().sum())
        if n_missing:
            st.info(f"{n_missing} session(s) on this day have an unavailable level "
                    f"and are shown as gaps.")

with tabs[2]:
    st.subheader("All sessions")
    if not has_data:
        st.info("No sessions saved. Add one in the Simulator tab.")
    else:
        table = df[["session_id", "start_time", "end_time"]].copy()
        table["duration_min"] = (df.hours * 60).round().astype(int)
        table["profile"] = df.profile_id
        table["level_dba"] = df.level_dba.apply(
            lambda v: "unavailable" if pd.isna(v) else f"{v:.0f}")
        table["margin_db"] = df.margin_db.apply(
            lambda v: "unavailable" if pd.isna(v) else f"{v:.0f}")
        table["label"] = df.label
        st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown("""
**What the labels mean**
- **measured**: taken from a direct measurement with a documented method
- **estimated**: calculated from a profile or model, with an error margin
- **simulated**: made by the demo or test data, not a real listening event
- **unavailable**: could not be obtained; shown as unknown, never as zero
""")

with tabs[3]:
    st.subheader("Simulator")
    st.warning("These are simulated listening events, not real phone data.")

    max_step = 15
    volume = st.slider("Volume step", 1, max_step, 8)
    minutes = st.number_input("Duration (minutes)", min_value=1, max_value=480,
                              value=30, step=5)
    unreadable = st.checkbox("Pretend the phone cannot read the volume "
                             "(level will be unavailable)")

    if unreadable:
        preview = {"level_dba": None, "margin_db": None, "label": "unavailable"}
        st.write("Estimated level: unavailable (label: unavailable)")
    else:
        preview = estimate_level(volume, max_step, profile_id)
        st.write(f"Estimated level at this volume: {preview['level_dba']:.0f} dBA "
                 f"(± {preview['margin_db']:.0f} dB), label: {preview['label']}")

    if st.button("Add session"):
        if has_data:
            start = df.end_time.max() + pd.Timedelta(minutes=5)
        else:
            start = pd.Timestamp.now().floor("min")
        end = start + pd.Timedelta(minutes=int(minutes))
        db.insert_session(start.strftime("%Y-%m-%d %H:%M"),
                          end.strftime("%Y-%m-%d %H:%M"),
                          profile_id,
                          None if unreadable else int(volume),
                          None if unreadable else max_step,
                          "simulated")
        if unreadable:
            st.session_state["sim_msg"] = (
                f"Added a {int(minutes)}-minute session with an unavailable level.")
        else:
            st.session_state["sim_msg"] = (
                f"Added a {int(minutes)}-minute session at about "
                f"{preview['level_dba']:.0f} dBA (± {preview['margin_db']:.0f} dB), "
                f"label: simulated.")
        st.rerun()

    if "sim_msg" in st.session_state:
        st.success(st.session_state["sim_msg"])
    if has_data and dose_known:
        st.write(f"Current dose today ({model.upper()}): {dose:.1f}%")

with tabs[4]:
    st.subheader("Settings")
    st.write(f"Active reference model: **{model.upper()}** (change it in the sidebar).")

    st.number_input("Break reminder after (minutes)", min_value=5, max_value=480,
                    value=60, step=5, key="break_minutes")

    st.write("Alert thresholds (percent of the daily reference limit):")
    c1, c2, c3 = st.columns(3)
    c1.number_input("Alert 1", min_value=1, max_value=300, value=50, key="thr_1")
    c2.number_input("Alert 2", min_value=1, max_value=300, value=80, key="thr_2")
    c3.number_input("Alert 3", min_value=1, max_value=300, value=100, key="thr_3")
    st.caption("Each alert fires once per day. Changes apply straight away.")

    st.divider()
    st.subheader("Your data")
    st.write("All data is stored on this computer only. Nothing is uploaded.")

    def _do_delete():
        db.delete_all()
        st.session_state["confirm_delete"] = False
        st.session_state.pop("sim_msg", None)
        st.session_state["data_msg"] = "All sessions and alerts were deleted."

    def _do_reload():
        db.reload_samples(csv_path)
        st.session_state.pop("sim_msg", None)
        st.session_state["data_msg"] = "Sample data loaded again (labelled simulated)."

    st.checkbox("Yes, I want to delete all sessions and alerts", key="confirm_delete")
    st.button("Delete all data",
              disabled=not st.session_state.get("confirm_delete", False),
              on_click=_do_delete)
    st.button("Load sample data again (demo reset)", on_click=_do_reload)

    if "data_msg" in st.session_state:
        st.success(st.session_state["data_msg"])

with tabs[5]:
    st.subheader("About EchoGuard")

    st.markdown("""
**What EchoGuard is.** EchoGuard estimates how loud your headphones are at your ears,
adds up your listening during the day, and compares the total with a documented
reference (NIOSH or WHO-ITU). It gives awareness and practical suggestions, such as
lowering the volume or taking a break.

**How the estimates are made.** EchoGuard uses your phone's volume step and a headphone
profile, which is a table that links each volume step to an estimated sound level in dBA.
Every level is an estimate with an error margin, shown as ± dB. Every number carries a
label: *measured*, *estimated*, *simulated* or *unavailable*. The data in this demo is
*simulated*. When a value cannot be obtained it is shown as *unavailable*, never as zero,
so your daily total may be lower than your real exposure.

**What EchoGuard is not.** Not a medical device. It does not diagnose hearing loss.
It is not a certified sound meter, and the dose percentage is a reference for awareness,
not a prediction for any one person. Your listening history stays on this computer and
no raw audio is saved.
""")

    st.caption("Reference models: NIOSH (85 dBA for 8 hours, 3 dB exchange rate) and "
               "WHO-ITU safe-listening reference (80 dBA for 40 hours per week).")
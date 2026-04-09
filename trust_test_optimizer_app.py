import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).with_name("trust_test_optimizer.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                question_text TEXT NOT NULL,
                tags TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                option_label TEXT NOT NULL CHECK(option_label IN ('A','B')),
                option_text TEXT NOT NULL,
                efficiency_delta REAL NOT NULL DEFAULT 0,
                reliability_delta REAL NOT NULL DEFAULT 0,
                agreeableness_delta REAL NOT NULL DEFAULT 0,
                UNIQUE(question_id, option_label),
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                notes TEXT DEFAULT '',
                started_at TEXT NOT NULL,
                final_score REAL,
                completed INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS run_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                chosen_label TEXT NOT NULL CHECK(chosen_label IN ('A','B')),
                shown_order INTEGER NOT NULL,
                answered_at TEXT NOT NULL,
                UNIQUE(run_id, question_id, shown_order),
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
                FOREIGN KEY(question_id) REFERENCES questions(id) ON DELETE CASCADE
            );
            """
        )


def fetch_questions(conn: sqlite3.Connection) -> pd.DataFrame:
    query = """
    SELECT q.id, q.title, q.question_text, q.tags, q.created_at,
           oa.option_text AS option_a_text,
           oa.efficiency_delta AS a_efficiency,
           oa.reliability_delta AS a_reliability,
           oa.agreeableness_delta AS a_agreeableness,
           ob.option_text AS option_b_text,
           ob.efficiency_delta AS b_efficiency,
           ob.reliability_delta AS b_reliability,
           ob.agreeableness_delta AS b_agreeableness
    FROM questions q
    LEFT JOIN options oa ON q.id = oa.question_id AND oa.option_label = 'A'
    LEFT JOIN options ob ON q.id = ob.question_id AND ob.option_label = 'B'
    ORDER BY q.id DESC
    """
    return pd.read_sql_query(query, conn)


def insert_question(conn: sqlite3.Connection, title: str, question_text: str, tags: str, option_a: dict, option_b: dict) -> None:
    now = datetime.utcnow().isoformat()
    with conn:
        cur = conn.execute(
            "INSERT INTO questions (title, question_text, tags, created_at) VALUES (?, ?, ?, ?)",
            (title.strip(), question_text.strip(), tags.strip(), now),
        )
        qid = cur.lastrowid
        conn.executemany(
            """
            INSERT INTO options (
                question_id, option_label, option_text,
                efficiency_delta, reliability_delta, agreeableness_delta
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (qid, "A", option_a["text"].strip(), option_a["eff"], option_a["rel"], option_a["agr"]),
                (qid, "B", option_b["text"].strip(), option_b["eff"], option_b["rel"], option_b["agr"]),
            ],
        )


def update_question(conn: sqlite3.Connection, qid: int, title: str, question_text: str, tags: str, option_a: dict, option_b: dict) -> None:
    with conn:
        conn.execute(
            "UPDATE questions SET title=?, question_text=?, tags=? WHERE id=?",
            (title.strip(), question_text.strip(), tags.strip(), qid),
        )
        for label, opt in [("A", option_a), ("B", option_b)]:
            conn.execute(
                """
                UPDATE options
                SET option_text=?, efficiency_delta=?, reliability_delta=?, agreeableness_delta=?
                WHERE question_id=? AND option_label=?
                """,
                (opt["text"].strip(), opt["eff"], opt["rel"], opt["agr"], qid, label),
            )


def delete_question(conn: sqlite3.Connection, qid: int) -> None:
    with conn:
        conn.execute("DELETE FROM questions WHERE id=?", (qid,))


def create_run(conn: sqlite3.Connection, name: str, notes: str = "") -> int:
    now = datetime.utcnow().isoformat()
    with conn:
        cur = conn.execute(
            "INSERT INTO runs (name, notes, started_at) VALUES (?, ?, ?)",
            (name.strip(), notes.strip(), now),
        )
        return int(cur.lastrowid)


def fetch_runs(conn: sqlite3.Connection) -> pd.DataFrame:
    query = """
    SELECT r.*,
           COUNT(ra.id) AS answer_count
    FROM runs r
    LEFT JOIN run_answers ra ON r.id = ra.run_id
    GROUP BY r.id
    ORDER BY r.id DESC
    """
    return pd.read_sql_query(query, conn)


def save_run_answer(conn: sqlite3.Connection, run_id: int, question_id: int, chosen_label: str) -> None:
    shown_order = conn.execute(
        "SELECT COALESCE(MAX(shown_order), 0) + 1 FROM run_answers WHERE run_id=?",
        (run_id,),
    ).fetchone()[0]
    now = datetime.utcnow().isoformat()
    with conn:
        conn.execute(
            """
            INSERT INTO run_answers (run_id, question_id, chosen_label, shown_order, answered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, question_id, chosen_label, shown_order, now),
        )


def complete_run(conn: sqlite3.Connection, run_id: int, final_score: float) -> None:
    with conn:
        conn.execute(
            "UPDATE runs SET final_score=?, completed=1 WHERE id=?",
            (final_score, run_id),
        )


def delete_run(conn: sqlite3.Connection, run_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM runs WHERE id=?", (run_id,))


def fetch_run_answers(conn: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    query = """
    SELECT ra.run_id, ra.question_id, ra.chosen_label, ra.shown_order, ra.answered_at,
           q.title, q.question_text,
           oa.option_text AS option_a_text,
           oa.efficiency_delta AS a_efficiency,
           oa.reliability_delta AS a_reliability,
           oa.agreeableness_delta AS a_agreeableness,
           ob.option_text AS option_b_text,
           ob.efficiency_delta AS b_efficiency,
           ob.reliability_delta AS b_reliability,
           ob.agreeableness_delta AS b_agreeableness
    FROM run_answers ra
    JOIN questions q ON q.id = ra.question_id
    LEFT JOIN options oa ON q.id = oa.question_id AND oa.option_label='A'
    LEFT JOIN options ob ON q.id = ob.question_id AND ob.option_label='B'
    WHERE ra.run_id=?
    ORDER BY ra.shown_order ASC
    """
    return pd.read_sql_query(query, conn, params=(run_id,))


def calculate_run_totals(run_answers_df: pd.DataFrame) -> dict:
    totals = {"efficiency": 0.0, "reliability": 0.0, "agreeableness": 0.0}
    if run_answers_df.empty:
        return totals
    for _, row in run_answers_df.iterrows():
        prefix = "a_" if row["chosen_label"] == "A" else "b_"
        totals["efficiency"] += row[f"{prefix}efficiency"]
        totals["reliability"] += row[f"{prefix}reliability"]
        totals["agreeableness"] += row[f"{prefix}agreeableness"]
    return totals


def fetch_recommendations(conn: sqlite3.Connection) -> pd.DataFrame:
    query = """
    WITH choice_scores AS (
        SELECT ra.question_id,
               ra.chosen_label,
               AVG(r.final_score) AS avg_score,
               COUNT(*) AS times_chosen
        FROM run_answers ra
        JOIN runs r ON r.id = ra.run_id
        WHERE r.completed = 1 AND r.final_score IS NOT NULL
        GROUP BY ra.question_id, ra.chosen_label
    )
    SELECT q.id AS question_id,
           q.title,
           q.question_text,
           COALESCE(a.avg_score, NULL) AS avg_score_a,
           COALESCE(a.times_chosen, 0) AS times_a,
           COALESCE(b.avg_score, NULL) AS avg_score_b,
           COALESCE(b.times_chosen, 0) AS times_b,
           CASE
               WHEN a.avg_score IS NULL AND b.avg_score IS NULL THEN 'No data yet'
               WHEN b.avg_score IS NULL THEN 'A'
               WHEN a.avg_score IS NULL THEN 'B'
               WHEN a.avg_score > b.avg_score THEN 'A'
               WHEN b.avg_score > a.avg_score THEN 'B'
               ELSE 'Tie'
           END AS recommended_choice
    FROM questions q
    LEFT JOIN choice_scores a ON q.id = a.question_id AND a.chosen_label = 'A'
    LEFT JOIN choice_scores b ON q.id = b.question_id AND b.chosen_label = 'B'
    ORDER BY q.id DESC
    """
    return pd.read_sql_query(query, conn)


def fetch_path_patterns(conn: sqlite3.Connection) -> pd.DataFrame:
    query = """
    SELECT ra1.question_id AS current_question_id,
           ra1.chosen_label AS current_choice,
           ra2.question_id AS next_question_id,
           COUNT(*) AS times_seen
    FROM run_answers ra1
    JOIN run_answers ra2
      ON ra1.run_id = ra2.run_id
     AND ra2.shown_order = ra1.shown_order + 1
    GROUP BY ra1.question_id, ra1.chosen_label, ra2.question_id
    ORDER BY times_seen DESC
    """
    return pd.read_sql_query(query, conn)


def pretty_delta(value: float) -> str:
    return f"+{value:g}" if value > 0 else f"{value:g}"


st.set_page_config(page_title="Trust Test Optimizer", layout="wide")
st.title("Trust Test Optimizer")
st.caption("Track visible needle movements, compare runs, and see which answers correlate with higher final scores.")

conn = get_conn()
init_db(conn)

page = st.sidebar.radio("Navigate", ["Question Library", "Run Tracker", "Recommendations", "Path Analysis"])

if page == "Question Library":
    st.header("Question Library")
    tab1, tab2 = st.tabs(["Add / Edit Question", "Browse Questions"])
    questions_df = fetch_questions(conn)

    with tab1:
        edit_mode = st.checkbox("Edit existing question")
        selected_row = None
        if edit_mode and not questions_df.empty:
            choice = st.selectbox(
                "Select question to edit",
                options=questions_df["id"].tolist(),
                format_func=lambda qid: f"#{qid} — {questions_df.loc[questions_df['id'] == qid, 'title'].iloc[0]}",
            )
            selected_row = questions_df[questions_df["id"] == choice].iloc[0]

        with st.form("question_form"):
            title = st.text_input("Short title", value="" if selected_row is None else selected_row["title"])
            question_text = st.text_area("Full question text", value="" if selected_row is None else selected_row["question_text"], height=120)
            tags = st.text_input("Tags (optional)", value="" if selected_row is None else selected_row["tags"])

            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Option A")
                a_text = st.text_area("Option A text", value="" if selected_row is None else selected_row["option_a_text"])
                a_eff = st.number_input("A: Efficiency delta", value=0.0 if selected_row is None else float(selected_row["a_efficiency"]), step=1.0)
                a_rel = st.number_input("A: Reliability delta", value=0.0 if selected_row is None else float(selected_row["a_reliability"]), step=1.0)
                a_agr = st.number_input("A: Agreeableness delta", value=0.0 if selected_row is None else float(selected_row["a_agreeableness"]), step=1.0)
            with col2:
                st.subheader("Option B")
                b_text = st.text_area("Option B text", value="" if selected_row is None else selected_row["option_b_text"])
                b_eff = st.number_input("B: Efficiency delta", value=0.0 if selected_row is None else float(selected_row["b_efficiency"]), step=1.0)
                b_rel = st.number_input("B: Reliability delta", value=0.0 if selected_row is None else float(selected_row["b_reliability"]), step=1.0)
                b_agr = st.number_input("B: Agreeableness delta", value=0.0 if selected_row is None else float(selected_row["b_agreeableness"]), step=1.0)

            if st.form_submit_button("Save question"):
                if not title.strip() or not question_text.strip() or not a_text.strip() or not b_text.strip():
                    st.error("Please fill in the title, question, and both options.")
                else:
                    option_a = {"text": a_text, "eff": a_eff, "rel": a_rel, "agr": a_agr}
                    option_b = {"text": b_text, "eff": b_eff, "rel": b_rel, "agr": b_agr}
                    if selected_row is None:
                        insert_question(conn, title, question_text, tags, option_a, option_b)
                        st.success("Question added.")
                    else:
                        update_question(conn, int(selected_row["id"]), title, question_text, tags, option_a, option_b)
                        st.success("Question updated.")
                    st.rerun()

        if edit_mode and selected_row is not None and st.button("Delete selected question"):
            delete_question(conn, int(selected_row["id"]))
            st.warning("Question deleted.")
            st.rerun()

    with tab2:
        if questions_df.empty:
            st.info("No questions yet.")
        else:
            search = st.text_input("Search")
            filtered = questions_df.copy()
            if search.strip():
                mask = (
                    filtered["title"].str.contains(search, case=False, na=False)
                    | filtered["question_text"].str.contains(search, case=False, na=False)
                    | filtered["tags"].str.contains(search, case=False, na=False)
                )
                filtered = filtered[mask]
            for _, row in filtered.iterrows():
                with st.expander(f"#{int(row['id'])} — {row['title']}"):
                    st.write(row["question_text"])
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**Option A**")
                        st.write(row["option_a_text"])
                        st.write(f"Efficiency: {pretty_delta(row['a_efficiency'])} | Reliability: {pretty_delta(row['a_reliability'])} | Agreeableness: {pretty_delta(row['a_agreeableness'])}")
                    with c2:
                        st.markdown("**Option B**")
                        st.write(row["option_b_text"])
                        st.write(f"Efficiency: {pretty_delta(row['b_efficiency'])} | Reliability: {pretty_delta(row['b_reliability'])} | Agreeableness: {pretty_delta(row['b_agreeableness'])}")

elif page == "Run Tracker":
    st.header("Run Tracker")
    runs_df = fetch_runs(conn)
    questions_df = fetch_questions(conn)
    left, right = st.columns([1, 2])

    with left:
        with st.form("new_run"):
            run_name = st.text_input("Run name", value=f"Run {len(runs_df) + 1}")
            run_notes = st.text_area("Notes")
            if st.form_submit_button("Create run") and run_name.strip():
                rid = create_run(conn, run_name, run_notes)
                st.success(f"Run created: #{rid}")
                st.rerun()

    with right:
        if runs_df.empty:
            st.info("Create a run first.")
        else:
            selected_run_id = st.selectbox(
                "Select run",
                options=runs_df["id"].tolist(),
                format_func=lambda rid: f"#{rid} — {runs_df.loc[runs_df['id'] == rid, 'name'].iloc[0]}",
            )
            run_row = runs_df[runs_df["id"] == selected_run_id].iloc[0]
            run_answers_df = fetch_run_answers(conn, int(selected_run_id))
            totals = calculate_run_totals(run_answers_df)

            c1, c2, c3 = st.columns(3)
            c1.metric("Efficiency total", f"{totals['efficiency']:+g}")
            c2.metric("Reliability total", f"{totals['reliability']:+g}")
            c3.metric("Agreeableness total", f"{totals['agreeableness']:+g}")

            if not int(run_row["completed"]):
                unanswered_qids = set(questions_df["id"].tolist()) - set(run_answers_df["question_id"].tolist())
                available_questions = questions_df[questions_df["id"].isin(unanswered_qids)]

                if not available_questions.empty:
                    qid = st.selectbox(
                        "Question shown next",
                        options=available_questions["id"].tolist(),
                        format_func=lambda q: f"#{q} — {available_questions.loc[available_questions['id'] == q, 'title'].iloc[0]}",
                    )
                    row = available_questions[available_questions["id"] == qid].iloc[0]
                    st.write(row["question_text"])
                    x1, x2 = st.columns(2)
                    with x1:
                        st.markdown("**A**")
                        st.write(row["option_a_text"])
                        st.caption(f"E {pretty_delta(row['a_efficiency'])} | R {pretty_delta(row['a_reliability'])} | A {pretty_delta(row['a_agreeableness'])}")
                    with x2:
                        st.markdown("**B**")
                        st.write(row["option_b_text"])
                        st.caption(f"E {pretty_delta(row['b_efficiency'])} | R {pretty_delta(row['b_reliability'])} | A {pretty_delta(row['b_agreeableness'])}")
                    chosen = st.radio("Chosen answer", ["A", "B"], horizontal=True)
                    if st.button("Save answer"):
                        save_run_answer(conn, int(selected_run_id), int(qid), chosen)
                        st.success("Answer saved.")
                        st.rerun()

                final_score = st.number_input("Final score", min_value=0.0, max_value=100.0, step=1.0)
                if st.button("Mark run as complete"):
                    complete_run(conn, int(selected_run_id), float(final_score))
                    st.success("Run completed.")
                    st.rerun()

            if run_answers_df.empty:
                st.info("No answers logged yet.")
            else:
                st.dataframe(run_answers_df[["shown_order", "title", "chosen_label", "answered_at"]], use_container_width=True)

elif page == "Recommendations":
    st.header("Recommendations")
    rec_df = fetch_recommendations(conn)
    q_df = fetch_questions(conn)
    if rec_df.empty:
        st.info("No data yet.")
    else:
        merged = rec_df.merge(q_df[["id", "option_a_text", "option_b_text"]], left_on="question_id", right_on="id", how="left")
        for _, row in merged.iterrows():
            with st.expander(f"#{int(row['question_id'])} — {row['title']} | Suggested: {row['recommended_choice']}"):
                st.write(row["question_text"])
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Option A**")
                    st.write(row["option_a_text"])
                    st.write(f"Avg final score: {row['avg_score_a'] if pd.notna(row['avg_score_a']) else 'No data'}")
                    st.write(f"Times chosen: {int(row['times_a'])}")
                with c2:
                    st.markdown("**Option B**")
                    st.write(row["option_b_text"])
                    st.write(f"Avg final score: {row['avg_score_b'] if pd.notna(row['avg_score_b']) else 'No data'}")
                    st.write(f"Times chosen: {int(row['times_b'])}")

else:
    st.header("Path Analysis")
    path_df = fetch_path_patterns(conn)
    q_df = fetch_questions(conn)
    if path_df.empty:
        st.info("No path data yet.")
    else:
        title_map = dict(zip(q_df["id"], q_df["title"]))
        view = path_df.copy()
        view["current_question"] = view["current_question_id"].map(title_map)
        view["next_question"] = view["next_question_id"].map(title_map)
        st.dataframe(view[["current_question", "current_choice", "next_question", "times_seen"]], use_container_width=True)

conn.close()

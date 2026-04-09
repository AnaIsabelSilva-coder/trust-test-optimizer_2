import streamlit as st
import sqlite3
import pandas as pd

conn = sqlite3.connect("data.db", check_same_thread=False)
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT,
    answer TEXT,
    score INTEGER
)
''')
conn.commit()

st.title("Trust Test Optimizer")

question = st.text_area("Question")
answer = st.selectbox("Answer", ["A", "B"])
score = st.number_input("Final Score", 0, 100, 0)

if st.button("Save"):
    c.execute("INSERT INTO runs (question, answer, score) VALUES (?, ?, ?)",
              (question, answer, score))
    conn.commit()
    st.success("Saved!")

df = pd.read_sql_query("SELECT * FROM runs", conn)
st.dataframe(df)

"""
Streamlit chat app for natural language queries over sales.db.

Reuses the Text-to-SQL pipeline from scripts/text_to_sql.py:
  question -> Claude -> SQL -> SQLite -> rows.

Run with:
    streamlit run app.py
"""

import os
import sys
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

# Make scripts/ importable so we can reuse the existing pipeline.
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

from text_to_sql import (  # noqa: E402
    ask_claude,
    extract_sql,
    is_select_only,
    run_sql,
)
from init_db import clean, load_csv, write_to_db  # noqa: E402


# Paths to the source CSV and the SQLite database.
CSV_PATH = os.path.join(PROJECT_ROOT, "data", "superstore.csv")
DB_PATH = os.path.join(PROJECT_ROOT, "data", "sales.db")


def ensure_database() -> None:
    """Build sales.db from superstore.csv if the database is missing.

    Runs the same pipeline as scripts/init_db.py (load CSV -> clean ->
    write to SQLite) so the app works on a fresh checkout without
    requiring the user to run the init script manually.
    """
    if os.path.exists(DB_PATH):
        return
    if not os.path.exists(CSV_PATH):
        raise FileNotFoundError(
            f"Cannot bootstrap database: source CSV not found at {CSV_PATH}"
        )
    df = load_csv()
    df = clean(df)
    write_to_db(df)


# Bootstrap the database at import time so every code path below
# (queries, schema display, etc.) can assume sales.db exists.
ensure_database()


# Schema description shown in the sidebar.
SCHEMA_DOC = """
**Table: `orders`**

| Column | Type | Description |
|---|---|---|
| row_id | INTEGER | Unique row id |
| order_id | TEXT | Order number |
| order_date | TEXT | Order date (YYYY-MM-DD) |
| ship_date | TEXT | Ship date (YYYY-MM-DD) |
| ship_mode | TEXT | Shipping mode |
| customer_id | TEXT | Customer id |
| customer_name | TEXT | Customer full name |
| segment | TEXT | Consumer / Corporate / Home Office |
| country | TEXT | Country |
| city | TEXT | City |
| state | TEXT | State or province |
| postal_code | TEXT | Postal code |
| region | TEXT | East / West / Central / South |
| product_id | TEXT | Product id |
| category | TEXT | Furniture / Office Supplies / Technology |
| sub_category | TEXT | Sub-category (Chairs, Phones, ...) |
| product_name | TEXT | Product name |
| sales | REAL | Sales amount (USD) |
"""

EXAMPLE_QUESTIONS = [
    "Top 10 customers by total sales",
    "Monthly sales in 2017",
    "Sales by region",
    "Top 5 sub-categories by sales in the West region",
]


def render_chart(df: pd.DataFrame):
    """Render a simple bar chart for the result DataFrame.

    Picks the first non-numeric column as the x-axis label and the first
    numeric column as the value. Returns None if no usable shape is found
    or the result has 1 or fewer rows.
    """
    if len(df) <= 1 or df.shape[1] < 2:
        return None

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        return None

    y_col = numeric_cols[0]
    label_candidates = [c for c in df.columns if c != y_col]
    if not label_candidates:
        return None
    x_col = label_candidates[0]

    # Cap to a reasonable number of bars so the chart stays readable.
    plot_df = df.head(30).copy()
    plot_df[x_col] = plot_df[x_col].astype(str)

    fig = px.bar(plot_df, x=x_col, y=y_col, title=f"{y_col} by {x_col}")
    fig.update_layout(
        xaxis_tickangle=-30,
        margin=dict(l=10, r=10, t=40, b=10),
        height=300,
    )
    return fig


def render_answer(answer: dict, key_prefix: str) -> None:
    """Render one assistant answer: SQL, table, chart, or error message."""
    if "error" in answer:
        st.error(answer["error"])
        if answer.get("sql"):
            st.markdown("**Generated SQL**")
            st.code(answer["sql"], language="sql")
        if answer.get("raw"):
            with st.expander("Raw model reply"):
                st.markdown(answer["raw"])
        return

    st.markdown("**Generated SQL**")
    st.code(answer["sql"], language="sql")

    df: pd.DataFrame = answer["df"]
    st.markdown(f"**Result** ({len(df)} row{'s' if len(df) != 1 else ''})")
    if df.empty:
        st.info("Query returned no rows.")
        return

    st.dataframe(df, use_container_width=True)

    if len(df) > 1:
        fig = render_chart(df)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_chart")
        else:
            st.caption("Chart skipped: no suitable numeric column to plot.")


def answer_question(question: str) -> dict:
    """Run the full Text-to-SQL pipeline and return a result dict."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"error": "ANTHROPIC_API_KEY is not set in the environment."}

    try:
        reply = ask_claude(question)
    except Exception as exc:  # noqa: BLE001 - surface any client error to the UI
        return {"error": f"Claude API call failed: {exc}"}

    sql = extract_sql(reply)
    if not sql:
        return {"error": "No SQL block found in the model reply.", "raw": reply}

    if not is_select_only(sql):
        return {
            "error": "Refused: only SELECT statements are allowed.",
            "sql": sql,
            "raw": reply,
        }

    try:
        columns, rows = run_sql(sql)
    except sqlite3.Error as exc:
        return {"error": f"SQLite error: {exc}", "sql": sql, "raw": reply}

    df = pd.DataFrame(rows, columns=columns)
    return {"sql": sql, "df": df, "raw": reply}


def main() -> None:
    st.set_page_config(page_title="Sales Q&A", page_icon=None, layout="wide")
    st.title("Sales Q&A")
    st.caption("Ask questions in natural language; Claude turns them into SQL.")

    # Sidebar: schema reference and controls.
    with st.sidebar:
        st.header("Database schema")
        st.markdown(SCHEMA_DOC)

        st.header("Examples")
        for q in EXAMPLE_QUESTIONS:
            st.markdown(f"- {q}")

        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.warning("Set the ANTHROPIC_API_KEY environment variable, then restart.")

        if st.button("Clear chat"):
            st.session_state.messages = []
            st.rerun()

    # Initialize chat history in session state.
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Replay prior turns.
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                render_answer(msg["content"], key_prefix=f"hist_{idx}")

    # Handle a new user question.
    question = st.chat_input("Ask about the sales data...")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            answer = answer_question(question)
        render_answer(answer, key_prefix=f"new_{len(st.session_state.messages)}")

    st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()

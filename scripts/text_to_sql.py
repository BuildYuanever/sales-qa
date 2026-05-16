"""
Text-to-SQL: convert a natural language question into a SQL query
and execute it against sales.db.

Usage:
    python scripts/text_to_sql.py "your question here"
"""

import os
import re
import sys
import sqlite3

import anthropic


# Project root = parent of the scripts/ directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# SQLite database file.
DB_PATH = os.path.join(PROJECT_ROOT, "data", "sales.db")

# Model name.
MODEL = "claude-sonnet-4-6"

# Custom API gateway base URL.
BASE_URL = "https://api.openox.tech"


SYSTEM_PROMPT = """You are a SQL assistant. Convert the user's natural language
question into a single SQLite SELECT query.

The database has exactly one table:

Table: orders

Columns:
  - row_id        INTEGER  unique row id
  - order_id      TEXT     order number
  - order_date    TEXT     order date in YYYY-MM-DD format
  - ship_date     TEXT     ship date in YYYY-MM-DD format
  - ship_mode     TEXT     shipping mode (e.g. Second Class, Standard Class)
  - customer_id   TEXT     customer id
  - customer_name TEXT     customer full name
  - segment       TEXT     customer segment (Consumer / Corporate / Home Office)
  - country       TEXT     country
  - city          TEXT     city
  - state         TEXT     state or province
  - postal_code   TEXT     postal code
  - region        TEXT     region (East / West / Central / South)
  - product_id    TEXT     product id
  - category      TEXT     product category (Furniture / Office Supplies / Technology)
  - sub_category  TEXT     product sub-category (e.g. Chairs, Phones)
  - product_name  TEXT     product name
  - sales         REAL     sales amount in USD

Rules:
1. Only generate SELECT queries. Never produce INSERT, UPDATE, DELETE, DROP,
   ALTER, CREATE, TRUNCATE, REPLACE, ATTACH, or DETACH statements.
2. Wrap the SQL in a fenced code block tagged ```sql ... ```.
3. Compare dates as strings in 'YYYY-MM-DD' format.
4. Round monetary aggregates to two decimals with ROUND(..., 2).
5. Add LIMIT when the question implies a small number of rows.
"""


def ask_claude(question: str) -> str:
    """Send the question to Claude and return the raw text reply."""
    client = anthropic.Anthropic(
        base_url=BASE_URL,
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )

    return response.content[0].text


def extract_sql(reply: str) -> str | None:
    """Extract a SQL statement from a Claude reply.

    Tries ```sql ... ``` first, then falls back to a generic ``` ... ``` block.
    """
    fenced_sql = re.search(r"```sql\s*(.*?)\s*```", reply, re.DOTALL | re.IGNORECASE)
    if fenced_sql:
        return fenced_sql.group(1).strip()

    fenced_any = re.search(r"```\s*(.*?)\s*```", reply, re.DOTALL)
    if fenced_any:
        return fenced_any.group(1).strip()

    return None


def is_select_only(sql: str) -> bool:
    """Return True only if the SQL is a single SELECT with no write keywords."""
    # Strip line comments and block comments before keyword scanning.
    cleaned = re.sub(r"--[^\n]*", "", sql)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    lowered = cleaned.strip().lower()

    if not lowered.startswith("select"):
        return False

    forbidden = (
        "insert", "update", "delete", "drop", "create",
        "alter", "truncate", "replace", "attach", "detach",
    )
    for word in forbidden:
        if re.search(rf"\b{word}\b", lowered):
            return False

    return True


def run_sql(sql: str) -> tuple[list[str], list[tuple]]:
    """Execute the SQL against sales.db and return (columns, rows)."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
    return columns, rows


def print_results(columns: list[str], rows: list[tuple]) -> None:
    """Print query results as an aligned text table."""
    if not rows:
        print("(no rows)")
        return

    widths = [len(str(c)) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    header = " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns))
    print(header)
    print("-" * len(header))

    for row in rows:
        print(" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(row)))

    print(f"\n{len(rows)} row(s)")


def main(question: str) -> None:
    print(f"\nQuestion: {question}")
    print("=" * 60)

    print("Calling Claude...")
    reply = ask_claude(question)
    print(f"\nClaude reply:\n{reply}\n")

    sql = extract_sql(reply)
    if not sql:
        print("Error: no SQL block found in the reply.")
        return

    print(f"Extracted SQL:\n{sql}\n")

    if not is_select_only(sql):
        print("Refused: only SELECT statements are allowed.")
        return

    print("Running SQL...")
    try:
        columns, rows = run_sql(sql)
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return

    print("\nResults:")
    print_results(columns, rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python scripts/text_to_sql.py "your question"')
        sys.exit(1)

    main(" ".join(sys.argv[1:]))

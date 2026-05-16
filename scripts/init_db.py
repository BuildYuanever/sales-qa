"""
init_db.py — 把 Superstore CSV 导入 SQLite 数据库

作用：这是整个项目的「地基」。
      只需要运行一次，之后所有查询都从数据库里取数据。

运行方式（在项目根目录执行）：
    python scripts/init_db.py
"""

import sqlite3       # Python 自带，不需要 pip install，用来操作数据库
import pandas        # 用来读取和清洗 CSV 文件
from pathlib import Path  # 用来处理文件路径，兼容 Windows/Mac/Linux


# ── 路径设置 ──────────────────────────────────────────────────────────────────
# Path(__file__) 是当前脚本的路径（scripts/init_db.py）
# .parent.parent 往上走两层，就是项目根目录（sales_qa/）
ROOT     = Path(__file__).parent.parent
CSV_PATH = ROOT / "data" / "superstore.csv"  # CSV 放在这里
DB_PATH  = ROOT / "data" / "sales.db"        # 数据库会自动生成在这里


# ── 第一步：读取 CSV ──────────────────────────────────────────────────────────
def load_csv() -> pandas.DataFrame:
    """
    pandas.read_csv() 把 CSV 读成一个 DataFrame（可以理解为内存里的 Excel 表格）。
    encoding="utf-8-sig" 兼容 Windows 导出的 CSV（会带一个隐藏的 BOM 字符）。
    """
    print(f"📂 读取 CSV：{CSV_PATH}")
    df = pandas.read_csv(CSV_PATH, encoding="utf-8-sig")
    print(f"   读取成功，共 {len(df)} 行，{len(df.columns)} 列")
    return df


# ── 第二步：清洗数据 ──────────────────────────────────────────────────────────
def clean(df: pandas.DataFrame) -> pandas.DataFrame:
    """
    清洗的目的：让数据格式统一，SQL 查询时不会出问题。

    主要做三件事：
    1. 日期格式标准化（"08/11/2017" → "2017-11-08"）
    2. 确保 Sales 是数字类型
    3. 列名统一用小写+下划线（方便写 SQL）
    """

    # 去掉列名里的多余空格
    df.columns = df.columns.str.strip()

    # 把日期转成 YYYY-MM-DD 格式
    # 为什么要这样？因为 SQLite 里日期是字符串，
    # YYYY-MM-DD 格式才能用 strftime() 函数做「按年/月统计」
    df["Order Date"] = pandas.to_datetime(
        df["Order Date"], format="%d/%m/%Y"
    ).dt.strftime("%Y-%m-%d")

    df["Ship Date"] = pandas.to_datetime(
        df["Ship Date"], format="%d/%m/%Y"
    ).dt.strftime("%Y-%m-%d")

    # 去掉 Sales 为空的行，转成浮点数
    df = df.dropna(subset=["Sales"])
    df["Sales"] = df["Sales"].astype(float)

    # 列名统一处理：
    # "Sub-Category" → "sub_category"（连字符也换成下划线）
    # 这样在 SQL 里直接写列名，不需要加引号
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace("-", "_")   # ← 重要：处理 "sub-category" 这种列名
    )

    print(f"   清洗完成，有效数据 {len(df)} 行")
    return df


# ── 第三步：写入数据库 ────────────────────────────────────────────────────────
def write_to_db(df: pandas.DataFrame) -> None:
    """
    SQLite 数据库 = data/ 文件夹里的一个 .db 文件。
    如果文件不存在，sqlite3.connect() 会自动创建它。
    """
    print(f"💾 写入数据库：{DB_PATH}")

    conn = sqlite3.connect(DB_PATH)

    # to_sql() 把整个 DataFrame 写成数据库里的 "orders" 表
    # if_exists="replace"：表已存在就先删掉，保证可以反复运行
    # index=False：不把 DataFrame 自带的行号写进去
    df.to_sql("orders", conn, if_exists="replace", index=False)

    # 建索引：让 SQL 查询更快
    # 没有索引 = 数据库每次查询都要扫描全部 9800 行
    # 有了索引 = 直接定位，快几十倍
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date     ON orders(order_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_region   ON orders(region)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON orders(category)")
    conn.commit()   # 提交，把改动正式存入文件
    conn.close()    # 关闭连接

    print(f"   写入成功！")


# ── 第四步：打印摘要确认 ──────────────────────────────────────────────────────
def print_summary() -> None:
    """
    跑几条 SQL，让你肉眼确认「数据确实进去了，而且是对的」。
    """
    conn = sqlite3.connect(DB_PATH)

    total_rows  = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    total_sales = conn.execute("SELECT SUM(sales) FROM orders").fetchone()[0]

    print(f"\n── 数据库摘要 ─────────────────────────────────")
    print(f"  总订单数：{total_rows:,} 条")
    print(f"  总销售额：${total_sales:,.0f}")

    print(f"\n── 各地区销售额 ───────────────────────────────")
    for region, total in conn.execute("""
        SELECT region, ROUND(SUM(sales), 0) AS total
        FROM orders GROUP BY region ORDER BY total DESC
    """).fetchall():
        print(f"  {region:<12} ${total:>10,.0f}")

    print(f"\n── 各产品类别销售额 ────────────────────────────")
    for cat, total in conn.execute("""
        SELECT category, ROUND(SUM(sales), 0) AS total
        FROM orders GROUP BY category ORDER BY total DESC
    """).fetchall():
        print(f"  {cat:<22} ${total:>10,.0f}")

    conn.close()


# ── 入口 ──────────────────────────────────────────────────────────────────────
# 只有「直接运行这个文件」时才执行；被 import 时不执行
if __name__ == "__main__":
    df = load_csv()
    df = clean(df)
    write_to_db(df)
    print_summary()
    print("\n🎉 第一阶段完成！接下来运行 python scripts/test_query.py 验证查询")

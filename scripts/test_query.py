"""
test_query.py — 用几条典型 SQL 验证数据库是否正常工作

作用：这是「冒烟测试」，确认数据库能被正确查询。
      同时这些 SQL 也是第二阶段 Claude 需要生成的样板。

运行方式：
    python scripts/test_query.py
"""

import sqlite3
from pathlib import Path

# 找到数据库文件的位置
DB_PATH = Path(__file__).parent.parent / "data" / "sales.db"

# 要测试的问题和对应的 SQL
# 格式：(自然语言问题, SQL语句)
# 这些 SQL 就是第二阶段 Claude 要帮我们自动生成的东西
TESTS = [
    (
        "哪个地区的总销售额最高？",
        """
        SELECT region, ROUND(SUM(sales), 0) AS total_sales
        FROM orders
        GROUP BY region
        ORDER BY total_sales DESC
        """,
    ),
    (
        "每年的销售额趋势是怎样的？",
        """
        SELECT strftime('%Y', order_date) AS year,
               ROUND(SUM(sales), 0) AS total_sales
        FROM orders
        GROUP BY year
        ORDER BY year
        """,
    ),
    (
        "哪个产品子类别卖得最好（Top 5）？",
        """
        SELECT sub_category, ROUND(SUM(sales), 0) AS total_sales
        FROM orders
        GROUP BY sub_category
        ORDER BY total_sales DESC
        LIMIT 5
        """,
    ),
    (
        "不同客户群体的平均订单金额？",
        """
        SELECT segment, COUNT(*) AS order_count,
               ROUND(AVG(sales), 2) AS avg_sales
        FROM orders
        GROUP BY segment
        ORDER BY avg_sales DESC
        """,
    ),
    (
        "哪种配送方式使用最多？",
        """
        SELECT ship_mode, COUNT(*) AS count
        FROM orders
        GROUP BY ship_mode
        ORDER BY count DESC
        """,
    ),
]


def run_tests() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 让结果可以用列名取值

    passed = 0
    for question, sql in TESTS:
        print(f"\n❓ {question}")
        try:
            rows = conn.execute(sql).fetchall()
            if rows:
                keys = rows[0].keys()
                header = " | ".join(f"{k:>18}" for k in keys)
                print(f"   {header}")
                print(f"   {'-' * len(header)}")
                for row in rows:
                    line = " | ".join(f"{str(row[k]):>18}" for k in keys)
                    print(f"   {line}")
                passed += 1
            else:
                print("   ⚠️  查询成功但无结果")
        except Exception as e:
            print(f"   ❌ 查询失败：{e}")

    conn.close()
    print(f"\n{'✅' if passed == len(TESTS) else '⚠️'} "
          f"{passed}/{len(TESTS)} 条查询通过")
    if passed == len(TESTS):
        print("数据库工作正常，可以进入第二阶段！")


if __name__ == "__main__":
    run_tests()

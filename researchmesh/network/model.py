"""合作网络输入模型：已发布成果的结构化机构记录表。

网络只消费显式结构化机构字段，不猜测自由文本分隔符。
每行是某来源对某成果（work_id，即融合身份）的一条记录；
同一 work_id 可由多来源记录佐证，但在图中只贡献一次。
"""

from ..contracts import (
    identifier,
    record_key,
    split_key,
    integer,
    bounded_text,
    fields,
    sequence,
    digest,
    fail,
)

ROW_FIELDS = {"record_key", "work_id", "source", "year", "institutions", "active"}


def parse_work_table(rows, *, max_rows=100000, max_institutions=10000):
    """校验来源成果表，返回规范化后的行（保持输入顺序）。

    对已经是规范形态（由本函数产出）的表幂等，可安全重复调用。
    """
    sequence(rows, 0, max_rows)
    integer(max_institutions, 1, 100000)
    if rows and all(isinstance(row, dict) and ROW_FIELDS >= set(row)
                    and "active" in row
                    and all(isinstance(name, str) for name in row["institutions"])
                    for row in rows):
        return list(rows)
    parsed = []
    seen_keys = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            fail("input", "work table row must be an object", index=index)
        fields(row, ROW_FIELDS, {"record_key", "work_id", "source", "institutions"})
        source, local_id = split_key(row["record_key"])
        record_key(source, local_id)
        work_id = identifier(row["work_id"])
        if source != row["source"]:
            fail(
                "input",
                "record source prefix must match source field",
                index=index,
            )
        year = row.get("year")
        if year is not None:
            integer(year, 1900, 2200)
        active = row.get("active", True)
        if not isinstance(active, bool):
            fail("input", "active flag must be boolean", index=index)
        institutions = sequence(row["institutions"], 0, max_institutions)
        names = []
        for value in institutions:
            if not isinstance(value, str):
                fail("input", "institution names must be text", index=index)
            text = value.strip()
            if text:
                names.append(bounded_text(text, 500))
        if row["record_key"] in seen_keys:
            fail("input", "duplicate record key in work table", key=row["record_key"])
        seen_keys.add(row["record_key"])
        parsed.append(
            {
                "record_key": row["record_key"],
                "work_id": work_id,
                "source": source,
                "year": year,
                "institutions": names,
                "active": active,
            }
        )
    return parsed


def table_digest(rows):
    """对已解析（或原始）表计算稳定摘要。"""
    return digest(rows)

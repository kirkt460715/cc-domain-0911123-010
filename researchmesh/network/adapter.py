"""从研合不可变发布版抽取网络输入。

网络分析只消费显式结构化机构名单：调用方必须提供 work_id -> 机构原文列表
的结构化映射（例如外部机构主数据），适配器不会对自由文本字段猜分隔符。
同一融合身份（master）下的每条来源记录生成一行，work_id 取 master 编号；
身份冲突的 master 标记为冲突行，建图时进入可追溯排除项。
"""

from ..contracts import digest, fail, bounded_text
from .model import parse_work_table


def work_table_from_release(release_payload, institution_members):
    """把发布 payload + 结构化机构名单转成网络成果表。

    institution_members 的键为来源记录键（source:local_id），
    值为该记录的结构化机构原文列表。
    """
    if not isinstance(release_payload, dict) or \
            release_payload.get("format_version") != 1:
        fail("version", "unsupported release payload")
    if not isinstance(institution_members, dict):
        fail("input", "institution_members must be an object")
    rows = []
    conflicts = []
    for master in release_payload["masters"]:
        work_id = master["id"]
        member_institutions = []
        for member in master["members"]:
            if member not in institution_members:
                fail(
                    "input",
                    "structured institution list missing for release member",
                    record=member,
                )
            names = institution_members[member]
            if not isinstance(names, list):
                fail("input", "institution member list must be a list",
                     record=member)
            names = [bounded_text(value, 500) for value in names]
            member_institutions.append(frozenset(names))
            rows.append(
                {
                    "record_key": member,
                    "work_id": work_id,
                    "source": member.split(":", 1)[0],
                    "year": master["data"].get("year"),
                    "institutions": names,
                    "active": True,
                }
            )
        if len(set(member_institutions)) > 1:
            conflicts.append(
                {
                    "work_id": work_id,
                    "records": list(master["members"]),
                    "reason": "conflicting_institution_set",
                }
            )
    return {
        "rows": parse_work_table(rows),
        "identity_conflicts": conflicts,
        "release_id": release_payload.get("id"),
        "input_digest": digest(rows),
    }

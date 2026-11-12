"""精确分数（Fraction）的 JSON 友好序列化。

权重的真值始终是 Fraction；``exact`` 字段保存分子/分母与分数字符串，
``decimal`` 仅用于展示，不参与任何计算，避免显示舍入污染结果。
"""

from fractions import Fraction
from ..contracts import fail


def to_rational(value):
    """把 int/Fraction/字符串统一转成非负 Fraction。"""
    if isinstance(value, bool):
        fail("input", "boolean is not a rational weight")
    if isinstance(value, Fraction):
        result = value
    elif isinstance(value, int):
        result = Fraction(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text or any(ch in text for ch in " \t\n"):
            fail("input", "invalid rational literal")
        try:
            result = Fraction(text)
        except (ValueError, ZeroDivisionError):
            fail("input", "invalid rational literal")
    else:
        fail("input", "rational number required")
    if result < 0:
        fail("input", "weights must be non-negative")
    return result


def rational_payload(value):
    """生成可复核的精确权重载荷。"""
    if not isinstance(value, Fraction):
        value = to_rational(value)
    return {
        "exact": str(value),
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": f"{float(value):.12g}",
    }


def rational_from_payload(payload):
    if not isinstance(payload, dict) or "exact" not in payload:
        fail("input", "rational payload requires exact field")
    return to_rational(payload["exact"])

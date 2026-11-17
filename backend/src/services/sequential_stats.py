import math
from scipy import stats

# 预注册分阶段检验：独立双组两比例，合并方差（pooled）双侧 z 检验。
# 每次查看只按该次预注册锁定的显著性额度 alpha_k 作临界判断；
# 同次检验始终对同一版数据执行，保证重试可复现。

def validate_count(value, label, limit=10_000_000):
    if isinstance(value, bool):
        raise ValueError(label + '必须为整数计数')
    if not isinstance(value, int):
        if isinstance(value, float) and math.isfinite(value) and float(value).is_integer():
            value = int(value)
        else:
            raise ValueError(label + '必须为非负整数')
    if value < 0 or value > limit:
        raise ValueError(label + '必须为 0 到 %d 的非负整数' % limit)
    return value


def validate_stage_counts(reach_a, click_a, reach_b, click_b):
    reach_a = validate_count(reach_a, 'A组累计触达')
    reach_b = validate_count(reach_b, 'B组累计触达')
    click_a = validate_count(click_a, 'A组累计点击')
    click_b = validate_count(click_b, 'B组累计点击')
    if reach_a <= 0 or reach_b <= 0:
        raise ValueError('双组累计触达必须为正整数')
    if click_a > reach_a:
        raise ValueError('A组累计点击不得超过累计触达')
    if click_b > reach_b:
        raise ValueError('B组累计点击不得超过累计触达')
    return reach_a, click_a, reach_b, click_b


def two_proportion_z_test(reach_a, click_a, reach_b, click_b, alpha_k):
    """双侧合并比例 z 检验，返回冻结的完整统计量。"""
    reach_a, click_a, reach_b, click_b = validate_stage_counts(
        reach_a, click_a, reach_b, click_b
    )
    if not isinstance(alpha_k, (int, float)) or not math.isfinite(float(alpha_k)):
        raise ValueError('显著性额度必须为有限数值')
    alpha_k = float(alpha_k)
    if not 0.0 < alpha_k < 1.0:
        raise ValueError('显著性额度必须位于 0 与 1 之间')
    p_a = click_a / reach_a
    p_b = click_b / reach_b
    pooled = (click_a + click_b) / (reach_a + reach_b)
    variance = pooled * (1.0 - pooled) * (1.0 / reach_a + 1.0 / reach_b)
    if variance <= 0.0:
        # 两组均为全点击或零点击，合并方差为 0，无法构造 z。
        z = 0.0
        p_value = 1.0
        se = 0.0
    else:
        se = math.sqrt(variance)
        z = (p_b - p_a) / se
        p_value = float(2.0 * stats.norm.sf(abs(z)))
    critical = float(stats.norm.ppf(1.0 - alpha_k / 2.0))
    significant = bool(p_value < alpha_k)
    return {
        'rate_a': p_a,
        'rate_b': p_b,
        'rate_diff': p_b - p_a,
        'pooled_rate': pooled,
        'z': float(z),
        'p_value': p_value,
        'critical_z': critical,
        'alpha_k': alpha_k,
        'significant': significant,
    }

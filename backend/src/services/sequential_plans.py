import math

# alpha 以百万分位整数存储与累加，避免浮点额度漂移导致总额越界。
ALPHA_SCALE = 1_000_000

def alpha_to_units(x):
    units = int(round(float(x) * ALPHA_SCALE))
    if units <= 0:
        raise ValueError('显著性额度过小，至少为 %.6f' % (1.0 / ALPHA_SCALE))
    return units

def units_to_alpha(units):
    return units / ALPHA_SCALE

def validate_plan_spec(alpha_total, looks):
    """预注册锁定校验：阶段连续、门槛递增、额度为正且总额不超过研究上限。"""
    if not isinstance(alpha_total, (int, float)) or not math.isfinite(float(alpha_total)):
        raise ValueError('研究显著性上限必须为有限数值')
    alpha_total = float(alpha_total)
    if not 0.0 < alpha_total <= 1.0:
        raise ValueError('研究显著性上限必须位于 0 与 1 之间')
    if not looks:
        raise ValueError('至少预注册一次查看')
    if len(looks) > 20:
        raise ValueError('小型研究最多预注册 20 次查看')
    stages = [int(l['stage']) for l in looks]
    if stages != list(range(1, len(looks) + 1)):
        raise ValueError('查看阶段必须从 1 开始连续编号，不得跳号或乱序')
    total_units = 0
    prev_reach_a = prev_reach_b = 0
    locked = []
    for i, look in enumerate(looks):
        reach_a = int(look['reach_a'])
        reach_b = int(look['reach_b'])
        alpha_k = float(look['alpha_k'])
        if reach_a <= 0 or reach_b <= 0:
            raise ValueError('第 %d 次查看的双组累计触达门槛必须为正' % (i + 1))
        if reach_a < prev_reach_a or reach_b < prev_reach_b:
            raise ValueError('第 %d 次查看的累计触达门槛不得低于前次（累计口径）' % (i + 1))
        if not math.isfinite(alpha_k) or not 0.0 < alpha_k < 1.0:
            raise ValueError('第 %d 次查看的显著性额度必须位于 0 与 1 之间' % (i + 1))
        units = alpha_to_units(alpha_k)
        total_units += units
        if total_units > alpha_to_units(alpha_total):
            raise ValueError('各次显著性额度合计 %.6f 超过研究上限 %.6f'
                             % (total_units / ALPHA_SCALE, alpha_total))
        locked.append({
            'stage': i + 1,
            'reach_a': reach_a,
            'reach_b': reach_b,
            'alpha_k': alpha_k,
            'alpha_units': units,
        })
        prev_reach_a, prev_reach_b = reach_a, reach_b
    return alpha_total, alpha_to_units(alpha_total), locked

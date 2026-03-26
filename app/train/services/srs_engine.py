from django.utils import timezone


def calculate_forget_score(memory):

    if not memory:
        return 999  # 新题优先级最高

    now = timezone.now()

    # =========================
    # 时间差（小时）
    # =========================
    if memory.next_review_at:
        hours = (now - memory.next_review_at).total_seconds() / 3600
    else:
        hours = 0

    hours = max(hours, 0)

    # =========================
    # 记忆等级（越高越不容易忘）
    # =========================
    level_factor = 1 / (memory.memory_level + 1)

    # =========================
    # 错误惩罚
    # =========================
    wrong_factor = 1 + memory.total_wrong * 0.3

    # =========================
    # 连续正确奖励
    # =========================
    streak_factor = 1 / (memory.correct_streak + 1)

    # =========================
    # 最终遗忘概率
    # =========================
    score = hours * level_factor * wrong_factor * streak_factor

    return score
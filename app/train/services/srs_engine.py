from datetime import timedelta

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


STRICT_CYCLE_MAX_STEP = 11


STRICT_STEP_RULES = {
    0: {"delay": None, "grace": None},
    1: {"delay": timedelta(minutes=5), "grace": timedelta(minutes=7)},
    2: {"delay": timedelta(minutes=30), "grace": timedelta(minutes=7)},
    3: {"delay": timedelta(hours=12), "grace": timedelta(minutes=7)},
    4: {"delay": timedelta(days=1), "grace": timedelta(days=1)},
    5: {"delay": timedelta(days=2), "grace": timedelta(days=1)},
    6: {"delay": timedelta(days=4), "grace": timedelta(days=1)},
    7: {"delay": timedelta(days=7), "grace": timedelta(days=1)},
    8: {"delay": timedelta(days=15), "grace": timedelta(days=1)},
    9: {"delay": timedelta(days=30), "grace": timedelta(days=1)},
    10: {"delay": timedelta(days=90), "grace": timedelta(days=1)},
    11: {"delay": timedelta(days=180), "grace": timedelta(days=1)},
}


def clamp_step(level):
    try:
        level = int(level or 0)
    except Exception:
        level = 0

    if level < 0:
        return 0

    if level > STRICT_CYCLE_MAX_STEP:
        return STRICT_CYCLE_MAX_STEP

    return level


def get_memory_step(memory):
    if not memory:
        return 0

    raw_level = getattr(memory, "cycle_step", None)
    if raw_level is None:
        raw_level = getattr(memory, "memory_level", 0)

    return clamp_step(raw_level)


def get_step_rule(level):
    level = clamp_step(level)
    return STRICT_STEP_RULES.get(
        level,
        STRICT_STEP_RULES[STRICT_CYCLE_MAX_STEP]
    )


def get_next_review(level, base_time=None):
    level = clamp_step(level)

    if base_time is None:
        base_time = timezone.now()

    rule = get_step_rule(level)
    delay = rule.get("delay")

    if not delay:
        return base_time

    return base_time + delay


def is_memory_overdue(memory, now=None):
    if not memory:
        return False

    if now is None:
        now = timezone.now()

    level = get_memory_step(memory)
    next_review_at = getattr(memory, "next_review_at", None)

    if level <= 0 or not next_review_at:
        return False

    grace = get_step_rule(level).get("grace")
    if not grace:
        return False

    return now > (next_review_at + grace)


def is_memory_mastered(memory):
    if not memory:
        return False

    level = get_memory_step(memory)
    next_review_at = getattr(memory, "next_review_at", None)
    mastered_at = getattr(memory, "mastered_at", None)

    if mastered_at:
        return True

    return level >= STRICT_CYCLE_MAX_STEP and next_review_at is None


def get_overdue_reset_reason(memory):
    if not memory:
        return ""

    level = get_memory_step(memory)

    if 1 <= level <= 3:
        return "short_overdue"

    if level >= 4:
        return "long_overdue"

    return ""

def is_slow_correct(is_correct, duration_seconds, item_type):
    """
    方案 A：
    慢答对只记录 slow_correct，不改变当前推进/重置主逻辑。

    判定规则：
    - 只有答对时才判断
    - 听说题先排除，不参与慢答对判定
    - read_cloze 阈值 12 秒
    - 其他非语音题阈值 8 秒
    """
    if not is_correct:
        return False

    if duration_seconds is None:
        return False

    try:
        duration_value = float(duration_seconds)
    except Exception:
        return False

    if duration_value <= 0:
        return False

    if item_type in {"listen_asr", "speak_read"}:
        return False

    threshold = 12.0 if item_type == "read_cloze" else 8.0
    return duration_value > threshold


def get_wrong_boost(memory):
    return getattr(memory, "wrong_boost", 0) or 0


def set_wrong_boost(memory, value):
    if hasattr(memory, "wrong_boost"):
        memory.wrong_boost = value


def set_last_wrong_at(memory, dt):
    if hasattr(memory, "last_wrong_at"):
        memory.last_wrong_at = dt


def update_memory_after_answer(memory, is_correct, duration_seconds=None, item_type="", used_hint=False):
    if not memory:
        return

    now = timezone.now()

    current_step = get_memory_step(memory)
    next_review_at = getattr(memory, "next_review_at", None)
    grace = get_step_rule(current_step).get("grace")

    is_overdue_reset = (
        current_step > 0
        and next_review_at is not None
        and grace is not None
        and now > (next_review_at + grace)
    )

    # 1) 先判定是否已经超窗
    if is_overdue_reset:
        memory.cycle_step = 0
        memory.memory_level = 0
        memory.correct_streak = 0
        memory.next_review_at = now
        memory.last_review_at = now
        memory.cycle_started_at = None
        memory.mastered_at = None
        memory.cycle_version = (getattr(memory, "cycle_version", 1) or 1) + 1
        memory.last_result = "overdue_reset"
        memory.last_reset_reason = get_overdue_reset_reason(memory)
        memory.save()
        return

    # 2) 正确：严格按 step 推进
    if is_correct:
        memory.correct_streak = (getattr(memory, "correct_streak", 0) or 0) + 1
        memory.total_correct = (getattr(memory, "total_correct", 0) or 0) + 1
        set_wrong_boost(memory, 0)

        if used_hint:
            memory.last_result = "hint_correct"
        elif is_slow_correct(is_correct, duration_seconds, item_type):
            memory.last_result = "slow_correct"
        else:
            memory.last_result = "correct"

        memory.last_reset_reason = ""

        if current_step == 0:
            memory.cycle_started_at = now
            next_step = 1
        else:
            next_step = current_step + 1

        if next_step > STRICT_CYCLE_MAX_STEP:
            next_step = STRICT_CYCLE_MAX_STEP
            memory.cycle_step = STRICT_CYCLE_MAX_STEP
            memory.memory_level = STRICT_CYCLE_MAX_STEP
            memory.mastered_at = now
            memory.next_review_at = None
            memory.last_result = "mastered"
        else:
            memory.cycle_step = next_step
            memory.memory_level = next_step
            memory.mastered_at = None
            memory.next_review_at = get_next_review(next_step, base_time=now)

    # 3) 错误：当前循环直接重置
    else:
        memory.cycle_step = 0
        memory.memory_level = 0
        memory.correct_streak = 0
        memory.total_wrong = (getattr(memory, "total_wrong", 0) or 0) + 1
        set_wrong_boost(memory, min(get_wrong_boost(memory) + 3, 10))
        set_last_wrong_at(memory, now)
        memory.next_review_at = now
        memory.cycle_started_at = None
        memory.mastered_at = None
        memory.cycle_version = (getattr(memory, "cycle_version", 1) or 1) + 1
        memory.last_result = "wrong_reset"
        memory.last_reset_reason = "wrong_answer"

    memory.last_review_at = now
    memory.save()


def manual_adjust_memory(memory, action):
    """
    手动调整记忆等级（v1）
    - 只允许 upgrade: 当前 step + 1

    保留现有严格艾宾浩斯自动规则不变：
    后续答错 / 超窗，仍然会按原逻辑自动 reset。
    """
    if not memory:
        return

    now = timezone.now()
    current_step = get_memory_step(memory)

    if action == "upgrade":
        next_step = min(current_step + 1, STRICT_CYCLE_MAX_STEP)

        memory.cycle_step = next_step
        memory.memory_level = next_step
        memory.last_result = "manual_upgrade"
        memory.last_reset_reason = ""

        if next_step <= 0:
            memory.next_review_at = now
            memory.mastered_at = None
        elif next_step >= STRICT_CYCLE_MAX_STEP:
            memory.mastered_at = now
            memory.next_review_at = None
        else:
            memory.mastered_at = None
            memory.next_review_at = get_next_review(next_step, base_time=now)

        if current_step == 0 and next_step > 0 and not getattr(memory, "cycle_started_at", None):
            memory.cycle_started_at = now

    else:
        raise ValueError(f"unsupported manual action: {action}")

    memory.last_review_at = now
    memory.save()
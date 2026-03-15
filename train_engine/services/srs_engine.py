from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

from .srs_config import (
    SRS_INTERVALS,
    NEW_LEVEL,
    MASTERED_LEVEL,
    SHORT_LEVELS,
    LONG_LEVELS,
    SHORT_OVERDUE_GRACE,
    LONG_OVERDUE_GRACE,
)


@dataclass
class ReviewResult:
    correct: bool
    old_level: int
    new_level: int
    next_review: Optional[object]
    was_reset: bool
    reset_reason: Optional[str]
    is_mastered: bool
    is_overdue: bool
    status_message: str


def get_interval_for_level(level: int):
    """
    根据 level 返回对应的复习间隔。
    """
    return SRS_INTERVALS.get(level)


def calculate_next_review(level: int, now=None):
    """
    计算某个 level 的下次复习时间。
    """
    if now is None:
        now = timezone.now()

    interval = get_interval_for_level(level)
    if interval is None:
        return None

    return now + interval


def get_level_name(level: int) -> str:
    """
    返回 level 的文字名称，给前端展示用。
    """
    mapping = {
        0: "new",
        1: "short_1",
        2: "short_2",
        3: "short_3",
        4: "long_1",
        5: "long_2",
        6: "long_3",
        7: "long_4",
        8: "long_5",
        9: "long_6",
        10: "long_7",
        11: "long_8",
        12: "mastered",
    }
    return mapping.get(level, f"level_{level}")


def get_due_status(memory, now=None) -> str:
    """
    返回当前记忆状态：
    - new
    - waiting
    - due
    - overdue
    - mastered
    """
    if now is None:
        now = timezone.now()

    if memory.memory_level >= MASTERED_LEVEL:
        return "mastered"

    if not memory.next_review:
        return "new"

    if is_overdue(memory, now=now):
        return "overdue"

    if now >= memory.next_review:
        return "due"

    return "waiting"


def is_overdue(memory, now=None) -> bool:
    """
    判断当前 memory 是否过期：
    - short: 到期后超过 7 分钟
    - long: 到期后超过 1 天
    """
    if now is None:
        now = timezone.now()

    if not memory.next_review:
        return False

    level = memory.memory_level

    if level in SHORT_LEVELS:
        return now > (memory.next_review + SHORT_OVERDUE_GRACE)

    if level in LONG_LEVELS:
        return now > (memory.next_review + LONG_OVERDUE_GRACE)

    return False


def start_new_cycle(memory, now=None):
    """
    启动新的短期循环：
    level = 1
    """
    if now is None:
        now = timezone.now()

    memory.memory_level = 1
    memory.cycle_started = now
    memory.last_review = now
    memory.next_review = calculate_next_review(1, now=now)
    memory.mastered_at = None


def reset_by_wrong(memory, now=None):
    """
    因答错而重置到 level 1。
    """
    if now is None:
        now = timezone.now()

    memory.wrong_reset_count += 1
    start_new_cycle(memory, now=now)


def reset_by_overdue(memory, now=None):
    """
    因过期而重置到 level 1。
    """
    if now is None:
        now = timezone.now()

    memory.overdue_reset_count += 1
    start_new_cycle(memory, now=now)


def advance_level(memory, now=None):
    """
    正确作答后推进 level。
    """
    if now is None:
        now = timezone.now()

    old_level = memory.memory_level

    # level 0 或异常状态，先进入 short_1
    if old_level <= 0:
        memory.memory_level = 1
        memory.cycle_started = now
        memory.last_review = now
        memory.next_review = calculate_next_review(1, now=now)
        return

    new_level = old_level + 1

    memory.memory_level = new_level
    memory.last_review = now

    if new_level >= MASTERED_LEVEL:
        memory.memory_level = MASTERED_LEVEL
        memory.next_review = None
        memory.mastered_at = now
        return

    memory.next_review = calculate_next_review(new_level, now=now)


def ensure_memory_started(memory, now=None):
    """
    确保 memory 至少有一个合法起点。
    """
    if now is None:
        now = timezone.now()

    if memory.memory_level <= 0 or memory.next_review is None:
        start_new_cycle(memory, now=now)


def review(memory, is_correct: bool, now=None) -> ReviewResult:
    """
    处理一次复习结果。

    规则：
    1. 如果已过期，先判定 overdue，并重置。
    2. 如果未过期但答错，重置。
    3. 如果答对，推进等级。
    """
    if now is None:
        now = timezone.now()

    old_level = memory.memory_level or 0
    memory.review_count += 1

    # 未开始时，先建立起点
    if old_level == NEW_LEVEL and memory.next_review is None:
        if is_correct:
            # 初次学习视作进入 short_1
            start_new_cycle(memory, now=now)
            result = ReviewResult(
                correct=is_correct,
                old_level=old_level,
                new_level=memory.memory_level,
                next_review=memory.next_review,
                was_reset=False,
                reset_reason=None,
                is_mastered=False,
                is_overdue=False,
                status_message="已开始新的记忆循环，下一次复习为 5 分钟后。",
            )
            return result
        else:
            # 初次学习就失败，也进入 short_1
            reset_by_wrong(memory, now=now)
            result = ReviewResult(
                correct=is_correct,
                old_level=old_level,
                new_level=memory.memory_level,
                next_review=memory.next_review,
                was_reset=True,
                reset_reason="wrong",
                is_mastered=False,
                is_overdue=False,
                status_message="本次未通过，已重新开始新的 5 分钟循环。",
            )
            return result

    # 已过期优先处理
    overdue = is_overdue(memory, now=now)
    if overdue:
        reset_by_overdue(memory, now=now)
        return ReviewResult(
            correct=is_correct,
            old_level=old_level,
            new_level=memory.memory_level,
            next_review=memory.next_review,
            was_reset=True,
            reset_reason="overdue",
            is_mastered=False,
            is_overdue=True,
            status_message="复习已过期，当前记忆链条已失效，已重新开始新的 5 分钟循环。",
        )

    # 未过期但答错
    if not is_correct:
        reset_by_wrong(memory, now=now)
        return ReviewResult(
            correct=is_correct,
            old_level=old_level,
            new_level=memory.memory_level,
            next_review=memory.next_review,
            was_reset=True,
            reset_reason="wrong",
            is_mastered=False,
            is_overdue=False,
            status_message="本次回答错误，已重新开始新的 5 分钟循环。",
        )

    # 正确推进
    advance_level(memory, now=now)

    if memory.memory_level >= MASTERED_LEVEL:
        return ReviewResult(
            correct=is_correct,
            old_level=old_level,
            new_level=memory.memory_level,
            next_review=memory.next_review,
            was_reset=False,
            reset_reason=None,
            is_mastered=True,
            is_overdue=False,
            status_message="恭喜，当前知识点已完成全部记忆周期。",
        )

    return ReviewResult(
        correct=is_correct,
        old_level=old_level,
        new_level=memory.memory_level,
        next_review=memory.next_review,
        was_reset=False,
        reset_reason=None,
        is_mastered=False,
        is_overdue=False,
        status_message=f"本轮通过，已进入 {get_level_name(memory.memory_level)}，请按时进行下一次复习。",
    )


def serialize_memory(memory):
    """
    给前端返回统一结构。
    """
    return {
        "level": memory.memory_level,
        "level_name": get_level_name(memory.memory_level),
        "next_review": (
            timezone.localtime(memory.next_review).strftime("%Y-%m-%d %H:%M")
            if memory.next_review
            else None
        ),
        "last_review": (
            timezone.localtime(memory.last_review).strftime("%Y-%m-%d %H:%M")
            if memory.last_review
            else None
        ),
        "due_status": get_due_status(memory),
        "wrong_reset_count": memory.wrong_reset_count,
        "overdue_reset_count": memory.overdue_reset_count,
        "review_count": memory.review_count,
        "is_mastered": memory.memory_level >= MASTERED_LEVEL,
    }
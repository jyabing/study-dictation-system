from datetime import timedelta


# =========================
# 基础 level 定义
# =========================

NEW_LEVEL = 0
MASTERED_LEVEL = 12


# =========================
# 短期记忆 level
# =========================

SHORT_LEVELS = {1, 2, 3}


# =========================
# 长期记忆 level
# =========================

LONG_LEVELS = {4, 5, 6, 7, 8, 9, 10, 11}


# =========================
# SRS 间隔表
# level → timedelta
# =========================

SRS_INTERVALS = {

    # 短期
    1: timedelta(minutes=5),
    2: timedelta(minutes=30),
    3: timedelta(hours=12),

    # 长期
    4: timedelta(days=1),
    5: timedelta(days=2),
    6: timedelta(days=4),
    7: timedelta(days=7),
    8: timedelta(days=15),
    9: timedelta(days=30),
    10: timedelta(days=90),
    11: timedelta(days=180),
}


# =========================
# 过期宽限
# =========================

SHORT_OVERDUE_GRACE = timedelta(minutes=7)

LONG_OVERDUE_GRACE = timedelta(days=1)
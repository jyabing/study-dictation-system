from django.db import models
from django.contrib.auth.models import User


# =========================
# 📘 Book（书册）
# =========================
class Book(models.Model):

    owner = models.ForeignKey(User, on_delete=models.CASCADE)

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.title


# =========================
# 📖 Lesson（章节）
# =========================
class Lesson(models.Model):

    book = models.ForeignKey(Book, on_delete=models.CASCADE)

    title = models.CharField(max_length=200)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


# =========================
# ❗（旧）Question（暂时保留，用于迁移）
# =========================
class Question(models.Model):

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    prompt_text = models.TextField()
    answer_text = models.TextField()

    audio_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return self.prompt_text[:50]


# =========================
# 🧠 MemoryItem（核心知识层）
# =========================
class MemoryItem(models.Model):
    """
    一个知识点（词 / 句 / 短语）
    可以派生多个 TrainingItem（题型）
    """

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)

    prompt_text = models.TextField()
    answer_text = models.TextField()

    audio_url = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.prompt_text[:50]


# =========================
# 🎯 TrainingItem（题型层）
# =========================
class TrainingItem(models.Model):

    TYPE_CHOICES = [
        ("listen", "听"),
        ("speak", "说"),
        ("read_cloze", "读-填空"),
        ("read_choice", "读-选择"),
        ("write", "写"),
    ]

    # ✅ 新结构：绑定 MemoryItem
    question = models.ForeignKey(
        "Question",
        on_delete=models.CASCADE,
        related_name="training_items"
    )

    item_type = models.CharField(max_length=20, choices=TYPE_CHOICES)

    # Cloze
    cloze_text = models.TextField(blank=True, null=True)
    cloze_answers = models.JSONField(blank=True, null=True)

    # Choice
    choices = models.JSONField(blank=True, null=True)
    correct_answers = models.JSONField(blank=True, null=True)

    # 通用
    prompt_text = models.TextField(blank=True, null=True)
    reveal_text_on_wrong = models.BooleanField(default=False)

    audio_file = models.FileField(upload_to="audio/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"M{self.question_id} - {self.item_type}"


# =========================
# 🧠 QuestionMemory（SRS记忆层）
# =========================
class QuestionMemory(models.Model):

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # ❗旧字段（暂时保留，用于迁移）
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    memory_level = models.IntegerField(default=0)

    # =========================
    # 🔥 插入这里 ↓↓↓
    # =========================
    wrong_boost = models.IntegerField(default=0)
    last_wrong_at = models.DateTimeField(null=True, blank=True)
    # =========================

    # =========================
    # P0：严格艾宾浩斯循环字段（兼容扩展）
    # 先加字段，不删除旧逻辑字段
    # 下一步由 train_views.py 同步写入
    # =========================
    cycle_step = models.PositiveSmallIntegerField(default=0)
    cycle_started_at = models.DateTimeField(null=True, blank=True)
    cycle_version = models.PositiveIntegerField(default=1)

    mastered_at = models.DateTimeField(null=True, blank=True)

    last_result = models.CharField(
        max_length=20,
        blank=True,
        default=""
    )

    last_reset_reason = models.CharField(
        max_length=30,
        blank=True,
        default=""
    )

    next_review_at = models.DateTimeField(null=True, blank=True)

    correct_streak = models.IntegerField(default=0)
    total_correct = models.IntegerField(default=0)
    total_wrong = models.IntegerField(default=0)

    last_review_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} - T{self.item_id or 'OLD'}"


# =========================
# 🏆 UserProfile（XP + 等级 + streak）
# =========================
class UserProfile(models.Model):

    user = models.OneToOneField(User, on_delete=models.CASCADE)

    xp = models.IntegerField(default=0)
    level = models.IntegerField(default=1)

    streak = models.IntegerField(default=0)
    last_study_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} (Lv{self.level})"
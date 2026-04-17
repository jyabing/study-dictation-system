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
# 🎯 TrainingItem（训练主表 + 题型兼容层）
# =========================
class TrainingItem(models.Model):

    TYPE_CHOICES = [
        ("listen", "听"),
        ("speak", "说"),
        ("read_cloze", "读-填空"),
        ("read_choice", "读-选择"),
        ("write", "写"),
    ]

    GRADING_MODE_CHOICES = [
        ("strict", "严格匹配"),
        ("normalize", "归一化匹配"),
        ("multi_answer", "多答案匹配"),
        ("keyword", "关键词匹配"),
    ]

    ANSWER_TYPE_CHOICES = [
        ("translation", "翻译"),
        ("polite_expression", "敬语表达"),
        ("tense_person_conversion", "时态/人称转换"),
        ("literary_expression", "文学表达"),
        ("fixed_expression", "固定表达"),
        ("general_response", "一般回答"),
    ]

    LANGUAGE_CHOICES = [
        ("ja", "日语"),
        ("en", "英语"),
        ("zh", "中文"),
        ("mixed", "混合"),
    ]

    CLOZE_MODE_CHOICES = [
        ("manual_only", "仅人工克漏字"),
        ("auto_only", "仅自动克漏字"),
        ("manual_first", "人工优先，自动补充"),
    ]

    MODE_CHOICES = [
        ("listen", "听力转换"),
        ("speak", "口说作答"),
        ("write", "输入作答"),
        ("cloze", "克漏字"),
        ("shadow", "跟读"),
        ("choice", "选择题"),
    ]

    # =========================
    # 旧结构（保留兼容）
    # =========================
    question = models.ForeignKey(
        "Question",
        on_delete=models.CASCADE,
        related_name="training_items"
    )

    item_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES
    )

    cloze_text = models.TextField(blank=True, null=True)
    cloze_answers = models.JSONField(blank=True, null=True)

    choices = models.JSONField(blank=True, null=True)
    correct_answers = models.JSONField(blank=True, null=True)

    prompt_text = models.TextField(blank=True, null=True)
    reveal_text_on_wrong = models.BooleanField(default=False)

    audio_file = models.FileField(
        upload_to="audio/",
        blank=True,
        null=True
    )

    answer_audio_file = models.FileField(
        upload_to="audio/answers/",
        blank=True,
        null=True
    )

    answer_use_tts = models.BooleanField(
        default=False
    )

    # =========================
    # 新结构：提示短语 + 题干 + 回答
    # =========================
    instruction_text = models.TextField(
        blank=True,
        default=""
    )

    source_text = models.TextField(
        blank=True,
        default=""
    )

    target_answer = models.TextField(
        blank=True,
        default=""
    )

    # =========================
    # 判题与解释
    # =========================
    accepted_answers = models.JSONField(
        blank=True,
        default=list
    )

    explanation = models.TextField(
        blank=True,
        default=""
    )

    grading_mode = models.CharField(
        max_length=30,
        choices=GRADING_MODE_CHOICES,
        default="normalize"
    )

    # =========================
    # 训练控制
    # =========================
    answer_type = models.CharField(
        max_length=50,
        choices=ANSWER_TYPE_CHOICES,
        default="general_response"
    )

    language = models.CharField(
        max_length=20,
        choices=LANGUAGE_CHOICES,
        default="ja"
    )

    enabled_modes = models.JSONField(
        blank=True,
        default=list
    )

    difficulty = models.PositiveSmallIntegerField(
        default=1
    )

    # =========================
    # 音频与克漏字增强
    # =========================
    source_audio = models.FileField(
        upload_to="audio/source/",
        blank=True,
        null=True
    )

    target_audio = models.FileField(
        upload_to="audio/target/",
        blank=True,
        null=True
    )

    manual_cloze_text = models.TextField(
        blank=True,
        default=""
    )

    cloze_mode = models.CharField(
        max_length=20,
        choices=CLOZE_MODE_CHOICES,
        default="manual_first"
    )

    auto_cloze_enabled = models.BooleanField(
        default=True
    )

    # =========================
    # 管理字段
    # =========================
    tags = models.JSONField(
        blank=True,
        default=list
    )

    source_reference = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )

    notes = models.TextField(
        blank=True,
        default=""
    )

    is_active = models.BooleanField(
        default=True
    )

    sort_order = models.IntegerField(
        default=0
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.instruction_text and self.source_text:
            return f"{self.instruction_text[:20]} | {self.source_text[:20]}"
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
    
# =========================
# 📝 StudyLog（学习行为日志）
# =========================
class StudyLog(models.Model):

    MODE_CHOICES = [
        ("normal", "Normal"),
        ("wrong_word_replay", "Wrong Word Replay"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_logs")

    question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="study_logs"
    )

    training_item = models.ForeignKey(
        TrainingItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="study_logs"
    )

    is_correct = models.BooleanField(default=False)

    user_answer = models.TextField(blank=True, default="")

    mode = models.CharField(
        max_length=30,
        choices=MODE_CHOICES,
        default="normal"
    )

    duration_ms = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        result = "correct" if self.is_correct else "wrong"
        return f"{self.user.username} - {result} - {self.created_at:%Y-%m-%d %H:%M:%S}"
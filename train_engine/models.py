from django.db import models
from django.utils import timezone


# =========================
# Course
# =========================
class Course(models.Model):

    name = models.CharField(
        "课程名称",
        max_length=200
    )

    name_en = models.CharField(
        "课程英文名",
        max_length=200,
        blank=True,
        null=True
    )

    description = models.TextField(
        "课程描述",
        blank=True
    )

    class Meta:
        verbose_name = "Course / 课程"
        verbose_name_plural = "Courses / 课程"
        ordering = ["id"]

    def __str__(self):
        return self.name or ""


# =========================
# Lesson
# =========================
class Lesson(models.Model):

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="lessons",
        verbose_name="所属课程"
    )

    title = models.CharField(
        "章节标题",
        max_length=200
    )

    title_en = models.CharField(
        "章节英文标题",
        max_length=200,
        blank=True,
        null=True
    )

    order = models.IntegerField(
        "排序",
        default=0
    )

    class Meta:
        verbose_name = "Lesson / 章节"
        verbose_name_plural = "Lessons / 章节"
        ordering = ["order", "id"]

    def __str__(self):
        return self.title or ""


# =========================
# Sentence（知识点 / 原句）
# =========================
class Sentence(models.Model):

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="sentences",
        verbose_name="所属章节"
    )

    text = models.TextField(
        "原句"
    )

    translation = models.TextField(
        "翻译",
        blank=True
    )

    audio = models.FileField(
        "音频",
        upload_to="audio/",
        blank=True,
        null=True
    )

    difficulty = models.PositiveSmallIntegerField(
        "难度等级",
        default=1
    )

    order = models.IntegerField(
        "排序",
        default=0
    )

    is_active = models.BooleanField(
        "是否隐藏知识点",
        default=True
    )

    class Meta:
        verbose_name = "Sentence / 句子"
        verbose_name_plural = "Sentences / 句子"
        ordering = ["order", "id"]

    def __str__(self):
        return (self.text or "")[:60]


# =========================
# Question（题型）
# =========================
class Question(models.Model):

    QUESTION_TYPES = [
        ("qa", "问答题"),
        ("cloze", "挖空题"),
        ("choice", "选择题"),
        ("listening", "听力题"),
        ("speaking", "朗读题"),
    ]

    BLANK_MODES = [
        ("auto", "自动挖空"),
        ("specified", "指定挖空"),
    ]

    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="所属句子"
    )

    qtype = models.CharField(
        "题型",
        max_length=20,
        choices=QUESTION_TYPES
    )

    question = models.TextField(
        "题目",
        blank=True,
        null=True
    )

    answer = models.TextField(
        "答案",
        blank=True,
        null=True
    )

    pattern = models.TextField(
        "句型提示",
        blank=True,
        null=True
    )

    blank_mode = models.CharField(
        "挖空方式",
        max_length=20,
        choices=BLANK_MODES,
        default="auto"
    )

    is_multiple_choice = models.BooleanField(
        "是否多选",
        default=False
    )

    option_count = models.PositiveSmallIntegerField(
        "选项数量",
        default=4
    )

    manual_distractors = models.TextField(
        "人工混淆项",
        blank=True,
        null=True
    )

    audio = models.FileField(
        "题目音频",
        upload_to="audio/",
        blank=True,
        null=True
    )

    is_active = models.BooleanField(
        "是否启用",
        default=True
    )

    is_auto_generated = models.BooleanField(
        "是否自动生成",
        default=False
    )

    sort_order = models.IntegerField(
        "排序",
        default=0
    )

    created_at = models.DateTimeField(
        "创建时间",
        auto_now_add=True
    )

    class Meta:
        verbose_name = "Question / 题目"
        verbose_name_plural = "Questions / 题目"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.qtype} - {(self.question or '')[:40]}"

    def save(self, *args, **kwargs):

        skip_sync = kwargs.pop("skip_sync", False)

        super().save(*args, **kwargs)

        if skip_sync:
            return

        from .services.question_engine import sync_question_content
        sync_question_content(self)


# =========================
# ChoiceOption（选择题选项）
# =========================
class ChoiceOption(models.Model):

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="所属题目"
    )

    letter = models.CharField(
        "选项字母",
        max_length=1,
        blank=True
    )

    text = models.CharField(
        "选项内容",
        max_length=200
    )

    is_correct = models.BooleanField(
        "是否正确",
        default=False
    )

    is_auto_generated = models.BooleanField(
        "系统生成",
        default=False
    )

    order = models.IntegerField(
        "排序",
        default=0
    )

    class Meta:
        verbose_name = "Choice Option / 选择题选项"
        verbose_name_plural = "Choice Options / 选择题选项"
        ordering = ["order", "id"]

    def __str__(self):
        return self.text or ""


# =========================
# StudyLog（学习记录 / SRS）
# =========================
class StudyLog(models.Model):

    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="study_logs",
        blank=True,
        null=True
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="study_logs",
        blank=True,
        null=True
    )

    user_input = models.TextField(
        "用户输入",
        blank=True
    )

    normalized_input = models.TextField(
        "标准化输入",
        blank=True
    )

    normalized_answer = models.TextField(
        "标准化答案",
        blank=True
    )

    similarity = models.FloatField(
        "相似度",
        default=0
    )

    correct = models.BooleanField(
        "是否正确",
        default=False
    )

    memory_level = models.IntegerField(
        "记忆等级",
        default=0
    )

    next_review = models.DateTimeField(
        "下次复习",
        default=timezone.now
    )

    wrong_count = models.IntegerField(
        "错误次数",
        default=0
    )

    created_at = models.DateTimeField(
        "记录时间",
        auto_now_add=True
    )

    class Meta:
        verbose_name = "Study Log / 学习记录"
        verbose_name_plural = "Study Logs / 学习记录"
        ordering = ["-created_at"]

    def __str__(self):
        if self.question:
            src = self.question.question or ""
        else:
            src = self.sentence.text if self.sentence else ""
        return f"{src[:30]} ({'✓' if self.correct else '✗'})"


# =========================
# WordMemoryState（词级记忆状态）
# =========================
class WordMemoryState(models.Model):

    word = models.CharField(
        "单词",
        max_length=100
    )

    normalized_word = models.CharField(
        "标准化单词",
        max_length=100,
        unique=True,
        db_index=True
    )

    source_sentence = models.ForeignKey(
        Sentence,
        on_delete=models.SET_NULL,
        related_name="word_memories",
        null=True,
        blank=True,
        verbose_name="来源句子"
    )

    memory_level = models.IntegerField(
        "记忆等级",
        default=0
    )

    next_review = models.DateTimeField(
        "下次复习",
        null=True,
        blank=True
    )

    last_review = models.DateTimeField(
        "上次复习",
        null=True,
        blank=True
    )

    wrong_count = models.IntegerField(
        "错误次数",
        default=0
    )

    review_count = models.IntegerField(
        "复习次数",
        default=0
    )

    is_due_boost = models.BooleanField(
        "是否错词强化中",
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Word Memory State / 单词记忆状态"
        verbose_name_plural = "Word Memory States / 单词记忆状态"
        ordering = ["normalized_word"]

    def __str__(self):
        return f"{self.word} (Lv {self.memory_level})"


# =========================
# WrongQuestionLog（错题本）
# =========================
class WrongQuestionLog(models.Model):

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="wrong_logs"
    )

    user_input = models.TextField(
        "错误输入",
        blank=True
    )

    wrong_count = models.IntegerField(
        "错误次数",
        default=1
    )

    last_wrong = models.DateTimeField(
        "最后错误",
        default=timezone.now
    )

    is_mastered = models.BooleanField(
        "已掌握",
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = "Wrong Question / 错题"
        verbose_name_plural = "Wrong Questions / 错题"
        ordering = ["-last_wrong"]

    def __str__(self):
        return f"Wrong Q{self.question_id}"
    


# =========================
# UserMemoryState（当前记忆状态）
# =========================
class UserMemoryState(models.Model):

    sentence = models.ForeignKey(
        Sentence,
        on_delete=models.CASCADE,
        related_name="memory_states",
        verbose_name="所属句子"
    )

    memory_level = models.IntegerField(
        "记忆等级",
        default=0
    )

    next_review = models.DateTimeField(
        "下次复习",
        null=True,
        blank=True
    )

    last_review = models.DateTimeField(
        "上次复习",
        null=True,
        blank=True
    )

    cycle_started = models.DateTimeField(
        "循环开始时间",
        null=True,
        blank=True
    )

    wrong_reset_count = models.IntegerField(
        "错误重置次数",
        default=0
    )

    overdue_reset_count = models.IntegerField(
        "过期重置次数",
        default=0
    )

    review_count = models.IntegerField(
        "复习次数",
        default=0
    )

    mastered_at = models.DateTimeField(
        "掌握时间",
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        "创建时间",
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        "更新时间",
        auto_now=True
    )

    class Meta:
        verbose_name = "User Memory State / 当前记忆状态"
        verbose_name_plural = "User Memory States / 当前记忆状态"
        ordering = ["sentence_id"]

    def __str__(self):
        return f"Sentence {self.sentence_id} - Lv {self.memory_level}"
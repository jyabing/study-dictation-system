from django.db import models
from django.utils import timezone


# =========================
# Course
# =========================
class Course(models.Model):
    name = models.CharField(
        max_length=200,
        verbose_name="课程名称"
    )

    name_en = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        verbose_name="课程英文名"
    )

    description = models.TextField(
        blank=True,
        verbose_name="课程描述"
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
        max_length=200,
        verbose_name="章节标题"
    )

    title_en = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        verbose_name="章节英文标题"
    )

    order = models.IntegerField(
        default=0,
        verbose_name="排序"
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
        verbose_name="原句"
    )

    translation = models.TextField(
        blank=True,
        verbose_name="翻译"
    )

    audio = models.FileField(
        upload_to="audio/",
        blank=True,
        null=True,
        verbose_name="音频"
    )

    difficulty = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="难度等级"
    )

    order = models.IntegerField(
        default=0,
        verbose_name="排序"
    )

    class Meta:
        verbose_name = "Sentence / 句子"
        verbose_name_plural = "Sentences / 句子"
        ordering = ["order", "id"]

    def __str__(self):
        return (self.text or "")[:50]


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
        max_length=20,
        choices=QUESTION_TYPES,
        verbose_name="题型"
    )

    question = models.TextField(
        blank=True,
        null=True,
        verbose_name="题目"
    )

    answer = models.TextField(
        blank=True,
        null=True,
        verbose_name="答案"
    )

    pattern = models.TextField(
        blank=True,
        null=True,
        verbose_name="句型提示 / Pattern"
    )

    blank_mode = models.CharField(
        max_length=20,
        choices=BLANK_MODES,
        default="auto",
        verbose_name="挖空方式"
    )

    is_multiple_choice = models.BooleanField(
        default=False,
        verbose_name="是否多选"
    )

    option_count = models.PositiveSmallIntegerField(
        default=4,
        verbose_name="总选项数"
    )

    manual_distractors = models.TextField(
        blank=True,
        null=True,
        verbose_name="人工混淆项（每行一个）"
    )

    audio = models.FileField(
        upload_to="audio/",
        blank=True,
        null=True,
        verbose_name="音频文件"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="是否启用"
    )

    is_auto_generated = models.BooleanField(
        default=False,
        verbose_name="是否自动生成"
    )

    sort_order = models.IntegerField(
        default=0,
        verbose_name="排序"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间"
    )

    class Meta:
        verbose_name = "Question / 题目"
        verbose_name_plural = "Questions / 题目"
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.qtype} - {(self.question or '')[:40]}"

    def save(self, *args, **kwargs):
        """
        保存 Question 后自动同步：
        - cloze：自动生成 question / answer
        - listening / speaking：自动补 question / answer
        - choice：自动补齐 ChoiceOption

        这里避免递归调用：
        仅在正常保存后调用一次同步函数；
        如果外部显式传入 skip_sync=True，则跳过自动同步。
        """
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

    text = models.CharField(
        max_length=200,
        verbose_name="选项内容"
    )

    is_correct = models.BooleanField(
        default=False,
        verbose_name="是否正确"
    )

    is_auto_generated = models.BooleanField(
        default=False,
        verbose_name="是否系统补齐"
    )

    order = models.IntegerField(
        default=0,
        verbose_name="排序"
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
        verbose_name="所属句子",
        null=True,
        blank=True
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="study_logs",
        blank=True,
        null=True,
        verbose_name="所属题目"
    )

    user_input = models.TextField(
        blank=True,
        verbose_name="用户输入"
    )

    correct = models.BooleanField(
        default=False,
        verbose_name="是否正确"
    )

    memory_level = models.IntegerField(
        default=0,
        help_text="0-6 记忆等级",
        verbose_name="记忆等级"
    )

    next_review = models.DateTimeField(
        default=timezone.now,
        verbose_name="下次复习时间"
    )

    wrong_count = models.IntegerField(
        default=0,
        verbose_name="错误次数"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="记录时间"
    )

    class Meta:
        verbose_name = "Study Log / 学习记录"
        verbose_name_plural = "Study Logs / 学习记录"
        ordering = ["-created_at"]

    def __str__(self):
        if self.question:
            src = self.question.question or self.question.answer or ""
        else:
            src = self.sentence.text if self.sentence else ""
        return f"{src[:30]} ({'✓' if self.correct else '✗'})"
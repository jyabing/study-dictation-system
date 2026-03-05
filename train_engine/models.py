from django.db import models


# 课程
class Course(models.Model):
    name_en = models.CharField(
        max_length=200,
        verbose_name="Course Name / 课程名称"
    )
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Course / 课程"
        verbose_name_plural = "Courses / 课程"
        ordering = ["id"]   # ← 加这一行

    def __str__(self):
        return f"{self.name_en}"


# 章节
class Lesson(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    title_en = models.CharField(max_length=200)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Lesson / 章节"
        verbose_name_plural = "Lessons / 章节"

    def __str__(self):
        return self.title_en


# 句子
class Sentence(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)

    text_en = models.TextField(verbose_name="English Sentence / 英文句子")
    text_zh = models.TextField(blank=True, verbose_name="Chinese Translation / 中文翻译")
    text_ja = models.TextField(blank=True, verbose_name="Japanese / 日本語")

    class Meta:
        verbose_name = "Sentence / 句子"
        verbose_name_plural = "Sentences / 句子"

    def __str__(self):
        return self.text_en[:30]


# 单词
class Word(models.Model):
    text = models.CharField(max_length=100, verbose_name="Word / 单词")
    meaning_en = models.TextField(blank=True, verbose_name="Meaning (EN) / 英文释义")
    meaning_zh = models.TextField(blank=True, verbose_name="Meaning (ZH) / 中文释义")
    meaning_ja = models.TextField(blank=True, verbose_name="Meaning (JA) / 日本語意味")

    class Meta:
        verbose_name = "Word / 单词"
        verbose_name_plural = "Words / 单词"

    def __str__(self):
        return self.text


# 学习记录（简单版，后面可以升级 SRS）
class StudyLog(models.Model):
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    correct = models.BooleanField(default=False)
    review_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.word.text} - {self.correct}"
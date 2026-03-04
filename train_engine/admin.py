from django.contrib import admin
from .models import Course, Lesson, Sentence, Word, StudyLog


admin.site.register(Course)
admin.site.register(Lesson)
admin.site.register(Sentence)
admin.site.register(Word)
admin.site.register(StudyLog)
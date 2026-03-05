import random, difflib
import re
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from .models import Lesson, Sentence


def normalize_text(s: str) -> str:
    """忽略大小写、标点、连续空格"""
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)      # 去标点
    s = re.sub(r"\s+", " ", s).strip() # 多空格归一
    return s


@require_GET
def lesson_sentences(request, lesson_id):
    """获取一个 Lesson 下的句子列表（用于前端顺序/随机）"""
    lesson = Lesson.objects.get(id=lesson_id)
    sentences = list(
        Sentence.objects.filter(lesson=lesson).values("id", "text_en")
    )
    random.shuffle(sentences)  # 简单随机
    return JsonResponse({"sentences": sentences})


@require_POST
def check_answer(request):
    sentence_id = request.POST.get("sentence_id")
    user_input = request.POST.get("user_input", "")

    s = Sentence.objects.get(id=sentence_id)
    expected = s.text_en

    norm_user = normalize_text(user_input)
    norm_expected = normalize_text(expected)

    correct = norm_user == norm_expected

    # ===== 逐词 diff =====
    expected_words = norm_expected.split()
    user_words = norm_user.split()

    diff = list(difflib.ndiff(expected_words, user_words))

    # 标记错误词
    marked = []
    for d in diff:
        code = d[0]
        word = d[2:]
        if code == " ":
            marked.append({"word": word, "status": "correct"})
        elif code == "-":
            marked.append({"word": word, "status": "missing"})
        elif code == "+":
            marked.append({"word": word, "status": "extra"})

    StudyLog.objects.create(
        word=None,
        correct=correct,
        review_time=None
    )

    return JsonResponse({
        "correct": correct,
        "expected": expected,
        "user_input": user_input,
        "diff": marked
    })

def dictation_page(request):
    return render(request, "train_engine/dictation.html")
import random, difflib, json
import re
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
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


@csrf_exempt
@require_POST
def check_answer(request):

    try:
        data = json.loads(request.body)

        sentence_id = data.get("sentence_id")
        user_input = data.get("user_input", "")

        s = Sentence.objects.get(id=sentence_id)

        expected = s.text_en.strip().lower()
        user_input = user_input.strip().lower()

        correct = expected == user_input

        return JsonResponse({
            "correct": correct,
            "expected": expected,
            "user_input": user_input
        })

    except Exception as e:
        return JsonResponse({
            "error": str(e)
        }, status=500)

def dictation_page(request):
    return render(request, "train_engine/dictation.html")
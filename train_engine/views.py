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
        sentence_id = request.POST.get("sentence_id")
        user_input = request.POST.get("user_input", "")

        if not sentence_id:
            return JsonResponse({"error": "sentence_id missing"}, status=400)

        sentence = Sentence.objects.get(id=sentence_id)

        expected = sentence.text_en.strip().lower()
        user = user_input.strip().lower()

        correct = expected == user

        return JsonResponse({
            "correct": correct,
            "expected": expected,
            "diff": []
        })

    except Sentence.DoesNotExist:
        return JsonResponse({"error": "sentence not found"}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

def dictation_page(request):
    return render(request, "train_engine/dictation.html")
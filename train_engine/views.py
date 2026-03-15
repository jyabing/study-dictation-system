import re

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from .models import Course, Lesson, Sentence, Question, StudyLog, UserMemoryState
from .services.srs_engine import review, serialize_memory
from .services.lesson_queue import build_lesson_queue


# =========================
# 文本标准化
# =========================
def normalize_text(s):

    if not s:
        return ""

    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()

    return s


# =========================
# Dashboard
# =========================
def dashboard(request):

    return render(request, "train_engine/dashboard.html")


# =========================
# Dictation 页面
# =========================
def dictation_page(request):

    return render(request, "train_engine/dictation.html")


# =========================
# 训练页面
# =========================
def question_train_page(request):

    return render(request, "train_engine/question_train.html")


# =========================
# 课程列表
# =========================
def course_list(request):

    courses = Course.objects.all()

    course_data = []

    for c in courses:

        lesson_count = Lesson.objects.filter(course=c).count()

        question_count = Question.objects.filter(
            sentence__lesson__course=c
        ).count()

        course_data.append({
            "id": c.id,
            "name": c.name,
            "lesson_count": lesson_count,
            "question_count": question_count
        })

    return render(
        request,
        "train_engine/course_list.html",
        {"courses": course_data}
    )

# =========================
# 新建课程
# =========================
def course_create(request):

    if request.method == "POST":

        name = request.POST.get("name")

        if name:

            Course.objects.create(name=name)

            return redirect("/courses/")

    return render(request, "train_engine/course_create.html")


# =========================
# 课程详情
# =========================
def course_detail(request, course_id):

    course = get_object_or_404(Course, id=course_id)

    lessons = Lesson.objects.filter(course=course)

    return render(
        request,
        "train_engine/course_detail.html",
        {
            "course": course,
            "lessons": lessons
        }
    )


# =========================
# 新建章节
# =========================
def lesson_create(request, course_id):

    course = get_object_or_404(Course, id=course_id)

    if request.method == "POST":

        title = request.POST.get("title")

        if title:

            Lesson.objects.create(
                course=course,
                title=title
            )

            return redirect(f"/course/{course_id}/")

    return render(
        request,
        "train_engine/lesson_create.html",
        {"course": course}
    )


# =========================
# 章节详情
# =========================
def lesson_detail(request, lesson_id):

    lesson = get_object_or_404(Lesson, id=lesson_id)

    sentences = Sentence.objects.filter(lesson=lesson)

    return render(
        request,
        "train_engine/lesson_detail.html",
        {
            "lesson": lesson,
            "sentences": sentences
        }
    )


# =========================
# 新建句子
# =========================
def sentence_create(request, lesson_id):

    lesson = get_object_or_404(Lesson, id=lesson_id)

    if request.method == "POST":

        text = request.POST.get("text")

        if text:

            Sentence.objects.create(
                lesson=lesson,
                text=text
            )

            return redirect(f"/lesson/{lesson_id}/")

    return render(
        request,
        "train_engine/sentence_create.html",
        {"lesson": lesson}
    )


# =========================
# 句子详情
# =========================
def sentence_detail(request, sentence_id):

    sentence = get_object_or_404(Sentence, id=sentence_id)

    questions = Question.objects.filter(sentence=sentence)

    return render(
        request,
        "train_engine/sentence_detail.html",
        {
            "sentence": sentence,
            "questions": questions
        }
    )


# =========================
# 新建题目
# =========================
def question_create(request, sentence_id):

    sentence = get_object_or_404(Sentence, id=sentence_id)

    if request.method == "POST":

        qtype = request.POST.get("qtype")
        question = request.POST.get("question")
        answer = request.POST.get("answer")

        Question.objects.create(
            sentence=sentence,
            qtype=qtype,
            question=question,
            answer=answer
        )

        return redirect(f"/sentence/{sentence_id}/")

    return render(
        request,
        "train_engine/question_form.html",
        {
            "mode": "create",
            "sentence": sentence
        }
    )


# =========================
# 编辑题目
# =========================
def question_edit(request, question_id):

    q = get_object_or_404(Question, id=question_id)

    if request.method == "POST":

        print("POST RECEIVED", request.POST)

        q.qtype = request.POST.get("qtype")
        q.question = request.POST.get("question", "").strip()
        q.answer = request.POST.get("answer", "").strip()
        q.pattern = request.POST.get("pattern", "").strip()

        # 强制更新数据库
        Question.objects.filter(id=q.id).update(
            qtype=q.qtype,
            question=q.question,
            answer=q.answer,
            pattern=q.pattern
        )

        return redirect(f"/sentence/{q.sentence.id}/")

    return render(
        request,
        "train_engine/question_form.html",
        {
            "mode": "edit",
            "sentence": q.sentence,
            "question_obj": q
        }
    )


# =========================
# 删除题目
# =========================
def question_delete(request, question_id):

    q = get_object_or_404(Question, id=question_id)

    sid = q.sentence.id

    q.delete()

    return redirect(f"/sentence/{sid}/")


# =========================
# Lesson sentences API
# =========================
def lesson_sentences(request, lesson_id):

    sentences = Sentence.objects.filter(lesson_id=lesson_id)

    return JsonResponse({

        "sentences": [
            {
                "id": s.id,
                "text": s.text
            }
            for s in sentences
        ]
    })


# =========================
# Lesson questions API
# =========================
def lesson_questions(request, lesson_id):

    questions = Question.objects.filter(
        sentence__lesson_id=lesson_id
    ).prefetch_related("options")

    return JsonResponse({

        "questions": [
            {
                "id": q.id,
                "qtype": q.qtype,
                "question": q.question,
                "answer": q.answer,
                "options": [
                    {
                        "text": o.text,
                        "is_correct": o.is_correct
                    }
                    for o in q.options.all()
                ]
            }
            for q in questions
        ]
    })


# =========================
# Dictation 检查
# =========================
@csrf_exempt
@require_POST
def check_answer(request):

    sentence_id = request.POST.get("sentence_id")
    user_input = request.POST.get("user_input")

    sentence = get_object_or_404(Sentence, id=sentence_id)

    correct = normalize_text(user_input) == normalize_text(sentence.text)

    StudyLog.objects.create(
        sentence=sentence,
        user_input=user_input,
        correct=correct
    )

    return JsonResponse({
        "correct": correct,
        "expected": sentence.text
    })


# =========================
# Question 判题
# =========================
@csrf_exempt
@require_POST
def check_question_answer(request):

    question_id = request.POST.get("question_id")
    user_input = request.POST.get("user_input", "").strip()

    question = Question.objects.select_related("sentence").get(id=question_id)

    expected = (question.answer or "").strip()

    normalized_user = user_input.lower()
    normalized_expected = expected.lower()

    is_correct = normalized_user == normalized_expected


    # =========================
    # 获取记忆状态
    # =========================

    memory, _ = UserMemoryState.objects.get_or_create(
        sentence=question.sentence,
        defaults={"memory_level": 0}
    )


    # =========================
    # SRS 更新
    # =========================

    result = review(memory, is_correct=is_correct, now=timezone.now())
    memory.save()


    # =========================
    # 记录学习日志
    # =========================

    StudyLog.objects.create(
        sentence=question.sentence,
        question=question,
        user_input=user_input,
        normalized_input=normalized_user,
        normalized_answer=normalized_expected,
        similarity=100 if is_correct else 0,
        correct=is_correct,
        memory_level=memory.memory_level,
        next_review=memory.next_review or timezone.now(),
        wrong_count=0 if is_correct else 1,
    )


    # =========================
    # 返回前端
    # =========================

    return JsonResponse({
        "correct": is_correct,
        "expected": expected,
        "memory": serialize_memory(memory),
        "status_message": result.status_message,
    })


# =========================
# Whisper 语音识别
# =========================
@csrf_exempt
@require_POST
def transcribe_speaking_audio(request):

    return JsonResponse({
        "text": "speech recognized"
    })


# =========================
# AI 评分
# =========================
@csrf_exempt
@require_POST
def score_speaking(request):

    return JsonResponse({
        "accuracy": 90,
        "fluency": 88,
        "pronunciation": 85,
        "grammar": 87,
        "suggestion": "Good job"
    })


# =========================
# 错题
# =========================
def wrong_sentences(request):

    logs = StudyLog.objects.filter(correct=False)

    sentence_ids = logs.values_list("sentence_id", flat=True)

    sentences = Sentence.objects.filter(id__in=sentence_ids)

    return JsonResponse({

        "sentences": [
            {
                "id": s.id,
                "text": s.text
            }
            for s in sentences
        ]
    })


# =========================
# SRS复习
# =========================
def review_due_sentences(request):

    now = timezone.now()

    logs = StudyLog.objects.filter(next_review__lte=now)

    sentence_ids = logs.values_list("sentence_id", flat=True)

    sentences = Sentence.objects.filter(id__in=sentence_ids)

    return JsonResponse({

        "sentences": [
            {
                "id": s.id,
                "text": s.text
            }
            for s in sentences
        ]
    })

def courses_api(request):

    courses = Course.objects.all().order_by("id")

    return JsonResponse({

        "courses": [

            {
                "id": c.id,
                "name": c.name
            }

            for c in courses

        ]

    })


@csrf_exempt
@require_POST
def start_training(request):

    lesson_id = request.POST.get("lesson_id")
    limit = int(request.POST.get("limit",5))
    qtype = request.POST.get("qtype")

    qs = Question.objects.filter(
        sentence__lesson__course_id=lesson_id
    )

    if qtype:
        qs = qs.filter(qtype=qtype)

    qs = qs.order_by("?")[:limit]

    data = []

    for q in qs:
        data.append({
            "id":q.id,
            "qtype":q.qtype,
            "question":q.question,
            "answer":q.answer
        })

    return JsonResponse({"questions":data})
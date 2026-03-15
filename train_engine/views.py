import re
import os
import random
import hashlib


from gtts import gTTS
from django.conf import settings

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from train_engine.services.training_queue import build_training_queue

from .models import (
    Course,
    Lesson,
    Sentence,
    Question,
    StudyLog,
    UserMemoryState,
    ChoiceOption,
)
from .services.srs_engine import (
    review,
    serialize_memory,
    calculate_session_next_review,
)
from .services.lesson_queue import build_lesson_queue
from .services.progress_engine import update_word_memory_states


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
# TTS语言
# 可按你的课程语言/题目语言继续扩展
# =========================
def get_tts_lang(question):

    lang = getattr(question, "language", None)
    if lang:
        lang = str(lang).lower()
        if lang in ["en", "english"]:
            return "en"
        if lang in ["ja", "jp", "japanese"]:
            return "ja"
        if lang in ["zh", "cn", "chinese"]:
            return "zh-CN"
        if lang in ["ko", "korean"]:
            return "ko"

    # 默认英语
    return "en"


# =========================
# TTS源文本
# listening / speaking：优先读 question
# 其他题型：也是 question 优先，answer 兜底
# =========================
def get_tts_text(question):

    if question.qtype in ["listening", "speaking"]:
        text = question.question or question.answer
    else:
        text = question.question or question.answer

    if not text and question.sentence:
        text = question.sentence.text

    return (text or "").strip()


# =========================
# 构建TTS文件名
# 使用 question.id + qtype + lang + text hash
# 这样题干修改后会自动换新文件
# =========================
def build_tts_filename(question, text, lang):

    text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    qid = question.id or "x"
    qtype = question.qtype or "unknown"

    return f"tts_q{qid}_{qtype}_{lang}_{text_hash}.mp3"


# =========================
# 获取题目音频URL
# 优先级：
# 1. Question.audio
# 2. Sentence.audio
# 3. TTS缓存
# =========================
def get_question_audio_url(question):

    # 1) 题目专属音频优先
    if getattr(question, "audio", None):
        return question.audio.url

    # 2) 句子音频
    if getattr(question, "sentence", None) and getattr(question.sentence, "audio", None):
        return question.sentence.audio.url

    # 3) TTS
    text = get_tts_text(question)
    if not text:
        return None

    lang = get_tts_lang(question)
    filename = build_tts_filename(question, text, lang)

    rel_dir = os.path.join("audio", "tts")
    abs_dir = os.path.join(settings.MEDIA_ROOT, "audio", "tts")
    abs_path = os.path.join(abs_dir, filename)

    os.makedirs(abs_dir, exist_ok=True)

    if not os.path.exists(abs_path):
        tts = gTTS(text=text, lang=lang)
        tts.save(abs_path)

    return f"{settings.MEDIA_URL}audio/tts/{filename}"

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
# 保存选择题选项（人工编辑）
# 规则：
# - 提交后全部重建
# - 标记 is_auto_generated=False
# - 同步 answer 为正确选项文本
# =========================
def save_choice_options_from_post(question, request):

    option_texts = request.POST.getlist("option_text")
    correct_indexes = request.POST.getlist("correct_option")

    cleaned_options = []

    for i, text in enumerate(option_texts):
        text = (text or "").strip()

        if not text:
            continue

        cleaned_options.append({
            "order": len(cleaned_options),
            "text": text,
            "original_index": i,
        })

    # 先删旧选项
    question.options.all().delete()

    correct_texts = []

    for item in cleaned_options:
        order = item["order"]
        text = item["text"]
        original_index = item["original_index"]

        is_correct = str(original_index) in [str(x) for x in correct_indexes]

        question.options.create(
            letter=chr(65 + order),
            text=text,
            is_correct=is_correct,
            is_auto_generated=False,
            order=order
        )

        if is_correct:
            correct_texts.append(text)

    # 同步答案字段
    if question.qtype == "choice":
        if getattr(question, "is_multiple_choice", False):
            question.answer = " / ".join(correct_texts)
        else:
            question.answer = correct_texts[0] if correct_texts else ""

        question.save(update_fields=["answer"])


# =========================
# 自动生成选择题选项
# 规则：
# - 只有没有人工选项时才允许生成
# - 如果已有人工编辑过的选项，立即停止
# =========================
def auto_generate_choice_options_if_allowed(question):

    if question.qtype != "choice":
        return

    existing_options = question.options.all()

    # 只要存在人工编辑的选项，就绝不覆盖
    if existing_options.filter(is_auto_generated=False).exists():
        return

    # 如果已经有自动生成选项，也先清掉重建
    existing_options.delete()

    answer_text = (question.answer or "").strip()
    sentence_text = (question.sentence.text or "").strip()

    if not answer_text:
        return

    distractors = []

    # 非常基础但稳定的干扰项规则
    # 先从 sentence 中取词
    words = re.findall(r"[A-Za-z\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7a3']+", sentence_text)

    for w in words:
        w = (w or "").strip()
        if not w:
            continue
        if w.lower() == answer_text.lower():
            continue
        if w not in distractors:
            distractors.append(w)

    # 如果句子里干扰项不够，再补一些兜底
    fallback_pool = [
        "Tokyo", "Osaka", "Kyoto", "Nagoya",
        "London", "Paris", "live", "lives", "work", "works"
    ]

    for w in fallback_pool:
        if len(distractors) >= 3:
            break
        if w.lower() == answer_text.lower():
            continue
        if w not in distractors:
            distractors.append(w)

    option_values = [answer_text] + distractors[:3]

    # 去重，防止 answer 和 distractor 撞车
    final_values = []
    for v in option_values:
        if v not in final_values:
            final_values.append(v)

    # 少于2个选项就不生成
    if len(final_values) < 2:
        return

    for i, text in enumerate(final_values):
        question.options.create(
            letter=chr(65 + i),
            text=text,
            is_correct=(text.strip().lower() == answer_text.strip().lower()),
            is_auto_generated=True,
            order=i
        )

# =========================
# 自动生成选择题题干
# sentence → 随机挖空
# =========================
def auto_generate_choice_stem(sentence_text):

    if not sentence_text:
        return "Choose the correct answer."

    words = sentence_text.split()

    if len(words) <= 2:
        return sentence_text

    # 随机选一个词挖空
    idx = random.randint(0, len(words) - 1)

    words[idx] = "_____"

    return " ".join(words)

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
        question = request.POST.get("question", "").strip()
        answer = request.POST.get("answer", "").strip()
        pattern = request.POST.get("pattern", "").strip()

        q = Question.objects.create(
            sentence=sentence,
            qtype=qtype,
            question=question,
            answer=answer,
            pattern=pattern
        )

        # 自动生成题干
        if qtype == "choice" and not question:

            sentence_text = (sentence.text or "").strip()

            if sentence_text:

                words = sentence_text.split()

                if len(words) > 2:

                    import random

                    idx = random.randint(0, len(words) - 1)

                    words[idx] = "_____"

                    q.question = " ".join(words)

                    q.save(update_fields=["question"])

        # 选择题选项逻辑
        if qtype == "choice":

            option_texts = [
                (x or "").strip()
                for x in request.POST.getlist("option_text")
            ]

            has_manual_options = any(option_texts)

            if has_manual_options:
                save_choice_options_from_post(q, request)
            else:
                auto_generate_choice_options_if_allowed(q)

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

        # 重新取最新对象，防止后续状态不一致
        q.refresh_from_db()

        # =========================
        # 选择题：人工编辑优先
        # - 如果提交了选项，就按人工选项保存
        # - 保存后标记 is_auto_generated=False
        # - 以后不再被自动生成覆盖
        # =========================
        if q.qtype == "choice":

            option_texts = [
                (x or "").strip()
                for x in request.POST.getlist("option_text")
            ]

            has_manual_options = any(option_texts)

            if has_manual_options:
                save_choice_options_from_post(q, request)
            else:
                auto_generate_choice_options_if_allowed(q)

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
    # 词级SRS + 错词强化
    # =========================
    word_progress = update_word_memory_states(
        question=question,
        user_input=user_input,
        is_correct=is_correct,
        now=timezone.now()
    )

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
        "word_progress": word_progress,
        "session_next_review": (
            timezone.localtime(memory.next_review).strftime("%Y-%m-%d %H:%M")
            if memory.next_review
            else None
        ),
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

    return JsonResponse(
        {
            "courses": [
                {
                    "id": c.id,
                    "name": c.name
                }
                for c in courses
            ]
        },
        json_dumps_params={"ensure_ascii": False}
    )


@csrf_exempt
@require_POST
def start_training(request):

    lesson_id = request.POST.get("lesson_id")
    limit = int(request.POST.get("limit", 10))
    qtype = request.POST.get("qtype")

    qs = Question.objects.select_related("sentence").prefetch_related("options").filter(
        sentence__lesson__course_id=lesson_id
    )

    if qtype:
        qs = qs.filter(qtype=qtype)

    questions = list(qs)

    # =========================
    # 读取用户记忆状态
    # =========================

    memories = UserMemoryState.objects.filter(
        sentence__in=[q.sentence for q in questions]
    )

    memory_map = {}

    for m in memories:
        memory_map[m.sentence_id] = m

    # =========================
    # 构建训练队列
    # =========================

    from train_engine.services.training_queue import build_training_queue

    queue = build_training_queue(questions, memory_map)

    # 限制数量
    queue = queue[:limit]

    data = []

    for q in queue:

        memory = memory_map.get(q.sentence_id)

        audio_url = get_question_audio_url(q)

        options = list(q.options.all())
        random.shuffle(options)

        data.append({
            "id": q.id,
            "qtype": q.qtype,
            "question": q.question,
            "answer": q.answer,
            "sentence": q.sentence.text,
            "audio_url": audio_url,
            "memory": serialize_memory(memory) if memory else None,
            "options": [
                {
                    "text": o.text,
                    "is_correct": o.is_correct
                }
                for o in options
            ]
        })

    return JsonResponse({
        "questions": data
    })
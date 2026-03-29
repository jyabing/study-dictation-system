import random
import re
import json
import difflib
import hashlib
import os

from datetime import timedelta
from urllib.parse import quote
from django.conf import settings
from gtts import gTTS

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

from ..models import (
    Lesson,
    Question,
    QuestionMemory,
    TrainingItem,
)


# =========================
# 艾宾浩斯间隔表
# =========================
SRS_STEPS = {
    0: timedelta(minutes=0),
    1: timedelta(minutes=10),
    2: timedelta(hours=1),
    3: timedelta(days=1),
    4: timedelta(days=2),
    5: timedelta(days=4),
    6: timedelta(days=7),
    7: timedelta(days=15),
    8: timedelta(days=30),
}


# =========================
# 每日负载（核心参数）
# =========================
DAILY_LIMIT = 40
NEW_RATIO = 0.30
WEAK_RATIO = 0.20

LOAD_NEW = 5
LOAD_WEAK = 4
LOAD_REVIEW = 2
LOAD_EASY = 1

DAILY_LOAD_LIMIT = 100

# 队列参数
QUEUE_REBUILD_THRESHOLD = 5
QUEUE_BATCH_SIZE = 20
WRONG_WORD_REPLAY_MAX = 20


# =========================
# 工具函数
# =========================
def get_speed_level(seconds):
    if seconds < 2:
        return "fast"
    elif seconds < 5:
        return "normal"
    return "slow"


def parse_cloze(text: str):
    answers = []
    cloze = text or ""

    matches = re.findall(r"\{([^}]+)\}", cloze)

    for m in matches:
        answers.append(m.strip())
        cloze = cloze.replace("{" + m + "}", "____", 1)

    return cloze, answers


def normalize(text: str):
    return (text or "").strip().lower()


def is_close(a, b):
    if len(a) <= 4 or len(b) <= 4:
        return a == b
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def check_answer(user_answer, correct_answer):
    """
    宽松判题：
    1. 忽略大小写
    2. 支持简单单复数
    3. 支持轻微拼写错误
    """
    ua = normalize(user_answer)
    ca = normalize(correct_answer)

    if ua == ca:
        return True

    if ua == ca + "s" or ua + "s" == ca:
        return True

    if is_close(ua, ca):
        return True

    return False


def get_next_review(level: int):
    if level in SRS_STEPS:
        return timezone.now() + SRS_STEPS[level]

    return timezone.now() + timedelta(days=30)


def _get_wrong_boost(memory):
    return getattr(memory, "wrong_boost", 0) or 0


def _set_wrong_boost(memory, value):
    if hasattr(memory, "wrong_boost"):
        memory.wrong_boost = value


def _set_last_wrong_at(memory, dt):
    if hasattr(memory, "last_wrong_at"):
        memory.last_wrong_at = dt


def _normalize_raw_answer(raw_answer):
    """
    前端可能传：
    - JSON list（cloze）
    - 普通字符串（write / choice）
    """
    try:
        parsed = json.loads(raw_answer or "")
        return parsed
    except Exception:
        return raw_answer


def _make_wrong_word_training_id(training_id, wrong_index):
    return f"wrong:{training_id}:{wrong_index}"


def _is_wrong_word_training_id(training_id):
    return isinstance(training_id, str) and training_id.startswith("wrong:")


def _parse_wrong_word_training_id(training_id):
    """
    wrong:12:1 -> (12, 1)
    """
    try:
        _, tid, idx = training_id.split(":")
        return int(tid), int(idx)
    except Exception:
        return None, None


def _session_get_wrong_word_queue(request):
    return request.session.get("wrong_word_queue", [])


def _session_set_wrong_word_queue(request, queue):
    request.session["wrong_word_queue"] = queue


def _session_push_wrong_word_items(request, lesson_id, training, user_answers, correct_answers):
    """
    错词复盘：
    把错误 blank 拆成单个“错词训练项”插入队列
    """
    queue = _session_get_wrong_word_queue(request)

    existing_ids = {item.get("replay_id") for item in queue}

    for i, correct in enumerate(correct_answers):
        user_word = ""
        if i < len(user_answers):
            user_word = str(user_answers[i] or "").strip()

        if not check_answer(user_word, correct):
            replay_id = _make_wrong_word_training_id(training.id, i)

            if replay_id in existing_ids:
                continue

            queue.insert(0, {
                "replay_id": replay_id,
                "lesson_id": lesson_id,
                "training_id": training.id,
                "wrong_index": i,
                "prompt": training.question.prompt_text or "",
                "cloze_text": training.cloze_text or "",
                "correct_word": correct,
                "user_word": user_word,
                "attempts": 0,
                "created_at": timezone.now().isoformat(),
            })

    # 控制长度，避免 session 无限增长
    queue = queue[:WRONG_WORD_REPLAY_MAX]
    _session_set_wrong_word_queue(request, queue)


def _build_wrong_word_payload(item):
    """
    错词复盘题：
    只练一个 blank
    """
    cloze_text = item.get("cloze_text") or ""
    wrong_index = item.get("wrong_index", 0)

    parts = cloze_text.split("____")

    rebuilt = []
    for i, p in enumerate(parts):
        rebuilt.append(p)
        if i < len(parts) - 1:
            if i == wrong_index:
                rebuilt.append("____")
            else:
                rebuilt.append("（已知）")

    replay_cloze_text = "".join(rebuilt)

    return {
        "training_id": item.get("replay_id"),
        "type": "read_cloze",
        "prompt": f"错词复盘：{item.get('prompt', '')}",
        "cloze_text": replay_cloze_text,
        "cloze_answers_len": 1,
        "choices": [],
        "audio": "",
        "correct_answers": [item.get("correct_word", "")],
        "is_wrong_word_replay": True,
    }


def _choose_dynamic_item_type(training, memory):
    """
    现在 builder 创建的是“明确题型”，不要再用旧的动态题型改写它。
    只对旧数据保留原逻辑。
    """
    meta = _extract_training_meta(training)
    explicit_item_type = meta.get("item_type")

    # 新 builder 题型：固定返回
    if explicit_item_type == "read_choice_single":
        return "read_choice"

    if explicit_item_type == "read_choice_multi":
        return "read_choice"

    if explicit_item_type == "write_text":
        return "write"

    if explicit_item_type in {"listen_asr", "speak_read", "read_cloze"}:
        return explicit_item_type

    # =========================
    # 下面保留旧逻辑，只给旧数据用
    # =========================
    item_type = training.item_type
    level = memory.memory_level or 0
    wrong_boost = _get_wrong_boost(memory)

    if wrong_boost >= 5:
        return "read_cloze"

    if level <= 2:
        if training.choices:
            return "read_choice"
        return "read_cloze"

    if level >= 5:
        return "write"

    return item_type

def _extract_training_meta(training):
    choices = training.choices or []
    if not choices or not isinstance(choices[0], dict):
        return {}

    first = choices[0]

    meta = first.get("_meta")
    if isinstance(meta, dict):
        return meta

    # 兼容 read_choice_single / read_choice_multi
    return {
        "selection_mode": first.get("selection_mode", "single"),
        "reveal_text_on_wrong": first.get("reveal_text_on_wrong", False),
    }


def _normalize_choice_answers(raw_answer):
    """
    前端传上来的可能是：
    1) JSON 数组字符串：["A", "C"]
    2) 逗号拼接字符串：A,C
    3) 单个字符串：A
    """
    if raw_answer is None:
        return []

    if isinstance(raw_answer, list):
        return [str(x).strip() for x in raw_answer if str(x).strip()]

    text = str(raw_answer).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass

    parts = re.split(r"[,，/|]+", text)
    return [p.strip() for p in parts if p.strip()]

def _guess_tts_lang(meta):
    asr_cfg = meta.get("asr") or {}
    lang = (asr_cfg.get("lang") or "").strip()

    mapping = {
        "ja-JP": "ja",
        "en-US": "en",
        "en-GB": "en",
        "zh-CN": "zh-CN",
        "ko-KR": "ko",
    }
    return mapping.get(lang, "en")


def _ensure_tts_audio(question, meta):
    prompt_text = (question.prompt_text or "").strip()
    if not prompt_text:
        return ""

    lang = _guess_tts_lang(meta)
    text_hash = hashlib.md5(prompt_text.encode("utf-8")).hexdigest()[:12]
    filename = f"tts_q{question.id}_{lang}_{text_hash}.mp3"

    rel_dir = os.path.join("audio", "tts")
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    abs_path = os.path.join(abs_dir, filename)

    os.makedirs(abs_dir, exist_ok=True)

    if not os.path.exists(abs_path):
        try:
            tts = gTTS(text=prompt_text, lang=lang)
            tts.save(abs_path)
        except Exception as e:
            print("TTS generate failed:", e)
            return ""

    return f"{settings.MEDIA_URL}{rel_dir}/{filename}"


# =========================
# 🔥 训练数据构建（最终版）
# =========================
def build_training_payload(training, memory=None):
    q = training.question
    meta = _extract_training_meta(training)
    cycle_status = _build_cycle_status(memory)

    dynamic_type = training.item_type
    if memory is not None:
        dynamic_type = _choose_dynamic_item_type(training, memory)

    audio_url = (q.audio_url or "").strip()

    if not audio_url and meta.get("use_tts") and dynamic_type in {"listen_asr", "speak_read"}:
        audio_url = _ensure_tts_audio(q, meta)

    payload = {
        "training_id": training.id,
        "type": dynamic_type,
        "prompt": q.prompt_text or "",
        "cloze_text": training.cloze_text or "",
        "cloze_answers_len": len(training.cloze_answers or []),
        "choices": training.choices or [],
        "audio": audio_url,
        "answer_text": q.answer_text or "",
        "meta": meta,

        "question_id": q.id,
        "lesson_id": q.lesson_id or "",
        "book_id": q.lesson.book_id if q.lesson_id else "",

        "cycle_status": cycle_status,
    }

    payload.update({
        "selection_mode": meta.get("selection_mode", "single"),
        "use_tts": meta.get("use_tts", False),
        "asr_lang": (meta.get("asr") or {}).get("lang", "ja-JP"),
        "allow_partial_match": (meta.get("asr") or {}).get("allow_partial_match", True),
    })

    return payload


def get_item_memory(user, training):
    if not user.is_authenticated:
        return None

    memory, _ = QuestionMemory.objects.get_or_create(
        user=user,
        question=training.question
    )
    return memory


def judge_training_answer(training, raw_answer):
    """
    根据 TrainingItem 类型统一判题
    返回:
    {
        "is_correct": bool,
        "correct_answers": list,
        "display_answer": str,
        "user_answers": list | str
    }
    """
    item_type = training.item_type
    q = training.question
    meta = _extract_training_meta(training)

    # =========================
    # Cloze
    # =========================
    if item_type == "read_cloze":

        try:
            user_answers = json.loads(raw_answer or "[]")
        except Exception:
            user_answers = []

        correct_answers = training.cloze_answers or []

        if len(correct_answers) == 1 and len(user_answers) == 1:
            ua = normalize(user_answers[0])
            ca = normalize(correct_answers[0])

            if ca in ua:
                return {
                    "is_correct": True,
                    "correct_answers": correct_answers,
                    "display_answer": correct_answers[0],
                    "user_answers": user_answers,
                }

        is_correct = True

        if len(user_answers) != len(correct_answers):
            is_correct = False
        else:
            for ua, ca in zip(user_answers, correct_answers):
                if not check_answer(ua, ca):
                    is_correct = False
                    break

        return {
            "is_correct": is_correct,
            "correct_answers": correct_answers,
            "display_answer": " / ".join(correct_answers),
            "user_answers": user_answers,
        }

    # =========================
    # 选择题（单选 / 多选）
    # =========================
    if item_type == "read_choice":
        choices = training.choices or []
        selection_mode = meta.get("selection_mode", "single")

        correct_keys = [
            c.get("key")
            for c in choices
            if c.get("correct")
        ]

        correct_texts = [
            c.get("text") or c.get("content") or c.get("audio") or ""
            for c in choices
            if c.get("correct")
        ]

        user_answers = _normalize_choice_answers(raw_answer)

        if selection_mode == "multi":
            is_correct = sorted(user_answers) == sorted(correct_keys)
        else:
            is_correct = len(user_answers) == 1 and user_answers[0] in correct_keys

        return {
            "is_correct": is_correct,
            "correct_answers": correct_keys,
            "display_answer": " / ".join(correct_texts or correct_keys),
            "user_answers": user_answers,
        }

    # =========================
    # 听 / 说：本质都是识别后的文本比对
    # =========================
    if item_type in {"listen_asr", "speak_read"}:
        parsed = _normalize_raw_answer(raw_answer)

        if isinstance(parsed, list):
            user_answer = normalize(" ".join(str(x) for x in parsed))
        else:
            user_answer = normalize(str(parsed or ""))

        correct_text = normalize(q.answer_text or "")

        allow_partial_match = (meta.get("asr") or {}).get("allow_partial_match", True)

        if allow_partial_match:
            is_correct = correct_text in user_answer or user_answer in correct_text
        else:
            is_correct = check_answer(user_answer, correct_text)

        return {
            "is_correct": is_correct,
            "correct_answers": [q.answer_text] if q.answer_text else [],
            "display_answer": q.answer_text or "",
            "user_answers": raw_answer,
        }

    # =========================
    # 写：统一走 question.answer_text
    # =========================
    parsed = _normalize_raw_answer(raw_answer)

    if isinstance(parsed, list):
        user_answer = normalize(" ".join(str(x) for x in parsed))
    else:
        user_answer = normalize(str(parsed or ""))

    correct_text = normalize(q.answer_text or "")
    is_correct = check_answer(user_answer, correct_text)

    return {
        "is_correct": is_correct,
        "correct_answers": [q.answer_text] if q.answer_text else [],
        "display_answer": q.answer_text or "",
        "user_answers": raw_answer,
    }


def judge_wrong_word_replay(item, raw_answer):
    """
    错词复盘只接受 1 个 blank
    前端仍可能传 list，所以这里兼容
    """
    parsed = _normalize_raw_answer(raw_answer)

    if isinstance(parsed, list):
        user_word = str(parsed[0] or "").strip() if parsed else ""
    else:
        user_word = str(parsed or "").strip()

    correct_word = item.get("correct_word", "")

    is_correct = check_answer(user_word, correct_word)

    return {
        "is_correct": is_correct,
        "correct_answers": [correct_word],
        "display_answer": correct_word,
        "user_answers": [user_word],
    }


def update_memory_after_answer(memory, is_correct):
    if not memory:
        return

    now = timezone.now()

    if is_correct:
        memory.memory_level = min((memory.memory_level or 0) + 1, 8)
        memory.correct_streak = (memory.correct_streak or 0) + 1
        memory.total_correct = (memory.total_correct or 0) + 1
        _set_wrong_boost(memory, 0)
        memory.next_review_at = get_next_review(memory.memory_level)
    else:
        memory.memory_level = max((memory.memory_level or 0) - 1, 0)
        memory.correct_streak = 0
        memory.total_wrong = (memory.total_wrong or 0) + 1
        _set_wrong_boost(memory, min(_get_wrong_boost(memory) + 3, 10))
        _set_last_wrong_at(memory, now)
        memory.next_review_at = now + timedelta(minutes=5)

    memory.last_review_at = now
    memory.save()

def _memory_stage_label(level):
    """
    按你当前代码的 memory_level 上限 8 来显示
    """
    mapping = {
        0: "新学",
        1: "第1轮巩固（5分钟）",
        2: "第2轮巩固（30分钟）",
        3: "第3轮巩固（12小时）",
        4: "第4轮巩固（1天）",
        5: "第5轮巩固（2天）",
        6: "第6轮巩固（4天）",
        7: "第7轮巩固（7天）",
        8: "第8轮巩固（15天）",
    }
    try:
        level = int(level or 0)
    except Exception:
        level = 0
    return mapping.get(level, f"Lv{level}")


def _memory_stage_group(level):
    try:
        level = int(level or 0)
    except Exception:
        level = 0

    if level == 0:
        return "新学阶段"
    if 1 <= level <= 3:
        return "短期巩固"
    if 4 <= level <= 7:
        return "中期巩固"
    return "长期巩固"


def _next_review_text(next_review_at):
    if not next_review_at:
        return "待安排"

    local_dt = timezone.localtime(next_review_at)
    now = timezone.localtime(timezone.now())
    day_diff = (local_dt.date() - now.date()).days

    if day_diff == 0:
        return f"今天 {local_dt.strftime('%H:%M')}"
    if day_diff == 1:
        return f"明天 {local_dt.strftime('%H:%M')}"
    if day_diff == -1:
        return f"昨天 {local_dt.strftime('%H:%M')}"
    return local_dt.strftime("%Y-%m-%d %H:%M")


def _build_cycle_status(memory):
    if not memory:
        return {
            "level": 0,
            "stage_label": _memory_stage_label(0),
            "stage_group": _memory_stage_group(0),
            "next_review_text": "待安排",
            "is_due": True,
            "is_overdue": False,
            "status_text": "新内容，等待开始第一轮巩固",
        }

    level = int(getattr(memory, "memory_level", 0) or 0)
    next_review_at = getattr(memory, "next_review_at", None)
    now = timezone.now()

    is_due = (next_review_at is None) or (next_review_at <= now)
    is_overdue = (next_review_at is not None) and (next_review_at < now)

    if next_review_at is None:
        status_text = "新内容，等待进入下一轮"
    elif is_overdue:
        status_text = f"已逾期，原定复习时间：{_next_review_text(next_review_at)}"
    elif is_due:
        status_text = f"今日到期，复习时间：{_next_review_text(next_review_at)}"
    else:
        status_text = f"下一次复习：{_next_review_text(next_review_at)}"

    return {
        "level": level,
        "stage_label": _memory_stage_label(level),
        "stage_group": _memory_stage_group(level),
        "next_review_text": _next_review_text(next_review_at),
        "is_due": is_due,
        "is_overdue": is_overdue,
        "status_text": status_text,
    }

def get_dashboard_cycle_summary(user):
    if not user or not user.is_authenticated:
        return {
            "main_stage": "未登录",
            "next_review_text": "待登录后查看",
            "today_due_count": 0,
            "overdue_count": 0,
            "done_today_count": 0,
            "stage_distribution": [],
            "danger_text": "请先登录",
        }

    now = timezone.now()

    memories = QuestionMemory.objects.filter(
        user=user,
        question__lesson__book__owner=user
    ).select_related("question__lesson")

    done_ids = set(getattr(user, "_request", None).session.get("today_done_ids", [])) if getattr(user, "_request", None) else set()

    level_counter = {
        0: 0, 1: 0, 2: 0, 3: 0, 4: 0,
        5: 0, 6: 0, 7: 0, 8: 0,
    }

    today_due_count = 0
    overdue_count = 0
    next_review_candidates = []

    for m in memories:
        level = int(getattr(m, "memory_level", 0) or 0)
        if level not in level_counter:
            level_counter[level] = 0
        level_counter[level] += 1

        next_review_at = getattr(m, "next_review_at", None)

        if next_review_at:
            next_review_candidates.append(next_review_at)

            local_next = timezone.localtime(next_review_at)
            local_now = timezone.localtime(now)

            if local_next.date() == local_now.date() and next_review_at <= now:
                today_due_count += 1

            if next_review_at < now:
                overdue_count += 1

    total_items = sum(level_counter.values())

    if total_items == 0:
        main_stage = "新学阶段"
    else:
        weighted = sum(k * v for k, v in level_counter.items())
        avg_level = weighted / max(total_items, 1)

        if avg_level < 1:
            main_stage = "新学阶段"
        elif avg_level < 4:
            main_stage = "短期巩固"
        elif avg_level < 7:
            main_stage = "中期巩固"
        else:
            main_stage = "长期巩固"

    next_review_text = "待安排"
    future_candidates = sorted(next_review_candidates)
    if future_candidates:
        next_review_text = _next_review_text(future_candidates[0])

    # 这里 done_today_count 仍按 session 里的完成数显示
    done_today_count = len(done_ids)

    if overdue_count > 0:
        danger_text = f"当前最危险的是已逾期内容，共 {overdue_count} 条，建议优先处理。"
    elif today_due_count > 0:
        danger_text = f"今天有 {today_due_count} 条内容到期，建议优先完成今天的循环。"
    else:
        danger_text = "当前没有逾期内容，系统处于稳定推进状态。"

    stage_distribution = [
        {"label": "新学", "count": level_counter.get(0, 0)},
        {"label": "5分钟", "count": level_counter.get(1, 0)},
        {"label": "30分钟", "count": level_counter.get(2, 0)},
        {"label": "12小时", "count": level_counter.get(3, 0)},
        {"label": "1天", "count": level_counter.get(4, 0)},
        {"label": "2天", "count": level_counter.get(5, 0)},
        {"label": "4天", "count": level_counter.get(6, 0)},
        {"label": "7天", "count": level_counter.get(7, 0)},
        {"label": "15天", "count": level_counter.get(8, 0)},
    ]

    return {
        "main_stage": main_stage,
        "next_review_text": next_review_text,
        "today_due_count": today_due_count,
        "overdue_count": overdue_count,
        "done_today_count": done_today_count,
        "stage_distribution": stage_distribution,
        "danger_text": danger_text,
    }

def get_book_lessons_cycle_summary(user, book):
    if not user or not user.is_authenticated:
        return []

    now = timezone.now()

    lessons = Lesson.objects.filter(book=book).order_by("order", "id")

    memories = QuestionMemory.objects.filter(
        user=user,
        question__lesson__book=book
    ).select_related("question__lesson")

    lesson_map = {
        lesson.id: {
            "lesson": lesson,
            "new_count": 0,
            "short_count": 0,
            "long_count": 0,
            "today_due_count": 0,
            "overdue_count": 0,
            "next_review_at": None,
        }
        for lesson in lessons
    }

    for m in memories:
        lesson_id = getattr(m.question, "lesson_id", None)
        if lesson_id not in lesson_map:
            continue

        row = lesson_map[lesson_id]
        level = int(getattr(m, "memory_level", 0) or 0)
        next_review_at = getattr(m, "next_review_at", None)

        if level == 0:
            row["new_count"] += 1
        elif 1 <= level <= 3:
            row["short_count"] += 1
        else:
            row["long_count"] += 1

        if next_review_at:
            local_next = timezone.localtime(next_review_at)
            local_now = timezone.localtime(now)

            if local_next.date() == local_now.date() and next_review_at <= now:
                row["today_due_count"] += 1

            if next_review_at < now:
                row["overdue_count"] += 1

            if row["next_review_at"] is None or next_review_at < row["next_review_at"]:
                row["next_review_at"] = next_review_at

    result = []

    for lesson in lessons:
        row = lesson_map[lesson.id]

        if row["overdue_count"] > 0:
            risk_level = "高风险"
        elif row["today_due_count"] > 0:
            risk_level = "中风险"
        else:
            risk_level = "稳定"

        total = row["new_count"] + row["short_count"] + row["long_count"]

        if total == 0:
            main_stage = "尚未开始"
        elif row["new_count"] >= row["short_count"] and row["new_count"] >= row["long_count"]:
            main_stage = "新学阶段"
        elif row["short_count"] >= row["long_count"]:
            main_stage = "短期巩固"
        else:
            main_stage = "长期巩固"

        result.append({
            "lesson": lesson,
            "new_count": row["new_count"],
            "short_count": row["short_count"],
            "long_count": row["long_count"],
            "today_due_count": row["today_due_count"],
            "overdue_count": row["overdue_count"],
            "next_review_text": _next_review_text(row["next_review_at"]),
            "risk_level": risk_level,
            "main_stage": main_stage,
        })

    return result

def get_lesson_cycle_summary(user, lesson):
    if not user or not user.is_authenticated:
        return {
            "new_count": 0,
            "short_count": 0,
            "long_count": 0,
            "today_due_count": 0,
            "overdue_count": 0,
            "main_stage": "未登录",
            "next_review_text": "待登录后查看",
            "risk_level": "稳定",
            "total_count": 0,
        }

    now = timezone.now()

    memories = QuestionMemory.objects.filter(
        user=user,
        question__lesson=lesson
    ).select_related("question__lesson")

    new_count = 0
    short_count = 0
    long_count = 0
    today_due_count = 0
    overdue_count = 0
    next_review_at = None

    for m in memories:
        level = int(getattr(m, "memory_level", 0) or 0)
        nr = getattr(m, "next_review_at", None)

        if level == 0:
            new_count += 1
        elif 1 <= level <= 3:
            short_count += 1
        else:
            long_count += 1

        if nr:
            local_next = timezone.localtime(nr)
            local_now = timezone.localtime(now)

            if local_next.date() == local_now.date() and nr <= now:
                today_due_count += 1

            if nr < now:
                overdue_count += 1

            if next_review_at is None or nr < next_review_at:
                next_review_at = nr

    total_count = new_count + short_count + long_count

    if total_count == 0:
        main_stage = "尚未开始"
    elif new_count >= short_count and new_count >= long_count:
        main_stage = "新学阶段"
    elif short_count >= long_count:
        main_stage = "短期巩固"
    else:
        main_stage = "长期巩固"

    if overdue_count > 0:
        risk_level = "高风险"
    elif today_due_count > 0:
        risk_level = "中风险"
    else:
        risk_level = "稳定"

    return {
        "new_count": new_count,
        "short_count": short_count,
        "long_count": long_count,
        "today_due_count": today_due_count,
        "overdue_count": overdue_count,
        "main_stage": main_stage,
        "next_review_text": _next_review_text(next_review_at),
        "risk_level": risk_level,
        "total_count": total_count,
    }

def get_lesson_round_progress(request, lesson):
    user = request.user

    if not user or not user.is_authenticated:
        return {
            "due_count": 0,
            "done_count": 0,
            "remaining_count": 0,
        }

    now = timezone.now()
    done_ids = set(request.session.get("today_done_ids", []))

    items = TrainingItem.objects.select_related("question__lesson").filter(
        question__lesson=lesson
    )

    due_ids = []

    for item in items:
        memory, _ = QuestionMemory.objects.get_or_create(
            user=user,
            question=item.question
        )

        next_review_at = getattr(memory, "next_review_at", None)
        is_due = (next_review_at is None) or (next_review_at <= now)

        if is_due:
            due_ids.append(item.id)

    due_count = len(due_ids)
    done_count = len([x for x in due_ids if x in done_ids])
    remaining_count = max(due_count - done_count, 0)

    return {
        "due_count": due_count,
        "done_count": done_count,
        "remaining_count": remaining_count,
    }

def get_dashboard_books_cycle_summary(user, books):
    if not user or not user.is_authenticated:
        return []

    now = timezone.now()
    book_ids = [b.id for b in books]

    memories = QuestionMemory.objects.filter(
        user=user,
        question__lesson__book_id__in=book_ids
    ).select_related("question__lesson__book")

    book_map = {
        book.id: {
            "book": book,
            "new_count": 0,
            "short_count": 0,
            "long_count": 0,
            "today_due_count": 0,
            "overdue_count": 0,
            "next_review_at": None,
        }
        for book in books
    }

    for m in memories:
        book_id = getattr(m.question.lesson, "book_id", None)
        if book_id not in book_map:
            continue

        row = book_map[book_id]
        level = int(getattr(m, "memory_level", 0) or 0)
        next_review_at = getattr(m, "next_review_at", None)

        if level == 0:
            row["new_count"] += 1
        elif 1 <= level <= 3:
            row["short_count"] += 1
        else:
            row["long_count"] += 1

        if next_review_at:
            local_next = timezone.localtime(next_review_at)
            local_now = timezone.localtime(now)

            if local_next.date() == local_now.date() and next_review_at <= now:
                row["today_due_count"] += 1

            if next_review_at < now:
                row["overdue_count"] += 1

            if row["next_review_at"] is None or next_review_at < row["next_review_at"]:
                row["next_review_at"] = next_review_at

    result = []

    for book in books:
        row = book_map[book.id]

        total = row["new_count"] + row["short_count"] + row["long_count"]

        if total == 0:
            main_stage = "尚未开始"
        elif row["new_count"] >= row["short_count"] and row["new_count"] >= row["long_count"]:
            main_stage = "新学阶段"
        elif row["short_count"] >= row["long_count"]:
            main_stage = "短期巩固"
        else:
            main_stage = "长期巩固"

        if row["overdue_count"] > 0:
            risk_level = "高风险"
        elif row["today_due_count"] > 0:
            risk_level = "中风险"
        else:
            risk_level = "稳定"

        result.append({
            "book": book,
            "new_count": row["new_count"],
            "short_count": row["short_count"],
            "long_count": row["long_count"],
            "today_due_count": row["today_due_count"],
            "overdue_count": row["overdue_count"],
            "main_stage": main_stage,
            "next_review_text": _next_review_text(row["next_review_at"]),
            "risk_level": risk_level,
        })

    return result

def add_xp(request, is_correct):
    xp = request.session.get("xp", 0)
    xp += 10 if is_correct else 2
    request.session["xp"] = xp
    return xp


# =========================
# 今日学习计划（SRS 正式版）
# =========================
def get_today_plan(request):

    user = request.user

    if not user.is_authenticated:
        return {"items": [], "total": 0, "done": 0, "progress": 0}

    now = timezone.now()
    daily_limit = int(request.session.get("daily_limit", DAILY_LIMIT))

    items = TrainingItem.objects.select_related("question__lesson").filter(
        question__lesson__book__owner=user
    )

    plan = []

    for item in items:

        memory, _ = QuestionMemory.objects.get_or_create(
            user=user,
            question=item.question
        )

        due = (
            memory.next_review_at is None
            or memory.next_review_at <= now
        )

        is_new = (memory.total_correct or 0) == 0 and (memory.total_wrong or 0) == 0

        plan.append({
            "training": item,
            "question": item.question,
            "lesson": item.question.lesson,
            "due": due,
            "level": memory.memory_level or 0,
            "wrong_boost": _get_wrong_boost(memory),
            "last_wrong_at": getattr(memory, "last_wrong_at", None),
            "is_new": is_new,
        })

    def _sort_key(x):
        last_wrong_ts = 0
        if x["last_wrong_at"]:
            last_wrong_ts = -x["last_wrong_at"].timestamp()

        return (
            not x["due"],            # 到期优先
            -x["wrong_boost"],       # 错题强化优先
            not x["is_new"],         # 新题优先
            x["level"],              # level 低优先
            last_wrong_ts,           # 最近错的更优先
        )

    plan.sort(key=_sort_key)

    plan = plan[:daily_limit]

    done_ids = request.session.get("today_done_ids", [])

    total = len(plan)
    done = sum(
        1 for p in plan
        if p["training"].id in done_ids
    )

    progress = int(done / total * 100) if total > 0 else 0

    return {
        "items": plan,
        "total": total,
        "done": done,
        "progress": progress
    }


# =========================
# SRS + 队列融合（优化版）
# =========================
def build_smart_queue(request, lesson, limit=QUEUE_BATCH_SIZE):
    """
    优化版智能队列：
    1. due 题优先
    2. wrong_boost 高的题优先
    3. 新题按比例进入
    4. level 低的题优先
    5. 避免重复塞满同一题
    """

    user = request.user
    now = timezone.now()

    items = TrainingItem.objects.select_related("question").filter(
        question__lesson=lesson
    )

    pool = []

    for item in items:
        memory = get_item_memory(user, item)
        if not memory:
            continue

        level = memory.memory_level or 0
        wrong_boost = _get_wrong_boost(memory)
        next_review_at = memory.next_review_at
        total_correct = memory.total_correct or 0
        total_wrong = memory.total_wrong or 0

        is_due = (next_review_at is None) or (next_review_at <= now)
        is_new = (total_correct == 0 and total_wrong == 0)

        score = 0

        # 1) 到期题最高优先
        if is_due:
            score += 1000

        # 2) 错题强化
        score += wrong_boost * 100

        # 3) 新题适度优先
        if is_new:
            score += 80

        # 4) level 越低越优先
        score += max(0, 20 - level * 2)

        # 5) 最近错过，稍微再提一点
        last_wrong_at = getattr(memory, "last_wrong_at", None)
        if last_wrong_at:
            minutes_since_wrong = max((now - last_wrong_at).total_seconds() / 60, 0)
            if minutes_since_wrong <= 30:
                score += 40
            elif minutes_since_wrong <= 180:
                score += 20

        pool.append({
            "id": item.id,
            "score": score,
            "is_due": is_due,
            "is_new": is_new,
            "wrong_boost": wrong_boost,
            "level": level,
        })

    if not pool:
        return []

    # =========================
    # 分桶
    # =========================
    due_items = [x for x in pool if x["is_due"]]
    wrong_items = [x for x in pool if x["wrong_boost"] > 0]
    new_items = [x for x in pool if x["is_new"]]
    normal_items = [x for x in pool if not x["is_due"] and not x["is_new"]]

    # 各桶内部排序
    due_items.sort(key=lambda x: (-x["score"], x["level"]))
    wrong_items.sort(key=lambda x: (-x["score"], x["level"]))
    new_items.sort(key=lambda x: (-x["score"], x["level"]))
    normal_items.sort(key=lambda x: (-x["score"], x["level"]))

    # =========================
    # 配比
    # =========================
    due_quota = max(1, int(limit * 0.5))
    wrong_quota = max(1, int(limit * 0.2))
    new_quota = max(1, int(limit * 0.2))

    selected = []

    selected += due_items[:due_quota]
    selected += wrong_items[:wrong_quota]
    selected += new_items[:new_quota]

    # 去重
    seen = set()
    deduped = []
    for x in selected:
        if x["id"] in seen:
            continue
        seen.add(x["id"])
        deduped.append(x)

    selected = deduped

    # 不够就从 normal_items 补
    remain = limit - len(selected)
    if remain > 0:
        for x in normal_items:
            if x["id"] in seen:
                continue
            selected.append(x)
            seen.add(x["id"])
            if len(selected) >= limit:
                break

    # 还不够，再从所有池子高分补齐
    if len(selected) < limit:
        fallback = sorted(pool, key=lambda x: (-x["score"], x["level"]))
        for x in fallback:
            if x["id"] in seen:
                continue
            selected.append(x)
            seen.add(x["id"])
            if len(selected) >= limit:
                break

    # =========================
    # 轻度打散，避免完全固定顺序
    # =========================
    top = selected[:5]
    rest = selected[5:]

    random.shuffle(top)
    random.shuffle(rest)

    final_items = top + rest

    print("🔥 smart_queue =", [x["id"] for x in final_items[:limit]])

    return [x["id"] for x in final_items[:limit]]

# =========================
# 页面：训练页
# =========================
@login_required
def lesson_train(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    plan = get_today_plan(request)
    lesson_cycle_summary = get_lesson_cycle_summary(request.user, lesson)
    lesson_round_progress = get_lesson_round_progress(request, lesson)

    return render(request, "train/train.html", {
        "lesson": lesson,
        "plan_total": plan["total"],
        "plan_done": plan["done"],
        "plan_progress": plan["progress"],
        "lesson_cycle_summary": lesson_cycle_summary,
        "lesson_round_progress": lesson_round_progress,
    })


# =========================
# API：无刷新训练（完整版）
# =========================
def lesson_train_api(request, lesson_id):
    print("🔥🔥🔥 API HIT")

    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )


    # =========================
    # GET：出题（走SRS调度）
    # =========================
    if request.method == "GET":

        print("🔥 API HIT")

        done_ids = request.session.get("today_done_ids", [])

        # =========================
        # 1) 先拿当前课自己的全部训练项
        # =========================
        all_training_items = list(
            TrainingItem.objects.select_related("question__lesson")
            .filter(question__lesson=lesson)
            .order_by("id")
        )

        if not all_training_items:
            return JsonResponse({
                "empty": True,
                "reason": "no_material",
                "message": "这课还没有循环记忆素材，请先新增循环记忆素材。"
            })

        # =========================
        # 2) 再看“今天计划”里有没有这课
        #    有就优先走今天计划
        #    没有就直接进入本课训练
        # =========================
        plan = get_today_plan(request)
        
        plan_items = plan["items"]

        lesson_plan_items = [
            i for i in plan_items
            if i["training"].question.lesson_id == lesson.id
        ]

        if lesson_plan_items:
            source_items = lesson_plan_items
        else:
            source_items = [
                {"training": item}
                for item in all_training_items
            ]

        remaining = [
            i for i in source_items
            if i["training"].id not in done_ids
        ]

        # =========================
        # 3) 只有“今天计划里确实有这课，并且都做完了”
        #    才显示今日完成
        # =========================
        if lesson_plan_items and not remaining:
            return JsonResponse({
                "empty": True,
                "reason": "today_done",
                "message": "今天这课的学习计划已经完成了。"
            })

        # =========================
        # 4) 如果今天计划里没有这课，
        #    就直接给这课的第一题 / 未做题，不显示今日完成
        # =========================
        if not remaining:
            remaining = [
                {"training": item}
                for item in all_training_items
                if item.id not in done_ids
            ]

        if not remaining:
            remaining = [
                {"training": all_training_items[0]}
            ]

        training = remaining[0]["training"]

        memory = get_item_memory(request.user, training)
        payload = build_training_payload(training, memory)

        payload.update({
            "empty": False,
            "memory_level": memory.memory_level if memory else 0,
            "plan_total": plan["total"] if lesson_plan_items else len(all_training_items),
            "plan_done": plan["done"] if lesson_plan_items else 0,
            "plan_progress": plan["progress"] if lesson_plan_items else 0,
            "is_today_plan": bool(lesson_plan_items),
        })

        return JsonResponse(payload)

    # =========================
    # POST：判题 + 记忆更新 + 队列更新
    # =========================
    if request.method == "POST":

        training_id = request.POST.get("training_id")
        raw_answer = request.POST.get("answer", "")
        duration = int(request.POST.get("duration", 0) or 0) / 1000

        # -------------------------
        # 错词复盘题
        # -------------------------
        if _is_wrong_word_training_id(training_id):

            wrong_word_queue = _session_get_wrong_word_queue(request)

            target = None
            for item in wrong_word_queue:
                if item.get("replay_id") == training_id and item.get("lesson_id") == lesson.id:
                    target = item
                    break

            if not target:
                return JsonResponse({
                    "ok": False,
                    "result": "❌ 错词复盘数据不存在"
                }, status=404)

            judge = judge_wrong_word_replay(target, raw_answer)
            is_correct = judge["is_correct"]

            # 错词复盘成功 → 从错词队列删除
            if is_correct:
                wrong_word_queue = [
                    x for x in wrong_word_queue
                    if x.get("replay_id") != training_id
                ]
            else:
                # 错了就 attempts +1，继续留在最前
                for x in wrong_word_queue:
                    if x.get("replay_id") == training_id:
                        x["attempts"] = int(x.get("attempts", 0)) + 1
                        break

            _session_set_wrong_word_queue(request, wrong_word_queue)

            xp = add_xp(request, is_correct)

            return JsonResponse({
                "ok": True,
                "is_correct": is_correct,
                "result": (
                    "✅ 错词复盘正确"
                    if is_correct else
                    f"❌ 错词复盘错误，正确答案：{judge['display_answer']}"
                ),
                "speed": get_speed_level(duration),
                "xp": xp,
                "correct_answers": judge["correct_answers"],
                "training_id": training_id,
                "type": "read_cloze",
                "prompt": target.get("prompt", ""),
                "cloze_text": target.get("cloze_text", ""),
                "choices": [],
                "audio": "",
            })

        # -------------------------
        # 正常 TrainingItem
        # -------------------------
        training = get_object_or_404(
            TrainingItem.objects.select_related("question__lesson"),
            id=training_id,
            question__lesson=lesson
        )

        judge = judge_training_answer(training, raw_answer)
        is_correct = judge["is_correct"]

        memory = get_item_memory(request.user, training)
        if not memory:
            memory, _ = QuestionMemory.objects.get_or_create(
                user=request.user,
                question=training.question
            )

        cycle_before = _build_cycle_status(memory)

        update_memory_after_answer(memory, is_correct)
        memory.save()
        memory.refresh_from_db()

        cycle_after = _build_cycle_status(memory)

        # 只有答对才计入今日完成
        if is_correct:
            done_ids = request.session.get("today_done_ids", [])
            if training.id not in done_ids:
                done_ids.append(training.id)
            request.session["today_done_ids"] = done_ids

        # Cloze 错词进入错词复盘队列
        if training.item_type == "read_cloze" and not is_correct:
            user_answers = judge.get("user_answers", [])
            correct_answers = judge.get("correct_answers", [])
            _session_push_wrong_word_items(
                request=request,
                lesson_id=lesson.id,
                training=training,
                user_answers=user_answers,
                correct_answers=correct_answers,
            )

        xp = add_xp(request, is_correct)

        # =========================
        # 队列更新（核心）
        # =========================
        queue = request.session.get("training_queue", [])

        if queue:
            current_id = queue.pop(0)

            if not is_correct:
                # 错题插到第2位，更合理
                queue.insert(1 if len(queue) > 0 else 0, current_id)

            request.session["training_queue"] = queue

        plan = get_today_plan(request)
        lesson_round_progress = get_lesson_round_progress(request, lesson)
        return JsonResponse({
            "ok": True,
            "is_correct": is_correct,
            "result": (
                f"✅ 正确（Lv {memory.memory_level if memory else 0}）"
                if is_correct else
                f"❌ 错误，正确答案：{judge['display_answer']}"
            ),
            "speed": get_speed_level(duration),
            "xp": xp,
            "memory_level": memory.memory_level if memory else 0,
            "correct_answers": judge["correct_answers"],
            "plan_total": plan["total"],
            "plan_done": plan["done"],
            "plan_progress": plan["progress"],

            "lesson_round_progress": lesson_round_progress,

            "cycle_before": cycle_before,
            "cycle_after": cycle_after,
            "cycle_feedback": (
                f"回答正确，已进入：{cycle_after['stage_label']}；{cycle_after['status_text']}"
                if is_correct else
                f"回答错误，已回退到：{cycle_after['stage_label']}；{cycle_after['status_text']}"
            ),

            **build_training_payload(training, memory),
        })

    return JsonResponse({"ok": False, "error": "method not allowed"}, status=405)

@login_required
def lesson_question_list(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    questions = Question.objects.filter(
        lesson=lesson
    ).order_by("id")

    return render(request, "train/question_list.html", {
        "lesson": lesson,
        "book": lesson.book,
        "questions": questions,
    })


# =========================
# 统计页
# =========================
def stats_page(request):
    stats = get_stats(request)

    return render(request, "train/stats.html", {
        "stats": stats
    })


@require_POST
def set_daily_limit(request):
    try:
        limit = int(request.POST.get("limit", DAILY_LIMIT))
    except Exception:
        limit = DAILY_LIMIT

    request.session["daily_limit"] = limit
    return JsonResponse({"ok": True})


# =========================
# 学习统计
# =========================
def get_stats(request):

    user = request.user

    if not user.is_authenticated:
        return {
            "today": 0,
            "week": 0,
            "streak": 0,
            "accuracy": 0,
            "xp": 0,
            "level": 0,
        }

    now = timezone.now()
    memories = QuestionMemory.objects.filter(user=user)

    today_count = memories.filter(
        last_review_at__date=now.date(),
        total_correct__gt=0
    ).count()

    week_start = now - timedelta(days=7)

    week_count = memories.filter(
        last_review_at__gte=week_start,
        total_correct__gt=0
    ).count()

    total_correct = sum(m.total_correct or 0 for m in memories)
    total_wrong = sum(m.total_wrong or 0 for m in memories)

    total = total_correct + total_wrong
    accuracy = int((total_correct / total) * 100) if total > 0 else 0

    streak = 0
    for i in range(30):
        day = now.date() - timedelta(days=i)

        count = memories.filter(
            last_review_at__date=day,
            total_correct__gt=0
        ).count()

        if count > 0:
            streak += 1
        else:
            break

    xp = request.session.get("xp", 0)
    level = int(xp ** 0.5)

    return {
        "today": int(today_count or 0),
        "week": int(week_count or 0),
        "streak": int(streak or 0),
        "accuracy": int(accuracy or 0),
        "xp": int(xp or 0),
        "level": int(level or 0),
    }


# =========================
# Builder 页面
# =========================
@login_required
def builder_page(request):
    lessons = Lesson.objects.filter(book__owner=request.user).order_by("book_id", "order", "id")

    return render(request, "train/builder.html", {
        "lessons": lessons
    })


# =========================
# Builder 工具
# =========================
def _safe_json_loads(raw_body):
    try:
        return json.loads(raw_body or "{}")
    except Exception:
        return {}


def _split_answer_text(answer_text):
    """
    支持：
    1) 单答案
    2) 多答案：换行 / 逗号 / 分号 / 斜杠 / 顿号 分隔
    """
    text = (answer_text or "").strip()
    if not text:
        return []

    parts = re.split(r"[\n,，;/；、|]+", text)
    return [p.strip() for p in parts if p.strip()]


def _normalize_choices(raw_choices, selection_mode="single", reveal_text_on_wrong=False):
    """
    把前端的 choices 统一整理成 TrainingItem.choices 可保存结构
    并且顺手提取 correct_texts，回写到 question.answer_text
    """
    normalized = []
    correct_texts = []

    for idx, c in enumerate(raw_choices or []):
        ctype = (c.get("type") or "text").strip()

        if ctype == "audio":
            audio = (c.get("audio") or c.get("content") or "").strip()
            text = (c.get("text") or c.get("content") or "").strip()

            item = {
                "key": chr(65 + idx),  # A/B/C/D...
                "type": "audio",
                "audio": audio,
                "text": text,
                "content": text,
                "correct": bool(c.get("correct")),
                "selection_mode": selection_mode,
                "reveal_text_on_wrong": reveal_text_on_wrong,
            }

            if item["correct"] and text:
                correct_texts.append(text)

            normalized.append(item)
            continue

        content = (c.get("content") or c.get("text") or "").strip()

        item = {
            "key": chr(65 + idx),
            "type": "text",
            "content": content,
            "text": content,
            "correct": bool(c.get("correct")),
            "selection_mode": selection_mode,
            "reveal_text_on_wrong": reveal_text_on_wrong,
        }

        if item["correct"] and content:
            correct_texts.append(content)

        normalized.append(item)

    return normalized, correct_texts


@csrf_exempt
@login_required
def builder_save(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    data = _safe_json_loads(request.body)

    lesson_id = data.get("lesson_id")
    skill = (data.get("skill") or "read").strip()
    item_type = (data.get("item_type") or "").strip()

    # 兼容旧字段
    prompt_text = (data.get("prompt_text") or data.get("prompt") or "").strip()
    answer_text = (data.get("answer_text") or data.get("answer") or "").strip()
    prompt_audio = (data.get("prompt_audio") or data.get("audio_url") or "").strip()

    use_tts = bool(data.get("use_tts", False))
    raw_choices = data.get("choices") or []
    reveal_text_on_wrong = bool(
        data.get("reveal_text_on_wrong") or data.get("reveal", False)
    )
    cloze_cfg = data.get("cloze") or {}
    asr_cfg = data.get("asr") or {}

    if not lesson_id:
        return JsonResponse({"ok": False, "error": "lesson_id 不能为空"}, status=400)

    if not item_type:
        return JsonResponse({"ok": False, "error": "item_type 不能为空"}, status=400)

    if not prompt_text:
        return JsonResponse({"ok": False, "error": "题干不能为空"}, status=400)

    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    # 听 / 说：如果没单独填 answer_text，默认用 prompt_text 当识别比对文本
    if item_type in {"listen_asr", "speak_read"} and not answer_text:
        answer_text = prompt_text

    question = Question.objects.create(
        lesson=lesson,
        prompt_text=prompt_text,
        answer_text=answer_text,
        audio_url=prompt_audio or ""
    )

    created_items = []

    # =========================
    # 读：选择题（单选 / 多选）
    # 现阶段仍然落到 read_choice，额外模式放在 choices 里
    # =========================
    if item_type in {"read_choice_single", "read_choice_multi"}:
        selection_mode = "multi" if item_type == "read_choice_multi" else "single"

        choices_payload, correct_texts = _normalize_choices(
            raw_choices=raw_choices,
            selection_mode=selection_mode,
            reveal_text_on_wrong=reveal_text_on_wrong
        )

        if not choices_payload:
            question.delete()
            return JsonResponse({"ok": False, "error": "选择题至少需要一个选项"}, status=400)

        if not correct_texts:
            question.delete()
            return JsonResponse({"ok": False, "error": "选择题至少需要一个正确答案"}, status=400)

        # 回写标准答案，便于后续训练统一判定
        question.answer_text = " / ".join(correct_texts)
        question.save(update_fields=["answer_text"])

        training = TrainingItem.objects.create(
            question=question,
            item_type="read_choice",
            choices=choices_payload
        )
        created_items.append(training.id)

        return JsonResponse({
            "ok": True,
            "question_id": question.id,
            "training_ids": created_items,
            "saved_as": "read_choice",
            "selection_mode": selection_mode
        })

    # =========================
    # 读：克漏字
    # 现阶段：
    # - prompt_text 直接当 cloze_text
    # - answer_text 支持多答案拆分
    # =========================
    if item_type == "read_cloze":
        cloze_text = prompt_text
        cloze_answers = _split_answer_text(answer_text)

        if "____" not in cloze_text:
            question.delete()
            return JsonResponse({
                "ok": False,
                "error": "克漏字题干里必须包含 ____ 占位符"
            }, status=400)

        if not cloze_answers:
            question.delete()
            return JsonResponse({
                "ok": False,
                "error": "克漏字必须填写答案，多个答案可用换行/逗号/分号分隔"
            }, status=400)

        training = TrainingItem.objects.create(
            question=question,
            item_type="read_cloze",
            cloze_text=cloze_text,
            cloze_answers=cloze_answers,
            choices=[{
                "_meta": {
                    "skill": skill,
                    "item_type": item_type,
                    "cloze": cloze_cfg
                }
            }]
        )
        created_items.append(training.id)

        return JsonResponse({
            "ok": True,
            "question_id": question.id,
            "training_ids": created_items,
            "saved_as": "read_cloze"
        })

    # =========================
    # 写：文字作答
    # 现阶段映射到 write
    # =========================
    if item_type == "write_text":
        if not answer_text:
            question.delete()
            return JsonResponse({"ok": False, "error": "写作题必须填写标准答案"}, status=400)

        training = TrainingItem.objects.create(
            question=question,
            item_type="write",
            choices=[{
                "_meta": {
                    "skill": skill,
                    "item_type": item_type
                }
            }]
        )
        created_items.append(training.id)

        return JsonResponse({
            "ok": True,
            "question_id": question.id,
            "training_ids": created_items,
            "saved_as": "write"
        })

    # =========================
    # 听 / 说
    # 这一步先保存素材和配置
    # 下一步再补训练页渲染与判题
    # =========================
    if item_type in {"listen_asr", "speak_read"}:
        training = TrainingItem.objects.create(
            question=question,
            item_type=item_type,
            choices=[{
                "_meta": {
                    "skill": skill,
                    "item_type": item_type,
                    "use_tts": use_tts,
                    "asr": asr_cfg
                }
            }]
        )
        created_items.append(training.id)

        return JsonResponse({
            "ok": True,
            "question_id": question.id,
            "training_ids": created_items,
            "saved_as": item_type,
            "note": "素材已保存；训练页与判题逻辑下一步再接"
        })

    question.delete()
    return JsonResponse({
        "ok": False,
        "error": f"暂不支持的 item_type: {item_type}"
    }, status=400)

@login_required
def question_edit(request, question_id):
    question = get_object_or_404(
        Question,
        id=question_id,
        lesson__book__owner=request.user
    )

    next_url = (
        request.GET.get("next")
        or request.POST.get("next")
        or f"/lesson/{question.lesson_id}/"
    )

    if request.method == "POST":
        prompt_text = (request.POST.get("prompt_text") or "").strip()
        answer_text = (request.POST.get("answer_text") or "").strip()
        audio_url = (request.POST.get("audio_url") or "").strip()

        if prompt_text:
            question.prompt_text = prompt_text
            question.answer_text = answer_text
            question.audio_url = audio_url
            question.save(update_fields=["prompt_text", "answer_text", "audio_url"])
            return redirect(next_url)

    return render(request, "train/edit_item.html", {
        "mode": "question",
        "obj": question,
        "next": next_url,
        "page_title": "编辑题干与回答",
    })

@login_required
@require_POST
def question_delete(request, question_id):
    question = get_object_or_404(
        Question,
        id=question_id,
        lesson__book__owner=request.user
    )

    lesson_id = question.lesson_id
    question.delete()

    return redirect("lesson-question-list", lesson_id=lesson_id)
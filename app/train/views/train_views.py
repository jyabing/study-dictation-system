import random
import re
import json
import difflib
import hashlib
import os
import copy
import unicodedata

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
from app.train.services.cloze_engine import generate_cloze

from django.urls import reverse

from ..models import (
    Book,
    Lesson,
    Question,
    QuestionMemory,
    UserProfile,
    StudyLog,
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


def _katakana_to_hiragana(text: str) -> str:
    result = []

    for ch in text:
        code = ord(ch)

        # Katakana -> Hiragana
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(ch)

    return "".join(result)


def _normalize_japanese_variants(text: str) -> str:
    """
    日语轻量归一化（不依赖第三方库）：
    1. NFKC 统一全角/半角
    2. 去首尾空白并小写
    3. 统一片假名 -> 平假名
    4. 去掉常见空格和标点
    5. 处理少量“汉字写法 <-> 假名写法”别名
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.strip().lower()
    text = _katakana_to_hiragana(text)

    remove_chars = " 　\t\r\n。、「」『』（）()［］[]【】{}〈〉《》・，,．.！!？?ー〜~：:；;/／…"
    for ch in remove_chars:
        text = text.replace(ch, "")

    jp_alias_map = {
        "相変わらず": "あいかわらず",
        "相变わらず": "あいかわらず",
    }

    for src, dst in jp_alias_map.items():
        text = text.replace(src, dst)

    return text


def normalize(text: str):
    text = unicodedata.normalize("NFKC", text or "")
    return text.strip().lower()


def is_close(a, b):
    if len(a) <= 4 or len(b) <= 4:
        return a == b
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def _looks_cjk_text(text: str) -> bool:
    text = str(text or "")
    return bool(re.search(r"[\u3040-\u30ff\u31f0-\u31ff\u4e00-\u9fff\uac00-\ud7af]", text))


def _check_answer_english(user_answer, correct_answer):
    ua = normalize(user_answer)
    ca = normalize(correct_answer)

    if not ua or not ca:
        return False

    if ua == ca:
        return True

    # 仅保留最保守的英文单复数容错
    if ua == ca + "s" or ua + "s" == ca:
        return True

    # 英语短句不做模糊匹配，避免误判
    if " " in ua or " " in ca:
        return False

    # 只有单词级别才给轻微拼写容错
    return is_close(ua, ca)


def _check_answer_cjk(user_answer, correct_answer):
    ua = normalize(user_answer)
    ca = normalize(correct_answer)

    if ua == ca:
        return True

    ua_jp = _normalize_japanese_variants(user_answer)
    ca_jp = _normalize_japanese_variants(correct_answer)

    if ua_jp == ca_jp:
        return True

    if is_close(ua, ca):
        return True

    if is_close(ua_jp, ca_jp):
        return True

    return False


def check_answer(user_answer, correct_answer):
    """
    分语言宽松判题：
    1. 英语：更保守，避免短句误判
    2. 中日韩：保留归一化与近似匹配
    """
    if _looks_cjk_text(user_answer) or _looks_cjk_text(correct_answer):
        return _check_answer_cjk(user_answer, correct_answer)

    return _check_answer_english(user_answer, correct_answer)

def judge_speech_answer_layers(user_answer, correct_answer):
    """
    听 / 说题最小分层判定：
    1. strict：原文严格一致
    2. normalized：归一化后一致（平假名 / 片假名 / 标点 / 空格容错）
    3. wrong：未命中

    说明：
    - 第一版先不做真正“汉字 -> 假名读音链”转换
    - 先把现有归一化能力显式结构化返回
    """

    raw_user = str(user_answer or "").strip()
    raw_correct = str(correct_answer or "").strip()

    strict_correct = bool(raw_user) and bool(raw_correct) and raw_user == raw_correct

    normalized_user = normalize(raw_user)
    normalized_correct = normalize(raw_correct)

    jp_user = _normalize_japanese_variants(raw_user)
    jp_correct = _normalize_japanese_variants(raw_correct)

    normalized_correct_flag = False

    if raw_user and raw_correct:
        if normalized_user == normalized_correct:
            normalized_correct_flag = True
        elif jp_user == jp_correct:
            normalized_correct_flag = True
        elif check_answer(raw_user, raw_correct):
            normalized_correct_flag = True

    if strict_correct:
        return {
            "is_correct": True,
            "result_level": "strict",
            "strict_correct": True,
            "normalized_correct": True,
            "reading_correct": False,
            "orthography_correct": True,
            "feedback_message": "完全正确",
        }

    if normalized_correct_flag:
        return {
            "is_correct": True,
            "result_level": "normalized",
            "strict_correct": False,
            "normalized_correct": True,
            "reading_correct": False,
            "orthography_correct": False,
            "feedback_message": "表达正确，但书写形式与标准答案不完全一致",
        }

    return {
        "is_correct": False,
        "result_level": "wrong",
        "strict_correct": False,
        "normalized_correct": False,
        "reading_correct": False,
        "orthography_correct": False,
        "feedback_message": "答案不正确",
    }

def _normalize_accepted_answers(values):
    """
    accepted_answers 统一清洗成字符串列表
    """
    if not values:
        return []

    cleaned = []

    if isinstance(values, list):
        raw_list = values
    else:
        raw_list = [values]

    for item in raw_list:
        text = str(item or "").strip()
        if text:
            cleaned.append(text)

    return cleaned

def _get_strict_step_rule(step: int):
    """
    严格艾宾浩斯锚点：
    0 = 新学（未进入正式循环）
    1 = 5分钟
    2 = 30分钟
    3 = 12小时
    4 = 1天
    5 = 2天
    6 = 4天
    7 = 7天
    8 = 15天
    9 = 1个月
    10 = 3个月
    11 = 6个月
    """
    rules = {
        0: {
            "label": "新学",
            "interval": None,
            "grace": None,
            "kind": "init",
        },
        1: {
            "label": "5分钟",
            "interval": timedelta(minutes=5),
            "grace": timedelta(minutes=7),
            "kind": "short",
        },
        2: {
            "label": "30分钟",
            "interval": timedelta(minutes=30),
            "grace": timedelta(minutes=7),
            "kind": "short",
        },
        3: {
            "label": "12小时",
            "interval": timedelta(hours=12),
            "grace": timedelta(minutes=7),
            "kind": "short",
        },
        4: {
            "label": "1天",
            "interval": timedelta(days=1),
            "grace": timedelta(days=1),
            "kind": "long",
        },
        5: {
            "label": "2天",
            "interval": timedelta(days=2),
            "grace": timedelta(days=1),
            "kind": "long",
        },
        6: {
            "label": "4天",
            "interval": timedelta(days=4),
            "grace": timedelta(days=1),
            "kind": "long",
        },
        7: {
            "label": "7天",
            "interval": timedelta(days=7),
            "grace": timedelta(days=1),
            "kind": "long",
        },
        8: {
            "label": "15天",
            "interval": timedelta(days=15),
            "grace": timedelta(days=1),
            "kind": "long",
        },
        9: {
            "label": "1个月",
            "interval": timedelta(days=30),
            "grace": timedelta(days=1),
            "kind": "long",
        },
        10: {
            "label": "3个月",
            "interval": timedelta(days=90),
            "grace": timedelta(days=1),
            "kind": "long",
        },
        11: {
            "label": "6个月",
            "interval": timedelta(days=180),
            "grace": timedelta(days=1),
            "kind": "long",
        },
    }

    try:
        step = int(step or 0)
    except Exception:
        step = 0

    return rules.get(step, rules[0])


def get_next_review(level: int, base_time=None):
    """
    兼容旧调用：
    现在仍然允许传 level，
    但这里的含义已经切换为“严格循环 step”。
    """
    now = base_time or timezone.now()
    rule = _get_strict_step_rule(level)
    interval = rule.get("interval")

    if interval is None:
        return now

    return now + interval


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

def _session_get_pinned_cloze_map(request):
    return request.session.get("pinned_cloze_map", {})


def _session_set_pinned_cloze_map(request, data):
    request.session["pinned_cloze_map"] = data


def _session_pin_cloze_layout(request, question_id, cloze_text, cloze_answers, level_name):
    pinned = _session_get_pinned_cloze_map(request)
    pinned[str(question_id)] = {
        "cloze_text": cloze_text,
        "cloze_answers": cloze_answers,
        "level_name": level_name,
    }
    _session_set_pinned_cloze_map(request, pinned)

def _session_prune_deleted_training_refs(request):
    """
    清理 session 中指向已删除训练题 / 已删除题目的残留缓存。
    目的：
    - 错词复盘不会继续显示已删除素材
    - 训练队列不会继续保留已删除 training_id
    - pinned_cloze_map 不会继续保留已删除 question_id
    """
    wrong_word_queue = request.session.get("wrong_word_queue", [])
    training_queue = request.session.get("training_queue", [])
    pinned_cloze_map = request.session.get("pinned_cloze_map", {})

    referenced_training_ids = set()

    if isinstance(wrong_word_queue, list):
        for item in wrong_word_queue:
            if isinstance(item, dict):
                training_id = item.get("training_id")
                if isinstance(training_id, int):
                    referenced_training_ids.add(training_id)

    if isinstance(training_queue, list):
        for item in training_queue:
            if isinstance(item, int):
                referenced_training_ids.add(item)
            elif isinstance(item, dict):
                training_id = item.get("training_id")
                if isinstance(training_id, int):
                    referenced_training_ids.add(training_id)

    existing_training_ids = set()
    if referenced_training_ids:
        existing_training_ids = set(
            TrainingItem.objects.filter(
                id__in=referenced_training_ids,
                question__lesson__book__owner=request.user
            ).values_list("id", flat=True)
        )

    if isinstance(wrong_word_queue, list):
        cleaned_wrong_word_queue = []
        for item in wrong_word_queue:
            if not isinstance(item, dict):
                continue

            training_id = item.get("training_id")
            if training_id is not None and training_id not in existing_training_ids:
                continue

            cleaned_wrong_word_queue.append(item)

        request.session["wrong_word_queue"] = cleaned_wrong_word_queue

    if isinstance(training_queue, list):
        cleaned_training_queue = []
        for item in training_queue:
            if isinstance(item, int):
                if item not in existing_training_ids:
                    continue
                cleaned_training_queue.append(item)
                continue

            if isinstance(item, dict):
                training_id = item.get("training_id")
                if training_id is not None and training_id not in existing_training_ids:
                    continue
                cleaned_training_queue.append(item)
                continue

            cleaned_training_queue.append(item)

        request.session["training_queue"] = cleaned_training_queue

    if isinstance(pinned_cloze_map, dict):
        referenced_question_ids = set()

        for key in pinned_cloze_map.keys():
            key_str = str(key).strip()
            if key_str.isdigit():
                referenced_question_ids.add(int(key_str))

        existing_question_ids = set()
        if referenced_question_ids:
            existing_question_ids = set(
                Question.objects.filter(
                    id__in=referenced_question_ids,
                    lesson__book__owner=request.user
                ).values_list("id", flat=True)
            )

        cleaned_pinned_cloze_map = {}
        for key, value in pinned_cloze_map.items():
            key_str = str(key).strip()
            if not key_str.isdigit():
                continue

            if int(key_str) not in existing_question_ids:
                continue

            cleaned_pinned_cloze_map[key_str] = value

        request.session["pinned_cloze_map"] = cleaned_pinned_cloze_map


def _session_get_pinned_cloze_layout(request, question_id):
    pinned = _session_get_pinned_cloze_map(request)
    return pinned.get(str(question_id))


def _session_clear_pinned_cloze_layout(request, question_id):
    pinned = _session_get_pinned_cloze_map(request)
    key = str(question_id)
    if key in pinned:
        pinned.pop(key)
        _session_set_pinned_cloze_map(request, pinned)


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
    # 🔥 新逻辑：禁止自动改题型
    # =========================
    if explicit_item_type:
        return explicit_item_type

    # fallback：仅旧数据使用
    return training.item_type
    

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

def _guess_choice_tts_lang(training, meta, choices):
    """
    选择题 TTS 语言推断：
    1. 优先复用 meta 里的 asr.lang
    2. 没有时，根据题干/答案/选项文本内容粗略判断
    3. 默认 en
    """
    lang = _guess_tts_lang(meta)
    if lang != "en":
        return lang

    samples = []

    if getattr(training, "instruction_text", None):
        samples.append(str(training.instruction_text or ""))

    if getattr(training, "source_text", None):
        samples.append(str(training.source_text or ""))

    if getattr(training, "target_answer", None):
        samples.append(str(training.target_answer or ""))

    for c in choices or []:
        samples.append(str(c.get("text") or c.get("content") or ""))

    joined = " ".join(samples)

    # 日语：优先看假名
    if re.search(r"[\u3040-\u30ff\u31f0-\u31ff]", joined):
        return "ja"

    # 韩语
    if re.search(r"[\uac00-\ud7af]", joined):
        return "ko"

    # 中文：只有汉字、没有假名时，再按中文
    if re.search(r"[\u4e00-\u9fff]", joined):
        return "zh-CN"

    return "en"


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

def _build_choice_tts_audio(text, lang="en", prefix="choiceopt"):
    text = (text or "").strip()
    if not text:
        return ""

    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    filename = f"{prefix}_{lang}_{digest}.mp3"

    rel_dir = "audio/tts"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    abs_path = os.path.join(abs_dir, filename)

    if not os.path.exists(abs_path):
        gTTS(text=text, lang=lang).save(abs_path)

    return f"{settings.MEDIA_URL}{rel_dir}/{filename}"

def _get_training_meta_dict(training):
    choices = training.choices or []
    if choices and isinstance(choices[0], dict):
        meta = choices[0].get("_meta")
        if isinstance(meta, dict):
            return meta
    return {}


def _resolve_choice_audio(choice, lang="en"):
    audio = (choice.get("audio") or "").strip()
    text = (choice.get("text") or choice.get("content") or "").strip()
    use_tts_when_no_audio = bool(choice.get("use_tts_when_no_audio", False))

    # 1. 优先人工音频
    if audio:
        return audio

    # 2. 没人工音频时，用 TTS
    if use_tts_when_no_audio and text:
        return _build_choice_tts_audio(
            text=text,
            lang=lang,
            prefix="choiceopt"
        )

    return ""

def _build_tts_audio(text, lang="en", prefix="prompttts"):
    text = (text or "").strip()
    if not text:
        return ""

    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    filename = f"{prefix}_{lang}_{digest}.mp3"

    rel_dir = "audio/tts"
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    abs_path = os.path.join(abs_dir, filename)

    if not os.path.exists(abs_path):
        gTTS(text=text, lang=lang).save(abs_path)

    return f"{settings.MEDIA_URL}{rel_dir}/{filename}"

# =========================
# 根据记忆等级决定克漏字难度
# =========================
def _resolve_cloze_level_by_memory(memory):
    level = 0

    if memory:
        level = int(
            getattr(memory, "cycle_step", None)
            if getattr(memory, "cycle_step", None) is not None
            else (getattr(memory, "memory_level", 0) or 0)
        )

    # 新题 / 低等级：初级
    if level <= 2:
        return "easy"

    # 中等级：中级
    if level <= 5:
        return "medium"

    # 更高等级：高级
    return "hard"


# =========================
# 根据难度给出 blank 范围
# =========================
def _resolve_cloze_blank_range(level_name, base_min, base_max):
    base_min = int(base_min or 1)
    base_max = int(base_max or base_min)

    if base_max < base_min:
        base_max = base_min

    if level_name == "easy":
        return 1, 1

    if level_name == "medium":
        return max(1, base_min), min(2, max(base_max, 2))

    return max(2, base_min), min(3, max(base_max, 3))

# =========================
# 🔥 训练数据构建（最终版）
# =========================
def build_training_payload(training, memory=None, request=None):
    item_type = _extract_training_meta(training).get("item_type") or training.item_type
    meta = _get_training_meta_dict(training)

    raw_choices = copy.deepcopy(training.choices or [])
    choices = []
    selection_mode = "single"

    if training.item_type == "read_choice":
        choices = raw_choices
        choice_tts_lang = _guess_choice_tts_lang(training, meta, choices)

        for c in choices:
            c["resolved_audio"] = _resolve_choice_audio(c, lang=choice_tts_lang)
            c["has_audio"] = bool(c["resolved_audio"])

        random.shuffle(choices)

        for idx, c in enumerate(choices):
            c["key"] = chr(65 + idx)

        if choices:
            selection_mode = choices[0].get("selection_mode") or "single"

    instruction_text = (training.instruction_text or "").strip()

    prompt_text = (
        training.source_text
        or training.prompt_text
        or training.question.prompt_text
        or ""
    ).strip()

    resolved_answer_text = (
        training.target_answer
        or training.question.answer_text
        or ""
    ).strip()

    # =========================
    # 题干上传音频
    # =========================
    training_audio_url = ""
    if training.audio_file:
        try:
            training_audio_url = training.audio_file.url or ""
        except Exception:
            training_audio_url = ""

    # =========================
    # 回答上传音频
    # =========================
    answer_audio_file_url = ""
    if getattr(training, "answer_audio_file", None):
        try:
            answer_audio_file_url = training.answer_audio_file.url or ""
        except Exception:
            answer_audio_file_url = ""

    # 旧 Question 音频链接字段（仅题干）
    question_audio_url = training.question.audio_url or ""

    use_tts = bool(meta.get("use_tts", False))
    answer_use_tts = bool(
        getattr(training, "answer_use_tts", False)
        or meta.get("answer_use_tts", False)
    )

    asr_cfg = meta.get("asr", {}) if isinstance(meta.get("asr"), dict) else {}
    asr_lang = asr_cfg.get("lang") or "en-US"

    # =========================
    # read_cloze：根据记忆等级动态增加空格
    # =========================
    resolved_cloze_text = training.cloze_text or ""
    resolved_cloze_answers = training.cloze_answers or []

    if training.item_type == "read_cloze":
        cloze_meta = meta.get("cloze", {}) if isinstance(meta.get("cloze"), dict) else {}
        auto_increase_blank = bool(cloze_meta.get("auto_increase_blank", False))

        level_name = _resolve_cloze_level_by_memory(memory)

        pinned_layout = None
        if request is not None:
            pinned_layout = _session_get_pinned_cloze_layout(request, training.question_id)

        if pinned_layout:
            resolved_cloze_text = pinned_layout.get("cloze_text") or resolved_cloze_text
            resolved_cloze_answers = pinned_layout.get("cloze_answers") or resolved_cloze_answers

        elif auto_increase_blank:
            base_min = cloze_meta.get("min_blank", 1)
            base_max = cloze_meta.get("max_blank", 2)

            dynamic_min, dynamic_max = _resolve_cloze_blank_range(
                level_name,
                base_min,
                base_max
            )

            cloze_seed_key = f"q{training.question_id}-lvl{level_name}-range{dynamic_min}-{dynamic_max}"

            cloze_base_text = (
                training.target_answer
                or training.question.answer_text
                or ""
            ).strip()

            dynamic_cloze_text = ""
            dynamic_cloze_answers = []

            if cloze_base_text:
                dynamic_cloze_text, dynamic_cloze_answers = generate_cloze(
                    cloze_base_text,
                    min_blank=dynamic_min,
                    max_blank=dynamic_max,
                    seed_key=cloze_seed_key
                )

            if dynamic_cloze_text and dynamic_cloze_answers:
                resolved_cloze_text = dynamic_cloze_text
                resolved_cloze_answers = dynamic_cloze_answers

    # =========================
    # 听 / 说题型：题干音频 fallback
    # 优先级：
    # 1. TrainingItem.audio_file（人工上传）
    # 2. Question.audio_url（旧链接字段）
    # 3. TTS 自动生成
    # =========================
    resolved_prompt_audio = training_audio_url or question_audio_url

    print("DEBUG AUDIO:", {
        "training_id": training.id,
        "question_id": training.question_id,
        "training_audio_name": getattr(training.audio_file, "name", ""),
        "training_audio_url": training_audio_url,
        "question_audio_url": question_audio_url,
        "resolved_prompt_audio": resolved_prompt_audio,
        "item_type": training.item_type,
    })

    if (
        not resolved_prompt_audio
        and training.item_type in {"listen_asr", "speak_read"}
        and use_tts
        and prompt_text
    ):
        tts_lang = "en"
        lang_upper = str(asr_lang).lower()

        if lang_upper.startswith("ja"):
            tts_lang = "ja"
        elif lang_upper.startswith("zh"):
            tts_lang = "zh-CN"
        elif lang_upper.startswith("ko"):
            tts_lang = "ko"
        else:
            tts_lang = "en"

        resolved_prompt_audio = _build_tts_audio(
            text=prompt_text,
            lang=tts_lang,
            prefix=f"prompttts_q{training.question_id}"
        )

    # =========================
    # 听 / 说题型：回答音频 fallback
    # 优先级：
    # 1. TrainingItem.answer_audio_file（人工上传）
    # 2. TTS 自动生成回答音频
    # =========================
    resolved_answer_audio = answer_audio_file_url

    if (
        not resolved_answer_audio
        and training.item_type in {"listen_asr", "speak_read"}
        and answer_use_tts
        and resolved_answer_text
    ):
        answer_tts_lang = "en"
        lang_upper = str(asr_lang).lower()

        if lang_upper.startswith("ja"):
            answer_tts_lang = "ja"
        elif lang_upper.startswith("zh"):
            answer_tts_lang = "zh-CN"
        elif lang_upper.startswith("ko"):
            answer_tts_lang = "ko"
        else:
            answer_tts_lang = "en"

        resolved_answer_audio = _build_tts_audio(
            text=resolved_answer_text,
            lang=answer_tts_lang,
            prefix=f"answertts_q{training.question_id}"
        )

    print("DEBUG ANSWER AUDIO:", {
        "training_id": training.id,
        "question_id": training.question_id,
        "answer_audio_name": getattr(getattr(training, "answer_audio_file", None), "name", ""),
        "answer_audio_file_url": answer_audio_file_url,
        "resolved_answer_audio": resolved_answer_audio,
        "answer_use_tts": answer_use_tts,
        "item_type": training.item_type,
    })

    cycle = _build_cycle_status(memory)

    payload = {
        "id": training.id,
        "training_id": training.id,

        "question_id": training.question_id,

        "item_type": training.item_type,
        "type": training.item_type,

        "display_item_type": item_type,

        "instruction_text": instruction_text,

        "prompt_text": prompt_text,
        "prompt": prompt_text,

        "answer_text": resolved_answer_text,
        "target_answer": resolved_answer_text,
        "correct_answers": resolved_cloze_answers or ([resolved_answer_text] if resolved_answer_text else []),

        # 题干音频
        "audio_url": resolved_prompt_audio or "",
        "audio": resolved_prompt_audio or "",

        # 回答音频
        "answer_audio_url": resolved_answer_audio or "",
        "answer_audio": resolved_answer_audio or "",
        "can_autoplay_answer_audio": bool(
            training.item_type in {"listen_asr", "speak_read"}
            and resolved_answer_audio
        ),

        "choices": choices,
        "selection_mode": selection_mode,

        "cloze_text": resolved_cloze_text,
        "cloze_answers": resolved_cloze_answers,

        # =========================
        # 严格循环字段：直接扁平返回给前端
        # =========================
        "memory_level": cycle["level"],
        "cycle_step": cycle["cycle_step"],
        "step_label": cycle["step_label"],
        "stage_label": cycle["stage_label"],
        "stage_group": cycle["stage_group"],
        "next_review_text": cycle["next_review_text"],
        "is_due": cycle["is_due"],
        "is_overdue": cycle["is_overdue"],
        "is_mastered": cycle["is_mastered"],
        "is_reset": cycle["is_reset"],
        "last_result": cycle["last_result"],
        "last_reset_reason": cycle["last_reset_reason"],
        "status_text": cycle["status_text"],

        # 听 / 说题型配置
        "use_tts": use_tts,
        "answer_use_tts": answer_use_tts,
        "asr_lang": asr_lang,
        "allow_partial_match": bool(asr_cfg.get("allow_partial_match", True)),
    }

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

        parsed = _normalize_raw_answer(raw_answer)

        if isinstance(parsed, list):
            user_answers = [
                str(x).strip()
                for x in parsed
                if str(x or "").strip()
            ]
        else:
            single_answer = str(parsed or "").strip()
            user_answers = [single_answer] if single_answer else []

        correct_answers = [
            str(x).strip()
            for x in (training.cloze_answers or [])
            if str(x or "").strip()
        ]

        if len(correct_answers) == 1 and len(user_answers) == 1:
            ua = user_answers[0]
            ca = correct_answers[0]

            if check_answer(ua, ca) or normalize(ca) in normalize(ua):
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

        correct_keys = []
        correct_texts = []

        for c in choices:
            if not c.get("correct"):
                continue

            key = str(c.get("key") or "").strip()
            text = str(c.get("text") or c.get("content") or c.get("audio") or "").strip()

            if key:
                correct_keys.append(key)

            if text:
                correct_texts.append(text)

        user_answers = _normalize_choice_answers(raw_answer)

        def _norm(v):
            return normalize(str(v or ""))

        normalized_user_answers = [_norm(x) for x in user_answers if str(x or "").strip()]
        normalized_correct_keys = [_norm(x) for x in correct_keys if str(x or "").strip()]
        normalized_correct_texts = [_norm(x) for x in correct_texts if str(x or "").strip()]

        if selection_mode == "multi":
            is_correct = (
                sorted(normalized_user_answers) == sorted(normalized_correct_texts)
                or sorted(normalized_user_answers) == sorted(normalized_correct_keys)
            )
        else:
            is_correct = (
                len(normalized_user_answers) == 1
                and (
                    normalized_user_answers[0] in normalized_correct_texts
                    or normalized_user_answers[0] in normalized_correct_keys
                )
            )

        return {
            "is_correct": is_correct,
            "correct_answers": correct_texts or correct_keys,
            "display_answer": " / ".join(correct_texts or correct_keys),
            "user_answers": user_answers,
        }

    # =========================
    # 听 / 说：本质都是识别后的文本比对
    # =========================
    if item_type in {"listen_asr", "speak_read"}:
        parsed = _normalize_raw_answer(raw_answer)

        if isinstance(parsed, list):
            user_answer_raw = " ".join(str(x) for x in parsed if str(x or "").strip())
        else:
            user_answer_raw = str(parsed or "").strip()

        resolved_answer_text = (
            training.target_answer
            or q.answer_text
            or ""
        ).strip()

        allow_partial_match = (meta.get("asr") or {}).get("allow_partial_match", True)
        asr_lang = str((meta.get("asr") or {}).get("lang") or "en-US").strip().lower()

        is_cjk_speech = (
            asr_lang.startswith("ja")
            or asr_lang.startswith("zh")
            or asr_lang.startswith("ko")
        )

        layered = judge_speech_answer_layers(
            user_answer=user_answer_raw,
            correct_answer=resolved_answer_text
        )

        is_correct = layered["is_correct"]

        accepted_answers = _normalize_accepted_answers(
            getattr(training, "accepted_answers", [])
        )

        if not is_correct and accepted_answers:
            for accepted in accepted_answers:
                accepted_layered = judge_speech_answer_layers(
                    user_answer=user_answer_raw,
                    correct_answer=accepted
                )

                if accepted_layered["is_correct"]:
                    layered = {
                        "is_correct": True,
                        "result_level": "reading",
                        "strict_correct": False,
                        "normalized_correct": False,
                        "reading_correct": True,
                        "orthography_correct": False,
                        "feedback_message": "读音正确，但标准书写需要加强",
                    }
                    is_correct = True
                    break

        if (
            not is_correct
            and allow_partial_match
            and is_cjk_speech
        ):
            normalized_user = normalize(user_answer_raw)
            normalized_correct = normalize(resolved_answer_text)

            if (
                normalized_correct in normalized_user
                or normalized_user in normalized_correct
            ):
                layered = {
                    "is_correct": True,
                    "result_level": "normalized",
                    "strict_correct": False,
                    "normalized_correct": True,
                    "reading_correct": False,
                    "orthography_correct": False,
                    "feedback_message": "表达基本正确，但书写形式与标准答案不完全一致",
                }
                is_correct = True

        all_correct_answers = []
        if resolved_answer_text:
            all_correct_answers.append(resolved_answer_text)

        for accepted in accepted_answers:
            if accepted and accepted not in all_correct_answers:
                all_correct_answers.append(accepted)

        return {
            "is_correct": is_correct,
            "correct_answers": all_correct_answers,
            "display_answer": resolved_answer_text,
            "user_answers": raw_answer,
            "result_level": layered["result_level"],
            "strict_correct": layered["strict_correct"],
            "normalized_correct": layered["normalized_correct"],
            "reading_correct": layered["reading_correct"],
            "orthography_correct": layered["orthography_correct"],
            "feedback_message": layered["feedback_message"],
        }

    # =========================
    # 写：统一走 question.answer_text
    # =========================
    parsed = _normalize_raw_answer(raw_answer)

    if isinstance(parsed, list):
        user_answer = normalize(" ".join(str(x) for x in parsed))
    else:
        user_answer = normalize(str(parsed or ""))

    resolved_answer_text = (
        training.target_answer
        or q.answer_text
        or ""
    ).strip()

    correct_text = normalize(resolved_answer_text)
    is_correct = check_answer(user_answer, correct_text)

    return {
        "is_correct": is_correct,
        "correct_answers": [resolved_answer_text] if resolved_answer_text else [],
        "display_answer": resolved_answer_text,
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

    current_step = int(
        getattr(memory, "cycle_step", None)
        if getattr(memory, "cycle_step", None) is not None
        else (getattr(memory, "memory_level", 0) or 0)
    )

    if current_step < 0:
        current_step = 0

    current_rule = _get_strict_step_rule(current_step)
    next_review_at = getattr(memory, "next_review_at", None)
    grace = current_rule.get("grace")

    # =========================
    # 1) 先判定是否已经超出当前锚点容忍窗口
    #    一旦超窗，本轮直接作废，不允许“补做后继续往下”
    # =========================
    is_overdue_reset = (
        current_step > 0
        and next_review_at is not None
        and grace is not None
        and now > (next_review_at + grace)
    )

    if is_overdue_reset:
        memory.cycle_step = 0
        memory.memory_level = 0
        memory.correct_streak = 0
        memory.next_review_at = now
        memory.last_review_at = now
        memory.cycle_started_at = None
        memory.mastered_at = None
        memory.cycle_version = (getattr(memory, "cycle_version", 1) or 1) + 1
        memory.last_result = "overdue_reset"
        memory.last_reset_reason = (
            "short_overdue"
            if current_rule.get("kind") == "short"
            else "long_overdue"
        )
        memory.save()
        return

    # =========================
    # 2) 正确：严格按 step 推进
    # =========================
    if is_correct:
        memory.correct_streak = (memory.correct_streak or 0) + 1
        memory.total_correct = (memory.total_correct or 0) + 1
        _set_wrong_boost(memory, 0)
        memory.last_result = "correct"
        memory.last_reset_reason = ""

        # 第一次答对：正式开始一轮循环
        if current_step == 0:
            memory.cycle_started_at = now
            next_step = 1
        else:
            next_step = current_step + 1

        # 已完成最后一锚点（6个月）
        if next_step > 11:
            next_step = 11
            memory.cycle_step = 11
            memory.memory_level = 11
            memory.mastered_at = now
            memory.next_review_at = None
            memory.last_result = "mastered"
        else:
            memory.cycle_step = next_step
            memory.memory_level = next_step
            memory.next_review_at = get_next_review(next_step, base_time=now)

    # =========================
    # 3) 错误：当前循环直接重置
    # =========================
    else:
        memory.cycle_step = 0
        memory.memory_level = 0
        memory.correct_streak = 0
        memory.total_wrong = (memory.total_wrong or 0) + 1
        _set_wrong_boost(memory, min(_get_wrong_boost(memory) + 3, 10))
        _set_last_wrong_at(memory, now)
        memory.next_review_at = now
        memory.cycle_started_at = None
        memory.mastered_at = None
        memory.cycle_version = (getattr(memory, "cycle_version", 1) or 1) + 1
        memory.last_result = "wrong_reset"
        memory.last_reset_reason = "wrong_answer"

    memory.last_review_at = now
    memory.save()

def _manual_adjust_memory(memory, action):
    """
    手动调整记忆等级（v1）
    - upgrade: 当前 step + 1
    - downgrade: 当前 step - 1
    保留现有严格艾宾浩斯自动规则不变：
    后续答错 / 超窗，仍然会按原逻辑自动 reset。
    """
    if not memory:
        return

    now = timezone.now()

    current_step = int(
        getattr(memory, "cycle_step", None)
        if getattr(memory, "cycle_step", None) is not None
        else (getattr(memory, "memory_level", 0) or 0)
    )

    if current_step < 0:
        current_step = 0

    max_step = 11

    if action == "upgrade":
        next_step = min(current_step + 1, max_step)

        memory.cycle_step = next_step
        memory.memory_level = next_step
        memory.last_result = "manual_upgrade"
        memory.last_reset_reason = ""

        if next_step <= 0:
            memory.next_review_at = now
            memory.mastered_at = None
        elif next_step >= max_step:
            memory.mastered_at = now
            memory.next_review_at = None
        else:
            memory.mastered_at = None
            memory.next_review_at = get_next_review(next_step, base_time=now)

        if current_step == 0 and next_step > 0 and not getattr(memory, "cycle_started_at", None):
            memory.cycle_started_at = now

    elif action == "downgrade":
        next_step = max(current_step - 1, 0)

        memory.cycle_step = next_step
        memory.memory_level = next_step
        memory.last_result = "manual_downgrade"
        memory.last_reset_reason = ""

        if next_step <= 0:
            memory.next_review_at = now
            memory.mastered_at = None
            memory.cycle_started_at = None
        else:
            memory.mastered_at = None
            memory.next_review_at = get_next_review(next_step, base_time=now)

    else:
        raise ValueError(f"unsupported manual action: {action}")

    memory.last_review_at = now
    memory.save()

def _touch_memory_after_wrong_word_replay(memory, is_correct):
    """
    方案 A：
    错词复盘只回写题级强化信号，
    不推进 / 不重置严格 cycle_step 主循环。

    原因：
    一个 cloze 题可能拆成多个错词复盘项，
    如果这里直接调用 update_memory_after_answer()，
    会对同一题重复推进或重复重置。
    """
    if not memory:
        return

    now = timezone.now()

    memory.last_review_at = now

    if is_correct:
        _set_wrong_boost(memory, max(_get_wrong_boost(memory) - 1, 0))
        memory.last_result = "replay_correct"
        memory.last_reset_reason = ""
    else:
        _set_wrong_boost(memory, min(_get_wrong_boost(memory) + 1, 10))
        _set_last_wrong_at(memory, now)
        memory.last_result = "replay_wrong"
        memory.last_reset_reason = "wrong_word_replay"

    memory.save()



def _memory_stage_label(level):
    """
    严格艾宾浩斯循环阶段显示：
    0 ~ 11
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
        9: "第9轮巩固（1个月）",
        10: "第10轮巩固（3个月）",
        11: "第11轮巩固（6个月）",
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
            "cycle_step": 0,
            "step_label": _memory_stage_label(0),
            "stage_label": _memory_stage_label(0),
            "stage_group": _memory_stage_group(0),
            "next_review_text": "待安排",
            "is_due": True,
            "is_overdue": False,
            "is_mastered": False,
            "is_reset": False,
            "last_result": "",
            "last_reset_reason": "",
            "status_text": "新内容，等待开始第一轮巩固",
        }

    level = int(
        getattr(memory, "cycle_step", None)
        if getattr(memory, "cycle_step", None) is not None
        else (getattr(memory, "memory_level", 0) or 0)
    )

    next_review_at = getattr(memory, "next_review_at", None)
    mastered_at = getattr(memory, "mastered_at", None)
    last_result = getattr(memory, "last_result", "") or ""
    last_reset_reason = getattr(memory, "last_reset_reason", "") or ""

    now = timezone.now()
    rule = _get_strict_step_rule(level)
    grace = rule.get("grace")

    is_due = (next_review_at is None) or (next_review_at <= now)
    is_overdue = (
        level > 0
        and next_review_at is not None
        and grace is not None
        and now > (next_review_at + grace)
    )
    is_mastered = bool(mastered_at) or (level >= 11 and next_review_at is None)
    is_reset = last_result in {"wrong_reset", "overdue_reset"}

    if is_mastered:
        status_text = "本轮严格循环已完成（6个月）"
    elif last_result == "replay_wrong":
        status_text = "错词复盘未通过，当前题已提高强化优先级"
    elif last_result == "replay_correct":
        status_text = "错词复盘通过，当前题的强化压力已下降"
    elif last_result == "wrong_reset":
        status_text = "上一题答错，当前循环已重置，需从头开始"
    elif last_result == "overdue_reset":
        if last_reset_reason == "short_overdue":
            status_text = "短期锚点超出允许时间窗，当前循环已重置"
        elif last_reset_reason == "long_overdue":
            status_text = "长期锚点超出允许时间窗，当前循环已重置"
        else:
            status_text = "已超出允许时间窗，当前循环已重置"
    elif next_review_at is None and level == 0:
        status_text = "新内容，等待开始第一轮巩固"
    elif is_overdue:
        status_text = f"已超出允许窗口，原定复习时间：{_next_review_text(next_review_at)}"
    elif is_due:
        status_text = f"当前锚点已到期：{_memory_stage_label(level)}"
    else:
        status_text = f"下一次复习：{_next_review_text(next_review_at)}"

    return {
        "level": level,
        "cycle_step": level,
        "step_label": _memory_stage_label(level),
        "stage_label": _memory_stage_label(level),
        "stage_group": _memory_stage_group(level),
        "next_review_text": _next_review_text(next_review_at),
        "is_due": is_due,
        "is_overdue": is_overdue,
        "is_mastered": is_mastered,
        "is_reset": is_reset,
        "last_result": last_result,
        "last_reset_reason": last_reset_reason,
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

    done_ids = (
        set(getattr(user, "_request", None).session.get("today_done_ids", []))
        if getattr(user, "_request", None)
        else set()
    )

    level_counter = {i: 0 for i in range(12)}
    today_due_count = 0
    overdue_count = 0
    next_review_candidates = []

    for m in memories:
        level = int(
            getattr(m, "cycle_step", None)
            if getattr(m, "cycle_step", None) is not None
            else (getattr(m, "memory_level", 0) or 0)
        )
        if level < 0:
            level = 0
        if level > 11:
            level = 11

        level_counter[level] += 1

        next_review_at = getattr(m, "next_review_at", None)

        if next_review_at:
            local_next = timezone.localtime(next_review_at)
            local_now = timezone.localtime(now)

            rule = _get_strict_step_rule(level)
            grace = rule.get("grace")

            if level > 0:
                next_review_candidates.append(next_review_at)

            is_overdue = (
                level > 0
                and grace is not None
                and now > (next_review_at + grace)
            )

            is_due_today = (
                local_next.date() == local_now.date()
                and next_review_at <= now
                and not is_overdue
            )

            if is_due_today:
                today_due_count += 1

            if is_overdue:
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
        elif avg_level < 8:
            main_stage = "中期巩固"
        else:
            main_stage = "长期巩固"

    next_review_text = "待安排"
    future_candidates = sorted(next_review_candidates)
    if future_candidates:
        next_review_text = _next_review_text(future_candidates[0])

    done_today_count = len(done_ids)

    if overdue_count > 0:
        danger_text = f"当前最危险的是超出允许窗口的内容，共 {overdue_count} 条，建议优先处理。"
    elif today_due_count > 0:
        danger_text = f"今天有 {today_due_count} 条内容到期，建议优先完成今天的循环。"
    else:
        danger_text = "当前没有超窗内容，系统处于稳定推进状态。"

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
        {"label": "1个月", "count": level_counter.get(9, 0)},
        {"label": "3个月", "count": level_counter.get(10, 0)},
        {"label": "6个月", "count": level_counter.get(11, 0)},
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
            "due_now_count": 0,
            "later_today_count": 0,
            "future_count": 0,
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

        level = int(
            getattr(m, "cycle_step", None)
            if getattr(m, "cycle_step", None) is not None
            else (getattr(m, "memory_level", 0) or 0)
        )
        if level < 0:
            level = 0
        if level > 11:
            level = 11

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

            rule = _get_strict_step_rule(level)
            grace = rule.get("grace")

            is_overdue = (
                level > 0
                and grace is not None
                and now > (next_review_at + grace)
            )

            is_due_now = (
                local_next.date() == local_now.date()
                and next_review_at <= now
                and not is_overdue
            )

            is_later_today = (
                local_next.date() == local_now.date()
                and next_review_at > now
                and not is_overdue
            )

            is_future = (
                local_next.date() > local_now.date()
                and not is_overdue
            )

            if is_due_now:
                row["due_now_count"] += 1
                row["today_due_count"] += 1

            if is_later_today:
                row["later_today_count"] += 1

            if is_future:
                row["future_count"] += 1

            if is_overdue:
                row["overdue_count"] += 1

            if level > 0:
                if row["next_review_at"] is None or next_review_at < row["next_review_at"]:
                    row["next_review_at"] = next_review_at

    result = []

    for lesson in lessons:
        row = lesson_map[lesson.id]

        due_now_count = row["due_now_count"]
        later_today_count = row["later_today_count"]
        future_count = row["future_count"]
        overdue_count = row["overdue_count"]

        if overdue_count > 0:
            risk_level = "高风险"
        elif due_now_count > 0:
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

        if overdue_count > 0:
            priority_status = "overdue"
            priority_status_label = "现在可做（已逾期）"
        elif due_now_count > 0:
            priority_status = "due_now"
            priority_status_label = "现在可做"
        elif later_today_count > 0:
            priority_status = "later_today"
            priority_status_label = "今天稍后"
        elif future_count > 0:
            priority_status = "future"
            priority_status_label = "未来安排"
        elif row["new_count"] > 0:
            priority_status = "new_available"
            priority_status_label = "可开始新学"
        else:
            priority_status = "idle"
            priority_status_label = "暂无安排"

        result.append({
            "lesson": lesson,
            "new_count": row["new_count"],
            "short_count": row["short_count"],
            "long_count": row["long_count"],
            "due_now_count": due_now_count,
            "later_today_count": later_today_count,
            "future_count": future_count,
            "today_due_count": due_now_count,
            "overdue_count": overdue_count,
            "next_review_text": _next_review_text(row["next_review_at"]),
            "risk_level": risk_level,
            "main_stage": main_stage,
            "priority_status": priority_status,
            "priority_status_label": priority_status_label,
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
        level = int(
            getattr(m, "cycle_step", None)
            if getattr(m, "cycle_step", None) is not None
            else (getattr(m, "memory_level", 0) or 0)
        )
        if level < 0:
            level = 0
        if level > 11:
            level = 11

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

            rule = _get_strict_step_rule(level)
            grace = rule.get("grace")

            is_overdue = (
                level > 0
                and grace is not None
                and now > (nr + grace)
            )

            is_due_today = (
                local_next.date() == local_now.date()
                and nr <= now
                and not is_overdue
            )

            if is_due_today:
                today_due_count += 1

            if is_overdue:
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

        level = int(
            getattr(memory, "cycle_step", None)
            if getattr(memory, "cycle_step", None) is not None
            else (getattr(memory, "memory_level", 0) or 0)
        )
        if level < 0:
            level = 0
        if level > 11:
            level = 11

        next_review_at = getattr(memory, "next_review_at", None)
        rule = _get_strict_step_rule(level)
        grace = rule.get("grace")

        is_overdue = (
            level > 0
            and next_review_at is not None
            and grace is not None
            and now > (next_review_at + grace)
        )

        is_due = (
            next_review_at is None
            or next_review_at <= now
            or is_overdue
        )

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
            "due_now_count": 0,
            "later_today_count": 0,
            "today_due_count": 0,
            "overdue_count": 0,
            "next_review_at": None,
        }
        for book in books
    }

    for m in memories:
        question = getattr(m, "question", None)
        lesson = getattr(question, "lesson", None) if question else None
        book_id = getattr(lesson, "book_id", None)

        if book_id not in book_map:
            continue

        row = book_map[book_id]

        level = int(
            getattr(m, "cycle_step", None)
            if getattr(m, "cycle_step", None) is not None
            else (getattr(m, "memory_level", 0) or 0)
        )
        if level < 0:
            level = 0
        if level > 11:
            level = 11

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

            rule = _get_strict_step_rule(level)
            grace = rule.get("grace")

            is_overdue = (
                level > 0
                and grace is not None
                and now > (next_review_at + grace)
            )

            is_due_now = (
                local_next.date() == local_now.date()
                and next_review_at <= now
                and not is_overdue
            )

            is_later_today = (
                local_next.date() == local_now.date()
                and next_review_at > now
                and not is_overdue
            )

            if is_due_now:
                row["due_now_count"] += 1
                row["today_due_count"] += 1

            if is_later_today:
                row["later_today_count"] += 1

            if is_overdue:
                row["overdue_count"] += 1

            if level > 0:
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
            "due_now_count": row["due_now_count"],
            "later_today_count": row["later_today_count"],
            "today_due_count": row["today_due_count"],
            "overdue_count": row["overdue_count"],
            "main_stage": main_stage,
            "next_review_text": _next_review_text(row["next_review_at"]),
            "risk_level": risk_level,
            "total_count": total,
        })

    return result


def add_xp(request, is_correct):
    gained_xp = 10 if is_correct else 2

    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    current_profile_xp = int(profile.xp or 0)
    current_session_xp = int(request.session.get("xp", 0) or 0)

    # 取两者较大值作为当前基线，避免 session / profile 其中一边落后时把值写小
    current_xp = max(current_profile_xp, current_session_xp)

    xp = current_xp + gained_xp
    level = int(xp ** 0.5)

    today = timezone.localdate()

    if profile.last_study_date == today:
        streak = int(profile.streak or 0)
    elif profile.last_study_date == (today - timedelta(days=1)):
        streak = int(profile.streak or 0) + 1
    else:
        streak = 1

    profile.xp = xp
    profile.level = level
    profile.streak = streak
    profile.last_study_date = today
    profile.save(update_fields=["xp", "level", "streak", "last_study_date"])

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

        level = int(
            getattr(memory, "cycle_step", None)
            if getattr(memory, "cycle_step", None) is not None
            else (getattr(memory, "memory_level", 0) or 0)
        )
        if level < 0:
            level = 0
        if level > 11:
            level = 11

        next_review_at = getattr(memory, "next_review_at", None)
        rule = _get_strict_step_rule(level)
        grace = rule.get("grace")

        is_overdue = (
            level > 0
            and next_review_at is not None
            and grace is not None
            and now > (next_review_at + grace)
        )

        due = (
            next_review_at is None
            or next_review_at <= now
            or is_overdue
        )

        is_new = (memory.total_correct or 0) == 0 and (memory.total_wrong or 0) == 0
        next_review_text = _next_review_text(next_review_at)


        plan.append({
            "training": item,
            "question": item.question,
            "lesson": item.question.lesson,
            "due": due,
            "is_overdue": is_overdue,
            "level": level,
            "wrong_boost": _get_wrong_boost(memory),
            "last_wrong_at": getattr(memory, "last_wrong_at", None),
            "is_new": is_new,
            "next_review_at": next_review_at,
            "next_review_text": next_review_text,
        })

    def _sort_key(x):
        last_wrong_ts = 0
        if x["last_wrong_at"]:
            last_wrong_ts = -x["last_wrong_at"].timestamp()

        return (
            not x["is_overdue"],     # 超窗最优先
            not x["due"],            # 到期优先
            -x["wrong_boost"],       # 错题强化优先
            not x["is_new"],         # 新题优先
            x["level"],              # step 低优先
            last_wrong_ts,           # 最近错的更优先
        )

    plan.sort(key=_sort_key)

    plan = plan[:daily_limit]

    done_ids = _get_today_done_ids(request)

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
    严格艾宾浩斯版智能队列：
    1. 超窗题优先
    2. 到期题优先
    3. wrong_boost 高的题优先
    4. 新题适度进入
    5. cycle_step 低的优先
    6. 已完成本轮严格循环的题跳过
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

        level = int(
            getattr(memory, "cycle_step", None)
            if getattr(memory, "cycle_step", None) is not None
            else (getattr(memory, "memory_level", 0) or 0)
        )
        if level < 0:
            level = 0
        if level > 11:
            level = 11

        wrong_boost = _get_wrong_boost(memory)
        next_review_at = getattr(memory, "next_review_at", None)
        total_correct = getattr(memory, "total_correct", 0) or 0
        total_wrong = getattr(memory, "total_wrong", 0) or 0
        mastered_at = getattr(memory, "mastered_at", None)

        rule = _get_strict_step_rule(level)
        grace = rule.get("grace")

        is_overdue = (
            level > 0
            and next_review_at is not None
            and grace is not None
            and now > (next_review_at + grace)
        )

        is_due = (
            next_review_at is None
            or next_review_at <= now
            or is_overdue
        )

        is_new = (total_correct == 0 and total_wrong == 0)
        is_mastered = bool(mastered_at) or (level >= 11 and next_review_at is None)

        if is_mastered:
            continue

        score = 0

        # 1) 超窗题最高优先
        if is_overdue:
            score += 2000
        # 2) 正常到期题其次
        elif is_due:
            score += 1000

        # 3) 错题强化
        score += wrong_boost * 100

        # 4) 新题适度优先
        if is_new:
            score += 80

        # 5) step 越低越优先
        score += max(0, 30 - level * 2)

        # 6) 最近错过的再轻微提权
        last_wrong_at = getattr(memory, "last_wrong_at", None)
        last_wrong_ts = 0
        if last_wrong_at:
            minutes_since_wrong = max((now - last_wrong_at).total_seconds() / 60, 0)
            last_wrong_ts = -last_wrong_at.timestamp()
            if minutes_since_wrong <= 30:
                score += 40
            elif minutes_since_wrong <= 180:
                score += 20

        pool.append({
            "id": item.id,
            "score": score,
            "is_overdue": is_overdue,
            "is_due": is_due,
            "is_new": is_new,
            "wrong_boost": wrong_boost,
            "level": level,
            "last_wrong_ts": last_wrong_ts,
        })

    if not pool:
        return []

    # =========================
    # 分桶
    # =========================
    overdue_items = [x for x in pool if x["is_overdue"]]
    due_items = [x for x in pool if x["is_due"] and not x["is_overdue"]]
    wrong_items = [x for x in pool if x["wrong_boost"] > 0 and not x["is_overdue"]]
    new_items = [x for x in pool if x["is_new"] and not x["is_due"]]
    normal_items = [x for x in pool if not x["is_due"] and not x["is_new"]]

    # 各桶内部排序
    sort_key = lambda x: (-x["score"], x["level"], x["last_wrong_ts"], x["id"])

    overdue_items.sort(key=sort_key)
    due_items.sort(key=sort_key)
    wrong_items.sort(key=sort_key)
    new_items.sort(key=sort_key)
    normal_items.sort(key=sort_key)

    # =========================
    # 配比
    # =========================
    overdue_quota = max(1, int(limit * 0.3))
    due_quota = max(1, int(limit * 0.3))
    wrong_quota = max(1, int(limit * 0.2))
    new_quota = max(1, int(limit * 0.1))

    selected = []

    selected += overdue_items[:overdue_quota]
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
    if len(selected) < limit:
        for x in normal_items:
            if x["id"] in seen:
                continue
            selected.append(x)
            seen.add(x["id"])
            if len(selected) >= limit:
                break

    # 还不够，再从所有池子高分补齐
    if len(selected) < limit:
        fallback = sorted(pool, key=sort_key)
        for x in fallback:
            if x["id"] in seen:
                continue
            selected.append(x)
            seen.add(x["id"])
            if len(selected) >= limit:
                break

    # 轻度打散，避免完全固定顺序
    top = selected[:5]
    rest = selected[5:]

    random.shuffle(top)
    random.shuffle(rest)

    final_items = top + rest

    print("🔥 smart_queue =", [x["id"] for x in final_items[:limit]])

    return [x["id"] for x in final_items[:limit]]

# =========================
# 训练范围工具
# =========================
def _get_train_scope_label(scope):
    return "整本训练" if scope == "book" else "本课训练"


def _get_train_scope_target_text(scope):
    return "这本书" if scope == "book" else "这课"


def _get_scope_training_qs(scope, obj):
    qs = TrainingItem.objects.select_related("question__lesson")

    if scope == "book":
        return qs.filter(question__lesson__book=obj)

    return qs.filter(question__lesson=obj)


def _training_in_scope(training, scope, obj):
    if scope == "book":
        return training.question.lesson.book_id == obj.id

    return training.question.lesson_id == obj.id


def _wrong_word_item_in_scope(item, scope, obj):
    lesson_id = item.get("lesson_id")

    if scope == "book":
        return Lesson.objects.filter(
            id=lesson_id,
            book_id=obj.id
        ).exists()

    return lesson_id == obj.id


def _get_scope_plan_items(plan_items, scope, obj):
    return [
        item for item in plan_items
        if _training_in_scope(item["training"], scope, obj)
    ]

def _get_today_done_ids(request):
    today_str = str(timezone.localdate())
    session_date = request.session.get("today_done_date")

    if session_date != today_str:
        request.session["today_done_date"] = today_str
        request.session["today_done_ids"] = []
        return []

    return list(request.session.get("today_done_ids", []))


def _add_today_done_id(request, training_id):
    done_ids = _get_today_done_ids(request)

    if training_id not in done_ids:
        done_ids.append(training_id)
        request.session["today_done_ids"] = done_ids

    return done_ids


def _build_scope_plan_stats(request, scope_items):
    done_ids = set(_get_today_done_ids(request))
    total = len(scope_items)

    done = sum(
        1 for item in scope_items
        if item["training"].id in done_ids
    )

    progress = int(done * 100 / total) if total > 0 else 0

    return {
        "total": total,
        "done": done,
        "progress": progress,
    }


def _render_train_page(request, scope, obj):
    plan = get_today_plan(request)
    scope_plan_items = _get_scope_plan_items(plan["items"], scope, obj)
    scope_plan_stats = _build_scope_plan_stats(request, scope_plan_items)
    all_count = _get_scope_training_qs(scope, obj).count()

    context = {
        "train_scope": scope,
        "train_scope_label": _get_train_scope_label(scope),
        "train_title": obj.title,
        "book": obj if scope == "book" else obj.book,
        "lesson": obj if scope == "lesson" else None,
        "plan_total": scope_plan_stats["total"] if scope_plan_items else all_count,
        "plan_done": scope_plan_stats["done"] if scope_plan_items else 0,
        "plan_progress": scope_plan_stats["progress"] if scope_plan_items else 0,
        "head_actions": (
            [
                {"label": "← 返回训练", "url": "javascript:history.back()"},
                {"label": "题目列表", "url": reverse("lesson-question-list", args=[obj.id])},
                {"label": "编辑章节", "url": reverse("lesson-edit", args=[obj.id])},
                {"label": "返回书册", "url": reverse("book-detail", args=[obj.book.id])},
                {"label": "返回首页", "url": reverse("dashboard")},
            ]
            if scope == "lesson"
            else [
                {"label": "← 返回书册", "url": reverse("book-detail", args=[obj.id])},
                {"label": "返回首页", "url": reverse("dashboard")},
            ]
        ),
        "head_meta": (
            [
                {"label": "书册：", "text": obj.book.title},
                {"label": "章节：", "text": obj.title},
            ]
            if scope == "lesson"
            else [
                {"label": "书册：", "text": obj.title},
            ]
        ),
        "head_chips": [
            {"kind": "warning", "text": "阶段：加载中..."},
            {"kind": "primary", "text": "复习：加载中..."},
            {"kind": "primary", "text": "状态：加载中..."},
            {"kind": "danger", "text": "来源：加载中..."},
        ],
    }

    if scope == "lesson":
        context.update({
            "lesson_cycle_summary": get_lesson_cycle_summary(request.user, obj),
            "lesson_round_progress": get_lesson_round_progress(request, obj),
        })

    return render(request, "train/train.html", context)

# =========================
# 页面：训练页
# =========================
@login_required
def book_train(request, book_id):
    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )

    return _render_train_page(request, "book", book)


@login_required
def lesson_train(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    return _render_train_page(request, "lesson", lesson)


# =========================
# API：无刷新训练（完整版）
# =========================
def _train_api_by_scope(request, scope, obj):
    _session_prune_deleted_training_refs(request)

    scope_label = _get_train_scope_label(scope)
    target_text = _get_train_scope_target_text(scope)

    # =========================
    # GET：出题（走SRS调度）
    # =========================
    if request.method == "GET":

        print("🔥 API HIT")

        done_ids = request.session.get("today_done_ids", [])

        # =========================
        # 0) 错词回炉优先：只回炉错掉的那个 blank
        # =========================
        wrong_word_queue = _session_get_wrong_word_queue(request)

        scoped_wrong_items = [
            item for item in wrong_word_queue
            if _wrong_word_item_in_scope(item, scope, obj)
        ]

        if scoped_wrong_items:
            replay_payload = _build_wrong_word_payload(scoped_wrong_items[0])

            replay_payload.update({
                "empty": False,
                "train_scope": scope,
                "train_scope_label": scope_label,
                "is_wrong_word_replay": True,
            })

            return JsonResponse(replay_payload)

        # =========================
        # 1) 当前范围内的全部训练项
        #    lesson -> 当前课
        #    book   -> 当前书
        # =========================
        all_training_items = list(
            _get_scope_training_qs(scope, obj).order_by("id")
        )

        if not all_training_items:
            return JsonResponse({
                "empty": True,
                "reason": "no_material",
                "message": f"{target_text}还没有循环记忆素材，请先新增循环记忆素材。"
            })

        # =========================
        # 2) 今天计划中，先只取当前范围的计划项
        # =========================
        plan = get_today_plan(request)
        scope_plan_items = _get_scope_plan_items(plan["items"], scope, obj)
        scope_plan_stats = _build_scope_plan_stats(request, scope_plan_items)

        if scope_plan_items:
            source_items = scope_plan_items
        else:
            source_items = [
                {"training": item}
                for item in all_training_items
            ]

        remaining = [
            item for item in source_items
            if item["training"].id not in done_ids
        ]

        # =========================
        # 3) 只有“今天计划里确实有当前范围，并且都做完了”
        #    才显示今日完成
        # =========================
        if scope_plan_items and not remaining:
            current_now = timezone.now()

            all_next_reviews = sorted(
                [
                    item["next_review_at"]
                    for item in scope_plan_items
                    if item.get("next_review_at")
                ]
            )

            future_next_reviews = [
                dt for dt in all_next_reviews
                if dt > current_now
            ]

            chosen_next_review = None

            if future_next_reviews:
                chosen_next_review = future_next_reviews[0]
            elif all_next_reviews:
                chosen_next_review = all_next_reviews[-1]

            next_review_text = (
                _next_review_text(chosen_next_review)
                if chosen_next_review
                else "待安排"
            )

            print("🔥 today_done debug")
            print("scope_label =", scope_label)
            print("scope_plan_items count =", len(scope_plan_items))
            print("all_next_reviews =", all_next_reviews)
            print("future_next_reviews =", future_next_reviews)
            print(
                "scope_plan_item next_review_at list =",
                [item.get("next_review_at") for item in scope_plan_items]
            )
            print("chosen_next_review =", chosen_next_review)
            print("next_review_text =", next_review_text)

            return JsonResponse({
                "empty": True,
                "reason": "today_done",
                "message": f"今天{scope_label}的学习计划已经完成了。",
                "next_review_text": next_review_text,
            })

        # =========================
        # 4) 如果今天计划里没有当前范围，
        #    就直接进入当前范围训练
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

        ranked_remaining = []

        for entry in remaining:
            training_obj = entry["training"]
            memory_obj = get_item_memory(request.user, training_obj)
            cycle_obj = _build_cycle_status(memory_obj)

            if cycle_obj.get("is_mastered"):
                continue

            wrong_boost = _get_wrong_boost(memory_obj) if memory_obj else 0
            total_correct = getattr(memory_obj, "total_correct", 0) or 0
            total_wrong = getattr(memory_obj, "total_wrong", 0) or 0
            is_new = (total_correct == 0 and total_wrong == 0)

            last_wrong_at = getattr(memory_obj, "last_wrong_at", None)
            last_wrong_ts = 0
            if last_wrong_at:
                last_wrong_ts = -last_wrong_at.timestamp()

            ranked_remaining.append({
                "training": training_obj,
                "memory": memory_obj,
                "cycle": cycle_obj,
                "wrong_boost": wrong_boost,
                "is_new": is_new,
                "last_wrong_ts": last_wrong_ts,
            })

        ranked_remaining.sort(
            key=lambda x: (
                not x["cycle"].get("is_overdue", False),
                not x["cycle"].get("is_due", False),
                -x["wrong_boost"],
                not x["is_new"],
                x["cycle"].get("cycle_step", 0),
                x["last_wrong_ts"],
                x["training"].id,
            )
        )

        if not ranked_remaining:
            current_now = timezone.now()

            all_next_reviews = sorted(
                [
                    item["next_review_at"]
                    for item in scope_plan_items
                    if item.get("next_review_at")
                ]
            )

            future_next_reviews = [
                dt for dt in all_next_reviews
                if dt > current_now
            ]

            chosen_next_review = None

            if future_next_reviews:
                chosen_next_review = future_next_reviews[0]
            elif all_next_reviews:
                chosen_next_review = all_next_reviews[-1]

            next_review_text = (
                _next_review_text(chosen_next_review)
                if chosen_next_review
                else "待安排"
            )

            return JsonResponse({
                "empty": True,
                "reason": "all_mastered",
                "message": f"{target_text}当前已全部完成本轮严格循环。",
                "next_review_text": next_review_text,
            })

        training = ranked_remaining[0]["training"]
        memory = ranked_remaining[0]["memory"]
        payload = build_training_payload(training, memory, request=request)

        payload.update({
            "empty": False,
            "plan_total": scope_plan_stats["total"] if scope_plan_items else len(all_training_items),
            "plan_done": scope_plan_stats["done"] if scope_plan_items else 0,
            "plan_progress": scope_plan_stats["progress"] if scope_plan_items else 0,
            "is_today_plan": bool(scope_plan_items),
            "train_scope": scope,
            "train_scope_label": scope_label,
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
                if (
                    item.get("replay_id") == training_id
                    and _wrong_word_item_in_scope(item, scope, obj)
                ):
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

            origin_training_id = target.get("training_id")
            origin_training = _get_scope_training_qs(scope, obj).filter(
                id=origin_training_id
            ).first()

            if is_correct:
                has_remaining_replay_for_same_training = any(
                    x.get("training_id") == origin_training_id
                    for x in wrong_word_queue
                )

                if not has_remaining_replay_for_same_training and origin_training:
                    _session_clear_pinned_cloze_layout(
                        request,
                        origin_training.question_id
                    )

            if origin_training:
                replay_memory = get_item_memory(request.user, origin_training)
                _touch_memory_after_wrong_word_replay(replay_memory, is_correct)

            replay_cycle_after = (
                _build_cycle_status(replay_memory)
                if origin_training else
                _build_cycle_status(None)
            )

            xp = add_xp(request, is_correct)

            StudyLog.objects.create(
                user=request.user,
                question=origin_training.question if origin_training else None,
                training_item=origin_training if origin_training else None,
                is_correct=is_correct,
                user_answer=json.dumps(
                    _normalize_raw_answer(raw_answer),
                    ensure_ascii=False
                ),
                mode="wrong_word_replay",
                duration_ms=max(int(duration or 0), 0),
            )

            return JsonResponse({
                "ok": True,
                "is_correct": is_correct,
                "result": (
                    "✅ 错词复盘正确"
                    if is_correct else
                    f"❌ 错词复盘错误，正确回答：{judge['display_answer']}"
                ),
                "speed": get_speed_level(duration),
                "xp": xp,
                "cycle_after": replay_cycle_after,
                "correct_answers": judge["correct_answers"],
                "training_id": training_id,
                "type": "read_cloze",
                "prompt": target.get("prompt", ""),
                "cloze_text": target.get("cloze_text", ""),
                "choices": [],
            })

        # -------------------------
        # 正常 TrainingItem
        # -------------------------
        training = get_object_or_404(
            _get_scope_training_qs(scope, obj),
            id=training_id
        )

        judge = judge_training_answer(training, raw_answer)

        is_correct = judge["is_correct"]

        memory = get_item_memory(request.user, training)
        if not memory:
            memory, _ = QuestionMemory.objects.get_or_create(
                user=request.user,
                question=training.question
            )

        current_payload_before_update = build_training_payload(
            training,
            memory,
            request=request
        )

        cycle_before = _build_cycle_status(memory)

        update_memory_after_answer(memory, is_correct)
        memory.refresh_from_db()

        cycle_after = _build_cycle_status(memory)

        memory_level_before = int(
            cycle_before.get("level", 0) or 0
        )

        memory_level_after = int(
            cycle_after.get("level", 0) or 0
        )

        memory_delta = memory_level_after - memory_level_before

        review_result = getattr(memory, "last_result", "") or ""
        reset_reason = getattr(memory, "last_reset_reason", "") or ""

        # 只有答对才计入今日完成
        if is_correct:
            _add_today_done_id(request, training.id)

        # Cloze：答错时冻结当前空位，并进入错词复盘队列；答对时清除冻结
        if training.item_type == "read_cloze":
            if not is_correct:
                user_answers = judge.get("user_answers", [])
                correct_answers = judge.get("correct_answers", [])

                _session_pin_cloze_layout(
                    request=request,
                    question_id=training.question_id,
                    cloze_text=current_payload_before_update.get("cloze_text", ""),
                    cloze_answers=current_payload_before_update.get("cloze_answers", []),
                    level_name=_resolve_cloze_level_by_memory(memory),
                )

                _session_push_wrong_word_items(
                    request=request,
                    lesson_id=training.question.lesson_id,
                    training=training,
                    user_answers=user_answers,
                    correct_answers=correct_answers,
                )
            else:
                _session_clear_pinned_cloze_layout(request, training.question_id)

        xp = add_xp(request, is_correct)

        StudyLog.objects.create(
            user=request.user,
            question=training.question if training else None,
            training_item=training,
            is_correct=is_correct,
            user_answer=json.dumps(
                _normalize_raw_answer(raw_answer),
                ensure_ascii=False
            ),
            mode="normal",
            duration_ms=max(int(duration or 0), 0),
        )

        # =========================
        # 队列更新（核心）
        # =========================
        queue = request.session.get("training_queue", [])

        if queue:
            current_id = queue.pop(0)

            if not is_correct:
                queue.insert(1 if len(queue) > 0 else 0, current_id)

            request.session["training_queue"] = queue

        plan = get_today_plan(request)
        scope_plan_items = _get_scope_plan_items(plan["items"], scope, obj)
        scope_plan_stats = _build_scope_plan_stats(request, scope_plan_items)
        all_count = _get_scope_training_qs(scope, obj).count()

        lesson_round_progress = None
        if scope == "lesson":
            lesson_round_progress = get_lesson_round_progress(request, obj)

        return JsonResponse({
            "ok": True,
            "is_correct": is_correct,
            "result": (
                f"✅ 正确（Lv {memory.memory_level if memory else 0}）"
                if is_correct else
                f"❌ 错误，正确回答：{judge['display_answer']}"
            ),
            "speed": get_speed_level(duration),
            "xp": xp,
            "memory_level": memory.memory_level if memory else 0,
            "memory_level_before": memory_level_before,
            "memory_level_after": memory_level_after,
            "memory_delta": memory_delta,
            "review_result": review_result,
            "reset_reason": reset_reason,
            "correct_answers": judge["correct_answers"],
            "plan_total": scope_plan_stats["total"] if scope_plan_items else all_count,
            "plan_done": scope_plan_stats["done"] if scope_plan_items else 0,
            "plan_progress": scope_plan_stats["progress"] if scope_plan_items else 0,
            "lesson_round_progress": lesson_round_progress,
            "cycle_before": cycle_before,
            "cycle_after": cycle_after,
            "cycle_feedback": (
                f"回答正确，已进入：{cycle_after['stage_label']}；{cycle_after['status_text']}"
                if is_correct else
                f"回答错误，已回退到：{cycle_after['stage_label']}；{cycle_after['status_text']}"
            ),
            "train_scope": scope,
            "train_scope_label": scope_label,
            **build_training_payload(training, memory, request=request),
        })

    return JsonResponse({"ok": False, "error": "method not allowed"}, status=405)


def book_train_api(request, book_id):
    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )

    return _train_api_by_scope(request, "book", book)


def _manual_memory_action_api(request, scope, obj, action):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "method not allowed"}, status=405)

    training_id = request.POST.get("training_id")

    if not training_id:
        return JsonResponse({"ok": False, "error": "missing training_id"}, status=400)

    training = get_object_or_404(
        _get_scope_training_qs(scope, obj),
        id=training_id
    )

    memory = get_item_memory(request.user, training)
    if not memory:
        memory, _ = QuestionMemory.objects.get_or_create(
            user=request.user,
            question=training.question
        )

    cycle_before = _build_cycle_status(memory)

    try:
        _manual_adjust_memory(memory, action)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    memory.refresh_from_db()
    cycle_after = _build_cycle_status(memory)

    return JsonResponse({
        "ok": True,
        "action": action,
        "training_id": training.id,
        "memory_level": memory.memory_level if memory else 0,
        "memory_level_before": int(cycle_before.get("level", 0) or 0),
        "memory_level_after": int(cycle_after.get("level", 0) or 0),
        "memory_delta": int(cycle_after.get("level", 0) or 0) - int(cycle_before.get("level", 0) or 0),
        "review_result": getattr(memory, "last_result", "") or "",
        "reset_reason": getattr(memory, "last_reset_reason", "") or "",
        "cycle_before": cycle_before,
        "cycle_after": cycle_after,
        "result": (
            "✅ 已手动升一级"
            if action == "upgrade" else
            "⚠️ 已手动降一级"
        ),
    })


def book_train_manual_upgrade(request, book_id):
    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )
    return _manual_memory_action_api(request, "book", book, "upgrade")


def book_train_manual_downgrade(request, book_id):
    book = get_object_or_404(
        Book,
        id=book_id,
        owner=request.user
    )
    return _manual_memory_action_api(request, "book", book, "downgrade")


def lesson_train_manual_upgrade(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        owner=request.user
    )
    return _manual_memory_action_api(request, "lesson", lesson, "upgrade")


def lesson_train_manual_downgrade(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        owner=request.user
    )
    return _manual_memory_action_api(request, "lesson", lesson, "downgrade")


def lesson_train_api(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    return _train_api_by_scope(request, "lesson", lesson)

@login_required
def lesson_question_list(request, lesson_id):
    lesson = get_object_or_404(
        Lesson,
        id=lesson_id,
        book__owner=request.user
    )

    questions = list(
        Question.objects.filter(
            lesson=lesson
        ).order_by("id")
    )

    for question in questions:
        training = question.training_items.order_by("id").first()

        question.display_qtype = training.item_type if training else ""
        question.display_instruction = (
            (training.instruction_text or "").strip()
            if training else ""
        )
        question.display_source_text = (
            (training.source_text or question.prompt_text or "").strip()
            if training else (question.prompt_text or "").strip()
        )
        question.display_target_answer = (
            (training.target_answer or question.answer_text or "").strip()
            if training else (question.answer_text or "").strip()
        )

    return render(request, "train/question_list.html", {
        "lesson": lesson,
        "book": lesson.book,
        "questions": questions,
        "head_actions": [
            {"label": "← 返回训练", "url": reverse("lesson-train", args=[lesson.id])},
            {"label": "返回章节页", "url": reverse("book-detail", args=[lesson.book.id])},
            {"label": "新增素材", "url": f"{reverse('builder-page')}?lesson_id={lesson.id}"},
        ],
        "head_meta": [
            {"label": "书册：", "text": lesson.book.title},
            {"label": "章节：", "text": lesson.title},
        ],
        "head_chips": [
            {"kind": "primary", "text": f"素材数：{len(questions)}"},
        ],
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
            "due": 0,
            "mastered": 0,
            "new_items": 0,
            "short_items": 0,
            "long_items": 0,
            "learning_summary": "当前学习状态稳定，建议继续按计划推进。",
        }

    now = timezone.now()
    today = now.date()

    memories = QuestionMemory.objects.filter(user=user)

    # =========================
    # 学习条目统计（近似口径）
    # =========================
    today_count = memories.filter(
        last_review_at__date=today,
        total_correct__gt=0
    ).count()

    week_start = now - timedelta(days=7)

    week_count = memories.filter(
        last_review_at__gte=week_start,
        total_correct__gt=0
    ).count()

    # =========================
    # 正确率
    # =========================
    total_correct = sum(m.total_correct or 0 for m in memories)
    total_wrong = sum(m.total_wrong or 0 for m in memories)

    total_answered = total_correct + total_wrong
    accuracy = int((total_correct / total_answered) * 100) if total_answered > 0 else 0

    # =========================
    # 用户成长信息：优先 UserProfile，回退旧逻辑
    # =========================
    profile = UserProfile.objects.filter(user=user).first()

    if profile and int(profile.streak or 0) > 0:
        streak = int(profile.streak or 0)
    else:
        streak = 0
        for i in range(30):
            day = today - timedelta(days=i)

            count = memories.filter(
                last_review_at__date=day,
                total_correct__gt=0
            ).count()

            if count > 0:
                streak += 1
            else:
                break

    session_xp = int(request.session.get("xp", 0) or 0)

    if profile and int(profile.xp or 0) > 0:
        xp = int(profile.xp or 0)
    else:
        xp = session_xp

    if profile and int(profile.level or 0) > 0:
        level = int(profile.level or 0)
    else:
        level = int(xp ** 0.5)

    # =========================
    # 状态类统计
    # =========================
    due_count = memories.filter(
        next_review_at__isnull=False,
        next_review_at__lte=now
    ).count()

    mastered_count = 0

    for memory in memories:
        level_value = int(
            getattr(memory, "cycle_step", None)
            if getattr(memory, "cycle_step", None) is not None
            else (getattr(memory, "memory_level", 0) or 0)
        )

        if level_value < 0:
            level_value = 0
        if level_value > 11:
            level_value = 11

        memory_mastered_at = getattr(memory, "mastered_at", None)
        memory_next_review_at = getattr(memory, "next_review_at", None)

        is_mastered = bool(memory_mastered_at) or (
            level_value >= 11 and memory_next_review_at is None
        )

        if is_mastered:
            mastered_count += 1

    new_items_count = 0
    short_items_count = 0
    long_items_count = 0

    # =========================
    # 阶段分布统计
    # level == 0      -> 新学
    # level 1 ~ 3     -> 短期巩固
    # level 4 及以上  -> 长期巩固
    # =========================
    new_items_count = 0
    short_items_count = 0
    long_items_count = 0

    for memory in memories:
        level_value = int(
            getattr(memory, "cycle_step", None)
            if getattr(memory, "cycle_step", None) is not None
            else (getattr(memory, "memory_level", 0) or 0)
        )

        if level_value < 0:
            level_value = 0
        if level_value > 11:
            level_value = 11

        if level_value == 0:
            new_items_count += 1
        elif 1 <= level_value <= 3:
            short_items_count += 1
        else:
            long_items_count += 1

    # =========================
    # 学习状态总结
    # =========================
    if (
        new_items_count >= short_items_count
        and new_items_count >= long_items_count
    ):
        stage_summary = "当前以新学推进为主"
    elif short_items_count >= long_items_count:
        stage_summary = "当前以短期巩固为主"
    else:
        stage_summary = "当前以长期巩固为主"

    if due_count >= 10:
        pressure_summary = "当前待复习压力较高"
    elif due_count > 0:
        pressure_summary = "当前有待复习内容，建议优先处理"
    else:
        pressure_summary = "当前待复习压力较低"

    learning_summary = f"{stage_summary}；{pressure_summary}。"

    return {
        "today": int(today_count or 0),
        "week": int(week_count or 0),
        "streak": int(streak or 0),
        "accuracy": int(accuracy or 0),
        "xp": int(xp or 0),
        "level": int(level or 0),
        "due": int(due_count or 0),
        "mastered": int(mastered_count or 0),
        "new_items": int(new_items_count or 0),
        "short_items": int(short_items_count or 0),
        "long_items": int(long_items_count or 0),
        "learning_summary": learning_summary,
    }


# =========================
# Builder 页面
# =========================
@login_required
def builder_page(request):

    # =========================
    # ① 读取 lesson_id（来自 ?lesson_id=4）
    # =========================
    lesson_id = request.GET.get("lesson_id")

    current_lesson = None
    current_book = None

    from ..models import Lesson

    if lesson_id:
        try:
            current_lesson = Lesson.objects.select_related("book").get(id=lesson_id)
            current_book = current_lesson.book
        except Lesson.DoesNotExist:
            current_lesson = None
            current_book = None

    # =========================
    # ② 提供 lesson 列表（给下拉框）
    # =========================
    lessons = Lesson.objects.select_related("book").all().order_by("id")

    # =========================
    # ③ 渲染
    # =========================
    return render(request, "train/builder.html", {
        "lessons": lessons,
        "current_lesson": current_lesson,
        "current_book": current_book,
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
    1) 单回答
    2) 多回答：换行 / 逗号 / 分号 / 斜杠 / 顿号 分隔
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

        text = (c.get("text") or c.get("content") or "").strip()
        audio = (c.get("audio") or "").strip()
        use_tts_when_no_audio = bool(c.get("use_tts_when_no_audio", False))
        correct = bool(c.get("correct"))

        # 所有选项都必须有文字
        if not text:
            continue

        item = {
            "key": chr(65 + idx),   # A / B / C / D
            "type": ctype if ctype in {"text", "audio"} else "text",
            "text": text,
            "content": text,
            "audio": audio,
            "use_tts_when_no_audio": use_tts_when_no_audio,
            "correct": correct,
            "selection_mode": selection_mode,
            "reveal_text_on_wrong": reveal_text_on_wrong,
        }

        if correct:
            correct_texts.append(text)

        normalized.append(item)

    return normalized, correct_texts


@csrf_exempt
@login_required
def builder_save(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    uploaded_audio_file = None
    uploaded_answer_audio_file = None

    if request.content_type and request.content_type.startswith("multipart/form-data"):
        payload_raw = (request.POST.get("payload") or "").strip()
        data = _safe_json_loads(payload_raw) if payload_raw else {}
        uploaded_audio_file = request.FILES.get("audio_file")
        uploaded_answer_audio_file = request.FILES.get("answer_audio_file")
    else:
        data = _safe_json_loads(request.body)

    lesson_id = data.get("lesson_id")
    skill = (data.get("skill") or "read").strip()
    item_type = (data.get("item_type") or "").strip()

    # 兼容旧字段 + 新字段
    instruction_text = (data.get("instruction_text") or "").strip()

    source_text = (
        data.get("source_text")
        or data.get("prompt_text")
        or data.get("prompt")
        or ""
    ).strip()

    target_answer = (
        data.get("target_answer")
        or data.get("answer_text")
        or data.get("answer")
        or ""
    ).strip()

    prompt_text = source_text
    answer_text = target_answer
    prompt_audio = (data.get("prompt_audio") or data.get("audio_url") or "").strip()
    answer_audio = (data.get("answer_audio") or "").strip()

    accepted_answers_text = (data.get("accepted_answers_text") or "").strip()
    accepted_answers = [
        line.strip()
        for line in accepted_answers_text.splitlines()
        if line.strip()
    ]

    use_tts = bool(data.get("use_tts", False))
    answer_use_tts = bool(data.get("answer_use_tts", False))
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

    # 先创建 question，供后续各题型分支统一使用
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

        if not raw_choices:
            question.delete()
            return JsonResponse({"ok": False, "error": "选择题至少需要填写一个选项"}, status=400)

        if not choices_payload:
            question.delete()
            return JsonResponse({"ok": False, "error": "所有选项都不能为空，且每个选项必须填写文字内容"}, status=400)

        if not correct_texts:
            question.delete()
            return JsonResponse({"ok": False, "error": "选择题至少需要一个正确回答"}, status=400)

        # 回写标准回答，便于后续训练统一判定
        question.answer_text = " / ".join(correct_texts)
        question.save(update_fields=["answer_text"])

        training = TrainingItem.objects.create(
            question=question,
            item_type="read_choice",
            instruction_text=instruction_text or prompt_text,
            source_text=source_text,
            target_answer=question.answer_text or target_answer,
            choices=choices_payload,
            audio_file=uploaded_audio_file,
            answer_audio_file=uploaded_answer_audio_file,
            answer_use_tts=answer_use_tts
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
    # 读：克漏字（自动克漏）
    # 现阶段：
    # - prompt_text 写完整句
    # - 系统自动生成 cloze_text / cloze_answers
    # - 如果用户手工写了 {word}，则优先走手工 parse 逻辑
    # =========================

    # =========================
    # read_cloze 分支
    # =========================
    if item_type == "read_cloze":

        min_blank = int(cloze_cfg.get("min_blank", 1) or 1)
        max_blank = int(cloze_cfg.get("max_blank", 2) or 2)

        if max_blank < min_blank:
            max_blank = min_blank

        cloze_base_text = (
            target_answer
            or answer_text
            or ""
        ).strip()

        if not cloze_base_text:
            question.delete()
            return JsonResponse({
                "ok": False,
                "error": "克漏字题必须先填写回答内容"
            }, status=400)

        cloze_text, cloze_answers = generate_cloze(
            cloze_base_text,
            min_blank=min_blank,
            max_blank=max_blank
        )

        if not cloze_text or "____" not in cloze_text:
            question.delete()
            return JsonResponse({
                "ok": False,
                "error": "自动克漏生成失败，请检查题干内容"
            }, status=400)

        if not cloze_answers:
            question.delete()
            return JsonResponse({
                "ok": False,
                "error": "自动克漏未生成回答，请检查题干内容"
            }, status=400)

        training = TrainingItem.objects.create(
            question=question,
            item_type="read_cloze",
            prompt_text=prompt_text,
            instruction_text=instruction_text or prompt_text,
            source_text=source_text,
            target_answer=target_answer or question.answer_text,
            manual_cloze_text=cloze_text,
            cloze_text=cloze_text,
            cloze_answers=cloze_answers,
            choices=[{
                "_meta": {
                    "skill": skill,
                    "item_type": item_type,
                    "cloze": cloze_cfg,
                    "auto_generated": True
                }
            }],
            audio_file=uploaded_audio_file,
            answer_audio_file=uploaded_answer_audio_file,
            answer_use_tts=answer_use_tts
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
            return JsonResponse({"ok": False, "error": "写作题必须填写回答"}, status=400)

        training = TrainingItem.objects.create(
            question=question,
            item_type="write",
            instruction_text=instruction_text or prompt_text,
            source_text=source_text,
            target_answer=target_answer,
            choices=[{
                "_meta": {
                    "skill": skill,
                    "item_type": item_type
                }
            }],
            audio_file=uploaded_audio_file,
            answer_audio_file=uploaded_answer_audio_file,
            answer_use_tts=answer_use_tts
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
            instruction_text=instruction_text or prompt_text,
            source_text=source_text,
            target_answer=target_answer or answer_text,
            accepted_answers=accepted_answers,
            choices=[{
                "_meta": {
                    "skill": skill,
                    "item_type": item_type,
                    "use_tts": use_tts,
                    "answer_use_tts": answer_use_tts,
                    "asr": asr_cfg
                }
            }],
            audio_file=uploaded_audio_file,
            answer_audio_file=uploaded_answer_audio_file,
            answer_use_tts=answer_use_tts
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

    training = question.training_items.order_by("id").first()
    item_type = training.item_type if training else ""

    display_qtype = item_type or ""

    if request.method == "POST":
        instruction_text = (request.POST.get("instruction_text") or "").strip()

        source_text = (
            request.POST.get("source_text")
            or request.POST.get("prompt_text")
            or ""
        ).strip()

        target_answer = (
            request.POST.get("target_answer")
            or request.POST.get("answer_text")
            or ""
        ).strip()

        audio_url = (request.POST.get("audio_url") or "").strip()
        answer_audio_url = (request.POST.get("answer_audio_url") or "").strip()

        accepted_answers_text = (request.POST.get("accepted_answers_text") or "").strip()

        accepted_answers = [
            line.strip()
            for line in accepted_answers_text.splitlines()
            if line.strip()
        ]

        uploaded_audio_file = request.FILES.get("audio_file")
        clear_audio_file = request.POST.get("clear_audio_file") == "1"

        uploaded_answer_audio_file = request.FILES.get("answer_audio_file")
        clear_answer_audio_file = request.POST.get("clear_answer_audio_file") == "1"

        if not source_text:
            return render(request, "train/edit_item.html", {
                "mode": "question",
                "obj": question,
                "training": training,
                "item_type": item_type,
                "display_qtype": display_qtype,
                "next": next_url,
                "page_title": "编辑训练题",
                "error": "题干不能为空",
                "choices_json": json.dumps(training.choices or [], ensure_ascii=False) if training else "[]",
                "cloze_answers_text": "\n".join(training.cloze_answers or []) if training and training.cloze_answers else "",
                "accepted_answers_text": "\n".join(training.accepted_answers or []) if training and training.accepted_answers else "",
                "listen_meta": (
                    ((training.choices or [])[0].get("_meta", {}))
                    if training and training.choices and isinstance((training.choices or [])[0], dict)
                    else {}
                ),
            })

        # 通用字段先保存（旧字段继续兼容）
        question.prompt_text = source_text
        question.answer_text = target_answer
        question.audio_url = audio_url
        question.save(update_fields=["prompt_text", "answer_text", "audio_url"])

        # 新字段同步写入 TrainingItem
        if training:
            training.instruction_text = instruction_text
            training.source_text = source_text
            training.target_answer = target_answer

            if training.item_type in {"listen_asr", "speak_read"}:
                training.accepted_answers = accepted_answers
            else:
                training.accepted_answers = []

            update_fields = [
                "instruction_text",
                "source_text",
                "target_answer",
                "accepted_answers",
            ]

            if clear_audio_file:
                if training.audio_file:
                    training.audio_file.delete(save=False)
                training.audio_file = None
                update_fields.append("audio_file")
            elif uploaded_audio_file:
                if training.audio_file:
                    training.audio_file.delete(save=False)
                training.audio_file = uploaded_audio_file
                update_fields.append("audio_file")

            if clear_answer_audio_file:
                if training.answer_audio_file:
                    training.answer_audio_file.delete(save=False)
                training.answer_audio_file = None
                update_fields.append("answer_audio_file")
            elif uploaded_answer_audio_file:
                if training.answer_audio_file:
                    training.answer_audio_file.delete(save=False)
                training.answer_audio_file = uploaded_answer_audio_file
                update_fields.append("answer_audio_file")

            training.save(update_fields=update_fields)

        # 没有 training 的旧题
        if not training:
            return redirect(next_url)

        # =========================
        # 选择题
        # =========================
        if training.item_type == "read_choice":
            raw_choice_texts = request.POST.getlist("choice_text[]")
            raw_choice_types = request.POST.getlist("choice_type[]")
            raw_choice_audios = request.POST.getlist("choice_audio[]")
            raw_choice_tts_flags = request.POST.getlist("choice_use_tts[]")
            raw_correct_indexes = request.POST.getlist("choice_correct[]")

            selection_mode = "single"
            old_choices = training.choices or []
            if old_choices:
                selection_mode = old_choices[0].get("selection_mode") or "single"

            correct_index_set = {
                int(x) for x in raw_correct_indexes if str(x).isdigit()
            }

            normalized_choices = []
            correct_texts = []

            max_len = max(
                len(raw_choice_texts),
                len(raw_choice_types),
                len(raw_choice_audios),
            ) if (raw_choice_texts or raw_choice_types or raw_choice_audios) else 0

            for idx in range(max_len):
                text = (raw_choice_texts[idx] if idx < len(raw_choice_texts) else "").strip()
                ctype = (raw_choice_types[idx] if idx < len(raw_choice_types) else "text").strip()
                audio = (raw_choice_audios[idx] if idx < len(raw_choice_audios) else "").strip()
                use_tts_when_no_audio = str(idx) in raw_choice_tts_flags
                correct = idx in correct_index_set

                if not text:
                    continue

                item = {
                    "key": chr(65 + len(normalized_choices)),
                    "type": ctype if ctype in {"text", "audio"} else "text",
                    "text": text,
                    "content": text,
                    "audio": audio,
                    "use_tts_when_no_audio": use_tts_when_no_audio,
                    "correct": correct,
                    "selection_mode": selection_mode,
                    "reveal_text_on_wrong": bool(
                        old_choices[0].get("reveal_text_on_wrong", False)
                    ) if old_choices else False,
                }

                normalized_choices.append(item)

                if correct:
                    correct_texts.append(text)

            if normalized_choices and correct_texts:
                resolved_answer_text = " / ".join(correct_texts)

                training.choices = normalized_choices
                training.target_answer = resolved_answer_text
                training.save(update_fields=["choices", "target_answer"])

                question.answer_text = resolved_answer_text
                question.save(update_fields=["answer_text"])

            return redirect(next_url)

        # =========================
        # 克漏字
        # =========================
        if training.item_type == "read_cloze":
            cloze_text = (request.POST.get("cloze_text") or "").strip()
            cloze_answers_text = (request.POST.get("cloze_answers_text") or "").strip()

            cloze_answers = [
                x.strip()
                for x in re.split(r"[\n,，;/；、|]+", cloze_answers_text)
                if x.strip()
            ]

            update_fields = ["cloze_answers"]

            if cloze_text:
                training.cloze_text = cloze_text
                training.manual_cloze_text = cloze_text
                update_fields.extend(["cloze_text", "manual_cloze_text"])

            training.cloze_answers = cloze_answers
            training.save(update_fields=update_fields)

            # 注意：
            # read_cloze 的 cloze_answers 只是空格回答，
            # 不能反向覆盖完整的 target_answer / question.answer_text。
            # 完整回答应继续保持为编辑页中的“回答”字段。

            return redirect(next_url)

        # =========================
        # 听 / 说
        # =========================
        if training.item_type in {"listen_asr", "speak_read"}:
            old_choices = training.choices or []
            meta = {}

            if old_choices and isinstance(old_choices[0], dict):
                meta = old_choices[0].get("_meta", {}) or {}

            skill = meta.get(
                "skill",
                "listen" if training.item_type == "listen_asr" else "speak"
            )
            old_item_type = meta.get("item_type", training.item_type)
            use_tts = request.POST.get("use_tts") == "1"
            answer_use_tts = request.POST.get("answer_use_tts") == "1"
            asr_lang = (request.POST.get("asr_lang") or "en-US").strip()
            allow_partial_match = request.POST.get("allow_partial_match") == "1"

            training.answer_use_tts = answer_use_tts
            training.choices = [{
                "_meta": {
                    "skill": skill,
                    "item_type": old_item_type,
                    "use_tts": use_tts,
                    "answer_use_tts": answer_use_tts,
                    "asr": {
                        "lang": asr_lang,
                        "allow_partial_match": allow_partial_match,
                    }
                }
            }]
            training.save(update_fields=["choices", "answer_use_tts"])

            return redirect(next_url)

        # =========================
        # 写作题 / 其他
        # =========================
        return redirect(next_url)

    return render(request, "train/edit_item.html", {
        "mode": "question",
        "obj": question,
        "training": training,
        "item_type": item_type,
        "display_qtype": display_qtype,
        "next": next_url,
        "page_title": "编辑训练题",
        "choices_json": json.dumps(training.choices or [], ensure_ascii=False) if training else "[]",
        "cloze_answers_text": "\n".join(training.cloze_answers or []) if training and training.cloze_answers else "",
        "accepted_answers_text": "\n".join(training.accepted_answers or []) if training and training.accepted_answers else "",
        "listen_meta": (
            ((training.choices or [])[0].get("_meta", {}))
            if training and training.choices and isinstance((training.choices or [])[0], dict)
            else {}
        ),
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

    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
        or ""
    ).strip()

    # 删除前先拿到关联 training_id，后面要清 session 缓存
    training_ids = list(
        question.training_items.values_list("id", flat=True)
    )

    # =========================
    # 清理 wrong_word_queue
    # =========================
    wrong_word_queue = request.session.get("wrong_word_queue", [])
    if isinstance(wrong_word_queue, list):
        cleaned_wrong_word_queue = []
        for item in wrong_word_queue:
            if not isinstance(item, dict):
                continue
            if item.get("training_id") in training_ids:
                continue
            cleaned_wrong_word_queue.append(item)
        request.session["wrong_word_queue"] = cleaned_wrong_word_queue

    # =========================
    # 清理 pinned_cloze_map
    # =========================
    pinned_cloze_map = request.session.get("pinned_cloze_map", {})
    if isinstance(pinned_cloze_map, dict):
        pinned_cloze_map.pop(str(question.id), None)
        request.session["pinned_cloze_map"] = pinned_cloze_map

    # =========================
    # 清理 training_queue
    # 兼容：
    # - [1, 2, 3]
    # - [{"training_id": 1}, ...]
    # =========================
    training_queue = request.session.get("training_queue", [])
    if isinstance(training_queue, list):
        cleaned_training_queue = []
        for item in training_queue:
            if isinstance(item, int):
                if item in training_ids:
                    continue
                cleaned_training_queue.append(item)
                continue

            if isinstance(item, dict):
                if item.get("training_id") in training_ids:
                    continue
                cleaned_training_queue.append(item)
                continue

            cleaned_training_queue.append(item)

        request.session["training_queue"] = cleaned_training_queue

    question.delete()

    if next_url:
        return redirect(next_url)

    return redirect("lesson-question-list", lesson_id=lesson_id)
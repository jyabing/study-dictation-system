import re
from typing import List, Tuple

from django.utils import timezone

from ..models import WordMemoryState
from .srs_engine import calculate_next_review


STOPWORDS = {
    "a", "an", "the",
    "i", "you", "he", "she", "it", "we", "they",
    "me", "him", "her", "us", "them",
    "my", "your", "his", "their", "our",
    "am", "is", "are", "was", "were",
    "be", "been", "being",
    "do", "does", "did",
    "have", "has", "had",
    "to", "of", "and", "or", "but",
    "in", "on", "at", "for", "from", "with", "by",
    "this", "that", "these", "those",
    "as", "if", "then", "than",
    "can", "could", "will", "would", "shall", "should",
    "ask", "tell", "repeat", "choose"
}


def normalize_word(word: str) -> str:
    if not word:
        return ""
    word = word.lower().strip()
    word = re.sub(r"[^\w\-']", "", word)
    return word


def split_words(text: str) -> List[str]:
    if not text:
        return []
    raw_words = re.split(r"\s+|\|", text.strip())
    words = []
    for w in raw_words:
        nw = normalize_word(w)
        if nw:
            words.append(nw)
    return words


def extract_focus_words(question) -> List[str]:
    """
    根据题型提取需要进行词级SRS的目标词。
    """

    qtype = question.qtype
    answer = (question.answer or "").strip()

    if not answer:
        return []

    words = split_words(answer)

    # cloze / choice：答案本身就是重点词
    if qtype in {"cloze", "choice"}:
        return words

    # qa / listening / speaking：过滤掉功能词，保留重点词
    focus = [w for w in words if w not in STOPWORDS and len(w) > 1]

    # 如果过滤后为空，就退回原答案词
    return focus or words


def split_missed_words(expected_words: List[str], user_input: str) -> Tuple[List[str], List[str]]:
    """
    返回：
    - missed_words: 用户没写出来的词
    - hit_words: 用户写对的词
    """
    user_words = set(split_words(user_input))

    missed_words = []
    hit_words = []

    for w in expected_words:
        if w in user_words:
            hit_words.append(w)
        else:
            missed_words.append(w)

    return missed_words, hit_words


def serialize_word_memory(memory: WordMemoryState) -> dict:
    return {
        "word": memory.word,
        "normalized_word": memory.normalized_word,
        "memory_level": memory.memory_level,
        "wrong_count": memory.wrong_count,
        "review_count": memory.review_count,
        "is_due_boost": memory.is_due_boost,
        "next_review": (
            timezone.localtime(memory.next_review).strftime("%Y-%m-%d %H:%M")
            if memory.next_review else None
        )
    }


def update_word_memory_states(question, user_input: str, is_correct: bool, now=None) -> dict:
    """
    词级SRS + 错词强化

    规则：
    1. 先提取本题的目标词
    2. 如果整题答对：
       - 目标词全部推进等级
    3. 如果整题答错：
       - 用户没写出来的词进入错词强化
       - 错词立即进入 5分钟复习
       - 用户写对的词仍可轻微推进
    """

    if now is None:
        now = timezone.now()

    expected_words = extract_focus_words(question)

    if not expected_words:
        return {
            "expected_words": [],
            "missed_words": [],
            "hit_words": [],
            "updated_words": []
        }

    missed_words, hit_words = split_missed_words(expected_words, user_input)

    updated_words = []

    # 整题答对：所有目标词提升
    if is_correct:
        for w in expected_words:
            memory, _ = WordMemoryState.objects.get_or_create(
                normalized_word=w,
                defaults={
                    "word": w,
                    "source_sentence": question.sentence,
                    "memory_level": 0
                }
            )

            memory.word = w
            memory.source_sentence = question.sentence
            memory.review_count += 1
            memory.last_review = now
            memory.is_due_boost = False

            # 最多推进到 11，沿用现有 srs_engine 的 level 区间
            if memory.memory_level <= 0:
                memory.memory_level = 1
            else:
                memory.memory_level = min(memory.memory_level + 1, 11)

            memory.next_review = calculate_next_review(memory.memory_level, now=now)
            memory.save()

            updated_words.append(serialize_word_memory(memory))

        return {
            "expected_words": expected_words,
            "missed_words": [],
            "hit_words": expected_words,
            "updated_words": updated_words
        }

    # 整题答错：错词强化
    for w in expected_words:
        memory, _ = WordMemoryState.objects.get_or_create(
            normalized_word=w,
            defaults={
                "word": w,
                "source_sentence": question.sentence,
                "memory_level": 0
            }
        )

        memory.word = w
        memory.source_sentence = question.sentence
        memory.review_count += 1
        memory.last_review = now

        if w in missed_words:
            memory.wrong_count += 1
            memory.memory_level = 1
            memory.is_due_boost = True
            memory.next_review = calculate_next_review(1, now=now)
        else:
            # 虽然整题错了，但这个词用户其实写出来了，给一点点正向推进
            if memory.memory_level <= 0:
                memory.memory_level = 1
            else:
                memory.memory_level = min(memory.memory_level + 1, 11)

            memory.is_due_boost = False
            memory.next_review = calculate_next_review(memory.memory_level, now=now)

        memory.save()
        updated_words.append(serialize_word_memory(memory))

    return {
        "expected_words": expected_words,
        "missed_words": missed_words,
        "hit_words": hit_words,
        "updated_words": updated_words
    }

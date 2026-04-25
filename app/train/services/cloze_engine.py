import random
import re


# =========================
# 简单分词（多语言通用 fallback）
# =========================
def simple_tokenize(text):
    if not text:
        return []

    # 英文：单词和标点分开
    if re.search(r"[A-Za-z]", text):
        return re.findall(r"[A-Za-z']+|[^\w\s]", text, flags=re.UNICODE)

    # 中文 / 日文 / 韩文 fallback：逐字
    return list(text)


# =========================
# 语言检测（简版）
# =========================
def detect_lang(text):
    if re.search(r"[a-zA-Z]", text):
        return "en"

    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"

    # 先判日文假名
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"

    # 再判中文汉字
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"

    return "unknown"

# =========================
# 是否允许成为克漏候选
# =========================
def is_candidate_token(token, lang):
    token = (token or "").strip()
    if not token:
        return False

    # 纯标点直接排除
    if re.fullmatch(r"[^\w\s]", token, flags=re.UNICODE):
        return False

    if lang == "en":
        low_value_words = {
            "a", "an", "the",
            "in", "on", "at", "to", "of", "for", "with",
            "and", "or", "but"
        }
        return token.lower() not in low_value_words

    if lang == "jp_cn":
        low_value_chars = {"的", "了", "着", "は", "が", "を", "に", "で"}
        return token not in low_value_chars

    if lang == "kr":
        low_value_chars = {"은", "는", "이", "가", "을", "를"}
        return token not in low_value_chars

    return True


# =========================
# 优先级规则
# =========================
LANG_RULES = {
    # =========================
    # 英文：动词 > 助动词 > 连接词 > 名词
    # =========================
    "en": {
        "verb": [
            r"\b(go|come|make|take|have|like|want|need|work|study|live|eat|drink|see|say|ask|tell|know|get|give|find|think|call|play|read|write)\b",
            r"\b\w+(ing|ed)\b"
        ],
        "aux": [
            r"\b(am|is|are|was|were|be|been|being)\b",
            r"\b(do|does|did|have|has|had)\b",
            r"\b(can|could|will|would|shall|should|may|might|must)\b"
        ],
        "connector": [
            r"\b(if|because|when|while|although|though|that|whether|before|after|since|unless)\b"
        ],
        "noun": [
            r"\b(job|work|wife|husband|school|book|home|house|teacher|student|friend|family|time|money|food|water)\b",
            r"\b[A-Za-z]{4,}\b"
        ],
        "low": [
            r"\b(a|an|the|in|on|at|to|of|for|with|by|from)\b",
            r"\b(and|or|but)\b"
        ]
    },

    # =========================
    # 日文：动词/活用 > 句型 > 名词 > 助词
    # =========================
    "ja": {
        "verb": [
            r"(する|した|します|して|できる|できない|行く|行きます|来る|来ます|見る|見ます|食べる|食べます|ある|いる|話す|話します|読む|読みます|書く|書きます)$",
            r"(ない|たい|ている|ていた|ました|ません|だった|でした)$"
        ],
        "pattern": [
            r"(なければならない|てもいい|ことがある|つもり|ように|ために|から|ので|のに)"
        ],
        "noun": [
            r"(学校|仕事|先生|学生|家族|友達|本|家|時間|お金)"
        ],
        "particle": [
            r"(は|が|を|に|で|へ|と|から|まで|より|の)"
        ]
    },

    # =========================
    # 中文：动词 > 关键词 > 补语 > 虚词
    # =========================
    "zh": {
        "verb": [
            r"(去|来|看|说|听|读|写|吃|喝|做|学|工作|喜欢|知道|觉得|告诉|问|买|卖|给|找|住|想)"
        ],
        "keyword": [
            r"(学校|工作|老师|学生|朋友|家人|时间|地方|问题|事情|书|家|公司)"
        ],
        "complement": [
            r"(上来|下去|起来|下来|完|到|见|懂|清楚|好)"
        ],
        "function": [
            r"(的|了|着|过|吗|呢|吧|啊|和|跟|在|对|把|被)"
        ]
    },

    # =========================
    # 韩文：谓语块 > 句尾 > 名词 > 조사
    # =========================
    "ko": {
        "predicate": [
            r"(하다|가다|오다|먹다|보다|좋아하다|공부하다|일하다|살다|읽다|쓰다)$",
            r"(합니다|해요|갔어요|먹어요|좋아해요|공부해요|일해요)$"
        ],
        "ending": [
            r"(다|요|니다|습니다|었어요|았어요|고 있다|고 싶다|아야 하다|어야 하다)$"
        ],
        "noun": [
            r"(학교|직장|선생님|학생|친구|가족|집|시간|돈|책)"
        ],
        "josa": [
            r"(은|는|이|가|을|를|에|에서|와|과|도|만)"
        ]
    }
}


# =========================
# 根据规则打分（按语法重要性）
# =========================
def score_token(token, lang):
    token = (token or "").strip()
    rules = LANG_RULES.get(lang, {})

    if lang == "en":
        for pattern in rules.get("verb", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return 90
        for pattern in rules.get("aux", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return 80
        for pattern in rules.get("connector", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return 70
        for pattern in rules.get("noun", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return 60
        for pattern in rules.get("low", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return 10
        return 40

    if lang == "ja":
        for pattern in rules.get("verb", []):
            if re.search(pattern, token):
                return 90
        for pattern in rules.get("pattern", []):
            if re.search(pattern, token):
                return 80
        for pattern in rules.get("noun", []):
            if re.search(pattern, token):
                return 60
        for pattern in rules.get("particle", []):
            if re.search(pattern, token):
                return 10
        return 40

    if lang == "zh":
        for pattern in rules.get("verb", []):
            if re.search(pattern, token):
                return 90
        for pattern in rules.get("keyword", []):
            if re.search(pattern, token):
                return 75
        for pattern in rules.get("complement", []):
            if re.search(pattern, token):
                return 60
        for pattern in rules.get("function", []):
            if re.search(pattern, token):
                return 10
        return 40

    if lang == "ko":
        for pattern in rules.get("predicate", []):
            if re.search(pattern, token):
                return 90
        for pattern in rules.get("ending", []):
            if re.search(pattern, token):
                return 80
        for pattern in rules.get("noun", []):
            if re.search(pattern, token):
                return 60
        for pattern in rules.get("josa", []):
            if re.search(pattern, token):
                return 10
        return 40

    return 40

# =========================
# 词类分类（用于难度联动）
# =========================
def classify_token(token, lang):
    token = (token or "").strip()
    rules = LANG_RULES.get(lang, {})

    if lang == "en":
        for pattern in rules.get("verb", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return "core"
        for pattern in rules.get("aux", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return "structure"
        for pattern in rules.get("connector", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return "structure"
        for pattern in rules.get("noun", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return "core"
        for pattern in rules.get("low", []):
            if re.search(pattern, token, flags=re.IGNORECASE):
                return "function"
        return "other"

    if lang == "ja":
        for pattern in rules.get("verb", []):
            if re.search(pattern, token):
                return "core"
        for pattern in rules.get("pattern", []):
            if re.search(pattern, token):
                return "structure"
        for pattern in rules.get("noun", []):
            if re.search(pattern, token):
                return "core"
        for pattern in rules.get("particle", []):
            if re.search(pattern, token):
                return "function"
        return "other"

    if lang == "zh":
        for pattern in rules.get("verb", []):
            if re.search(pattern, token):
                return "core"
        for pattern in rules.get("keyword", []):
            if re.search(pattern, token):
                return "core"
        for pattern in rules.get("complement", []):
            if re.search(pattern, token):
                return "structure"
        for pattern in rules.get("function", []):
            if re.search(pattern, token):
                return "function"
        return "other"

    if lang == "ko":
        for pattern in rules.get("predicate", []):
            if re.search(pattern, token):
                return "core"
        for pattern in rules.get("ending", []):
            if re.search(pattern, token):
                return "structure"
        for pattern in rules.get("noun", []):
            if re.search(pattern, token):
                return "core"
        for pattern in rules.get("josa", []):
            if re.search(pattern, token):
                return "function"
        return "other"

    return "other"

# =========================
# 难度规则：控制空格数和允许的词类
# =========================
def resolve_difficulty_rules(min_blank, max_blank):
    min_blank = int(min_blank or 1)
    max_blank = int(max_blank or min_blank)

    if max_blank < min_blank:
        max_blank = min_blank

    # 初级：优先挖 1 个核心词
    if max_blank <= 1:
        return {
            "level": "easy",
            "allowed_classes": {"core"},
            "blank_min": 1,
            "blank_max": 1,
        }

    # 中级：挖 1~2 个，加入结构词
    if max_blank <= 2:
        return {
            "level": "medium",
            "allowed_classes": {"core", "structure"},
            "blank_min": max(1, min_blank),
            "blank_max": min(2, max_blank),
        }

    # 高级：挖 2~3 个，加入虚词辨析
    return {
        "level": "hard",
        "allowed_classes": {"core", "structure", "function"},
        "blank_min": max(2, min_blank),
        "blank_max": min(3, max_blank),
    }

# =========================
# 位置权重：优先中部，尽量避开首尾
# =========================
def apply_position_preference(scored, total_tokens):
    adjusted = []

    for idx, token, score, token_class in scored:
        adjusted_score = score

        # 首尾位置：明显降权
        if total_tokens >= 3 and (idx == 0 or idx == total_tokens - 1):
            adjusted_score -= 25

        # 靠近首尾：轻度降权
        elif total_tokens >= 5 and (idx == 1 or idx == total_tokens - 2):
            adjusted_score -= 10

        adjusted.append((idx, token, adjusted_score, token_class))

    # 重新排序：先位置修正后的分数，再按原句顺序
    adjusted.sort(key=lambda x: (-x[2], x[0]))
    return adjusted

# =========================
# 选择候选：避免连续挖相邻词
# =========================
def select_non_adjacent_tokens(scored, blank_count):
    selected = []
    selected_indexes = set()

    # 第一轮：严格避免相邻
    for idx, token, score, token_class in scored:
        if (idx - 1) in selected_indexes or (idx + 1) in selected_indexes:
            continue

        selected.append((idx, token, score, token_class))
        selected_indexes.add(idx)

        if len(selected) >= blank_count:
            break

    # 第二轮：如果不够，再补
    if len(selected) < blank_count:
        for idx, token, score, token_class in scored:
            if idx in selected_indexes:
                continue

            selected.append((idx, token, score, token_class))
            selected_indexes.add(idx)

            if len(selected) >= blank_count:
                break

    return selected


# =========================
# 主函数：生成克漏题
# =========================
def generate_cloze(text, min_blank=1, max_blank=2, seed_key=None):
    text = re.sub(r"[\r\n]+", "", text or "")
    tokens = simple_tokenize(text)
    lang = detect_lang(text)

    if not tokens:
        return text, []

    difficulty_rules = resolve_difficulty_rules(min_blank, max_blank)
    allowed_classes = difficulty_rules["allowed_classes"]

    scored = []
    fallback_scored = []

    for i, token in enumerate(tokens):
        if not is_candidate_token(token, lang):
            continue

        token_class = classify_token(token, lang)
        score = score_token(token, lang)

        row = (i, token, score, token_class)
        fallback_scored.append(row)

        if token_class in allowed_classes:
            scored.append(row)

    # 如果按难度筛完一个都没有，就退回到全部候选
    if not scored:
        scored = fallback_scored

    if not scored:
        return text, []

    # 按语法重要性先排序
    scored.sort(key=lambda x: (-x[2], x[0]))

    # 再加位置偏好：优先中部，尽量避开首尾
    scored = apply_position_preference(scored, total_tokens=len(tokens))

    max_available = len(scored)

    # =========================
    # 固定随机源：同一题同一等级下结果一致
    # =========================
    rng = random
    if seed_key is not None:
        rng = random.Random(str(seed_key))

    blank_count = rng.randint(
        difficulty_rules["blank_min"],
        min(difficulty_rules["blank_max"], max_available)
    )

    selected = select_non_adjacent_tokens(scored, blank_count)
    selected_indexes = {i for i, _, _, _ in selected}

    answers = []
    new_tokens = []

    for i, token in enumerate(tokens):
        if i in selected_indexes:
            answers.append(token)
            new_tokens.append("____")
        else:
            new_tokens.append(token)

    if lang == "en":
        cloze_text = ""
        for i, token in enumerate(new_tokens):
            if i == 0:
                cloze_text += token
                continue

            if re.fullmatch(r"[^\w\s]", token, flags=re.UNICODE):
                cloze_text += token
            else:
                cloze_text += " " + token
    else:
        cloze_text = "".join(new_tokens)

    return cloze_text, answers
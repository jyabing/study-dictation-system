import random
import re


# =========================
# 语言检测
# =========================
def detect_language(text: str) -> str:

    if not text:
        return "unknown"

    # 韩文
    if re.search(r"[\uac00-\ud7a3]", text):
        return "ko"

    # 日文（平假名 / 片假名）
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"

    # 中文
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"

    # 默认英语
    return "en"


# =========================
# 英语分词
# 保留原始顺序，去掉纯标点
# =========================
def tokenize_english(text: str):

    if not text:
        return []

    return re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|[^\w\s]", text, flags=re.UNICODE)


# =========================
# 日语粗分词
# 这里不做 MeCab，只做可运行的轻量规则版
# 优先抓助词 / 常见功能词 / 连续文本块
# =========================
def tokenize_japanese(text: str):

    if not text:
        return []

    particles = [
        "では", "には", "へは", "とは", "から", "まで", "より",
        "には", "へと", "ので", "のに",
        "は", "が", "を", "に", "で", "と", "へ", "も", "の", "や", "ね", "よ", "か"
    ]

    tokens = []
    i = 0
    n = len(text)

    while i < n:
        matched = None

        for p in sorted(particles, key=len, reverse=True):
            if text[i:i + len(p)] == p:
                matched = p
                break

        if matched:
            tokens.append(matched)
            i += len(matched)
            continue

        ch = text[i]

        # 标点单独成 token
        if re.match(r"[。、「」！？，、】【（）\s]", ch):
            tokens.append(ch)
            i += 1
            continue

        # 连续非助词 / 非标点的文本块
        j = i
        while j < n:
            stop = False

            for p in particles:
                if text[j:j + len(p)] == p:
                    stop = True
                    break

            if stop:
                break

            if re.match(r"[。、「」！？，、】【（）\s]", text[j]):
                break

            j += 1

        tokens.append(text[i:j])
        i = j

    return [t for t in tokens if t != ""]


# =========================
# 中文粗分词
# 不引入 jieba，先做轻量规则版
# 常见虚词优先拆开，其余按连续块
# =========================
def tokenize_chinese(text: str):

    if not text:
        return []

    function_words = [
        "为了", "因为", "所以", "如果", "但是", "然后",
        "在", "对", "给", "跟", "向", "从", "比", "把", "被", "让", "和", "与", "或"
    ]

    tokens = []
    i = 0
    n = len(text)

    while i < n:
        matched = None

        for w in sorted(function_words, key=len, reverse=True):
            if text[i:i + len(w)] == w:
                matched = w
                break

        if matched:
            tokens.append(matched)
            i += len(matched)
            continue

        ch = text[i]

        if re.match(r"[。，“”‘’！？；：、，（）\s]", ch):
            tokens.append(ch)
            i += 1
            continue

        tokens.append(ch)
        i += 1

    return [t for t in tokens if t != ""]


# =========================
# 韩语粗分词
# 按空格切，再对常见助词做尾部识别
# =========================
def tokenize_korean(text: str):

    if not text:
        return []

    tokens = []
    for part in text.split():
        tokens.append(part)

    return tokens


# =========================
# 通用分词入口
# =========================
def tokenize_text(text: str, lang: str):

    if lang == "en":
        return tokenize_english(text)

    if lang == "ja":
        return tokenize_japanese(text)

    if lang == "zh":
        return tokenize_chinese(text)

    if lang == "ko":
        return tokenize_korean(text)

    return text.split()


# =========================
# 是否是标点
# =========================
def is_punctuation(token: str) -> bool:

    if not token:
        return True

    return bool(re.fullmatch(r"[^\w\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7a3]+", token))


# =========================
# 英语词类优先级
# =========================
EN_PRIORITY_1 = {
    "in", "on", "at", "to", "for", "with", "from", "of", "by", "about", "into", "over", "after",
    "where", "when", "why", "how", "what", "who", "which"
}

EN_PRIORITY_2 = {
    "is", "are", "am", "was", "were",
    "do", "does", "did", "have", "has", "had",
    "go", "goes", "went", "come", "comes", "came",
    "live", "lives", "work", "works", "study", "studies",
    "make", "makes", "take", "takes", "want", "wants",
    "like", "likes", "know", "knows"
}

EN_PRIORITY_3_SUFFIX = (
    "ous", "ful", "able", "ible", "al", "ive", "less", "ish",
    "ly", "y"
)


# =========================
# 日语优先级
# 助词 > 动词/形容词特征 > 其他
# =========================
JA_PARTICLES = {
    "は", "が", "を", "に", "で", "と", "へ", "も", "の", "や", "か", "ね", "よ",
    "から", "まで", "より", "ので", "のに", "では", "には"
}


# =========================
# 中文优先级
# =========================
ZH_PRIORITY_1 = {
    "在", "对", "给", "跟", "向", "从", "比", "把", "被", "和", "与", "或", "为了", "因为", "所以", "如果", "但是"
}

ZH_PRIORITY_2 = {
    "是", "有", "去", "来", "看", "说", "做", "学", "住", "工作", "喜欢", "知道", "想", "要", "会", "能"
}


# =========================
# 韩语优先级
# =========================
KO_PARTICLE_SUFFIXES = (
    "은", "는", "이", "가", "을", "를", "에", "에서", "에게", "와", "과", "도", "로", "으로"
)

KO_VERB_SUFFIXES = (
    "하다", "합니다", "했다", "해요", "해", "이다", "입니다", "있다", "없다", "간다", "온다"
)


# =========================
# 判断英语 token 优先级
# =========================
def get_en_priority(token: str) -> int:

    t = token.lower().strip(".,!?;:'\"()[]{}")

    if not t:
        return 999

    if t in EN_PRIORITY_1:
        return 1

    if t in EN_PRIORITY_2:
        return 2

    if t.endswith(EN_PRIORITY_3_SUFFIX):
        return 3

    return 9


# =========================
# 判断日语 token 优先级
# =========================
def get_ja_priority(token: str) -> int:

    t = token.strip()

    if not t or is_punctuation(t):
        return 999

    if t in JA_PARTICLES:
        return 1

    # 轻量动词判断
    if t.endswith(("する", "します", "した", "して", "いる", "います", "れる", "られる", "ない", "ます", "た", "て")):
        return 2

    # 轻量形容词判断
    if t.endswith(("い", "な")):
        return 3

    return 9


# =========================
# 判断中文 token 优先级
# =========================
def get_zh_priority(token: str) -> int:

    t = token.strip()

    if not t or is_punctuation(t):
        return 999

    if t in ZH_PRIORITY_1:
        return 1

    if t in ZH_PRIORITY_2:
        return 2

    if len(t) >= 2:
        return 3

    return 9


# =========================
# 判断韩语 token 优先级
# =========================
def get_ko_priority(token: str) -> int:

    t = token.strip()

    if not t or is_punctuation(t):
        return 999

    if t.endswith(KO_PARTICLE_SUFFIXES):
        return 1

    if t.endswith(KO_VERB_SUFFIXES):
        return 2

    return 9


# =========================
# 统一优先级入口
# =========================
def get_token_priority(token: str, lang: str) -> int:

    if lang == "en":
        return get_en_priority(token)

    if lang == "ja":
        return get_ja_priority(token)

    if lang == "zh":
        return get_zh_priority(token)

    if lang == "ko":
        return get_ko_priority(token)

    return 9


# =========================
# 是否适合挖空
# =========================
def is_blankable(token: str, lang: str) -> bool:

    t = token.strip()

    if not t:
        return False

    if is_punctuation(t):
        return False

    # 英语过滤冠词 / 代词等低价值词
    if lang == "en":
        low_value = {
            "a", "an", "the",
            "i", "you", "he", "she", "it", "we", "they",
            "me", "him", "her", "us", "them",
            "my", "your", "his", "their", "our"
        }
        if t.lower() in low_value:
            return False

    return True


# =========================
# 选出要挖空的 token 下标
# =========================
def pick_blank_index(tokens, lang: str):

    candidates = []

    for i, token in enumerate(tokens):
        if not is_blankable(token, lang):
            continue

        candidates.append({
            "index": i,
            "token": token,
            "priority": get_token_priority(token, lang)
        })

    if not candidates:
        return None

    # 找最优先级
    best_priority = min(item["priority"] for item in candidates)
    best = [item for item in candidates if item["priority"] == best_priority]

    return random.choice(best)["index"]


# =========================
# 重新拼接文本
# =========================
def join_tokens(tokens, lang: str):

    if lang == "en":
        text = " ".join(tokens)
        text = re.sub(r"\s+([.,!?;:])", r"\1", text)
        return text

    # 中日韩直接拼接
    return "".join(tokens)


# =========================
# 自动挖空主函数
# 返回: (question, answer)
# =========================
def generate_cloze(text: str):

    if not text:
        return None

    lang = detect_language(text)
    tokens = tokenize_text(text, lang)

    if len(tokens) < 2:
        return None

    idx = pick_blank_index(tokens, lang)

    if idx is None:
        return None

    answer = tokens[idx]
    tokens[idx] = "_____"
    question = join_tokens(tokens, lang)

    return question, answer


# =========================
# 生成 choice 题干
# 本质就是 cloze stem
# =========================
def generate_choice_stem(text: str):

    result = generate_cloze(text)

    if not result:
        return None

    question, answer = result
    return question, answer
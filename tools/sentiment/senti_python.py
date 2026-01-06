import math
import os
import re
import time

import jieba

import config


def not_empty(value):
    return value and value.strip()


def open_dict(filename, base_dir):
    path = os.path.join(base_dir, filename)
    try:
        with open(path, "r", encoding="utf-8") as dictionary:
            return [word.strip("\n") for word in dictionary if word.strip("\n")]
    except FileNotFoundError:
        return []


def judgeodd(num):
    return "odd" if (num % 2) else "even"


def slice_between(words, start, end):
    if start in words and end in words:
        return words[words.index(start) + 1 : words.index(end)]
    return []


SENTI_DIR_PATH = os.getenv("SENTI_DIR_PATH", getattr(config, "SENTI_DIR_PATH", ""))
if not SENTI_DIR_PATH:
    SENTI_DIR_PATH = os.path.join(os.path.dirname(__file__), "data")
elif not os.path.isabs(SENTI_DIR_PATH):
    SENTI_DIR_PATH = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", SENTI_DIR_PATH)
    )

_senti_use_redis = os.getenv("SENTI_USE_REDIS")
if _senti_use_redis is None:
    SENTI_USE_REDIS = bool(getattr(config, "SENTI_USE_REDIS", True))
else:
    SENTI_USE_REDIS = _senti_use_redis not in ("0", "false", "False")
SENTI_REDIS_PREFIX = os.getenv(
    "SENTI_REDIS_PREFIX", getattr(config, "SENTI_REDIS_PREFIX", "weibo:senti:")
)
SENTI_CACHE_TTL = int(os.getenv("SENTI_CACHE_TTL", str(getattr(config, "SENTI_CACHE_TTL", 60))))

_LEXICONS = None
_LEXICONS_TS = 0


def load_lexicons_from_files():
    return {
        "stopwords": open_dict("stopwords.txt", SENTI_DIR_PATH),
        "positive": open_dict("positive.txt", SENTI_DIR_PATH),
        "negative": open_dict("negative.txt", SENTI_DIR_PATH),
        "negation": open_dict("negation.txt", SENTI_DIR_PATH),
        "degree": open_dict("degree_words.txt", SENTI_DIR_PATH),
    }


def load_lexicons_from_redis():
    try:
        import redis
    except Exception:
        return None

    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    password = os.getenv("REDIS_PASSWORD") or None

    client = redis.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        decode_responses=True,
    )
    try:
        client.ping()
    except Exception:
        return None

    types = ["positive", "negative", "negation", "degree", "stopwords"]
    data = {}
    for word_type in types:
        data[word_type] = list(client.smembers(f"{SENTI_REDIS_PREFIX}{word_type}"))
    return data


def get_lexicons():
    global _LEXICONS, _LEXICONS_TS
    now = time.time()
    if _LEXICONS and (now - _LEXICONS_TS) < SENTI_CACHE_TTL:
        return _LEXICONS

    lexicons = None
    if SENTI_USE_REDIS:
        lexicons = load_lexicons_from_redis()
    if not lexicons:
        lexicons = load_lexicons_from_files()

    _LEXICONS = lexicons
    _LEXICONS_TS = now
    return lexicons


def tokenize(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "ignore")
    text = strs_filter(text)
    return jieba.lcut(text, cut_all=False)


def sentiment_score_list(seg_sentence):
    lexicons = get_lexicons()
    stopwords = lexicons["stopwords"]
    posdict = lexicons["positive"]
    negdict = lexicons["negative"]
    deny_word = lexicons["negation"]
    degree_word = lexicons["degree"]

    mostdict = slice_between(degree_word, "extreme", "very")
    verydict = slice_between(degree_word, "very", "more")
    moredict = slice_between(degree_word, "more", "ish")
    ishdict = slice_between(degree_word, "ish", "last")

    if not mostdict:
        mostdict = slice_between(degree_word, "极其", "很")
    if not verydict:
        verydict = slice_between(degree_word, "很", "较")
    if not moredict:
        moredict = slice_between(degree_word, "较", "稍")
    if not ishdict:
        ishdict = slice_between(degree_word, "稍", "完")
    words = []
    count1 = []
    count2 = []
    senti_score_words_result = {"count2": count2, "words": words}
    for sen in seg_sentence:
        if not sen:
            continue
        segtmp = jieba.lcut(sen, cut_all=False)
        words.extend(segtmp)
        i = 0
        a = 0
        poscount = 0
        poscount2 = 0
        poscount3 = 0
        negcount = 0
        negcount2 = 0
        negcount3 = 0
        for word in segtmp:
            if word in posdict:
                poscount += 1
                c = 0
                for w in segtmp[a:i]:
                    if w in mostdict:
                        poscount *= 4.0
                    elif w in verydict:
                        poscount *= 3.0
                    elif w in moredict:
                        poscount *= 2.0
                    elif w in ishdict:
                        poscount *= 0.5
                    elif w in deny_word:
                        c += 1
                if judgeodd(c) == "odd":
                    poscount *= -1.0
                    poscount2 += poscount
                    poscount = 0
                    poscount3 = poscount + poscount2 + poscount3
                    poscount2 = 0
                else:
                    poscount3 = poscount + poscount2 + poscount3
                    poscount = 0
                a = i + 1

            elif word in negdict:
                negcount += 1
                d = 0
                for w in segtmp[a:i]:
                    if w in mostdict:
                        negcount *= 4.0
                    elif w in verydict:
                        negcount *= 3.0
                    elif w in moredict:
                        negcount *= 2.0
                    elif w in ishdict:
                        negcount *= 0.5
                    elif w in degree_word:
                        d += 1
                if judgeodd(d) == "odd":
                    negcount *= -1.0
                    negcount2 += negcount
                    negcount = 0
                    negcount3 = negcount + negcount2 + negcount3
                    negcount2 = 0
                else:
                    negcount3 = negcount + negcount2 + negcount3
                    negcount = 0
                a = i + 1
            elif word in ("！", "!"):
                for w2 in segtmp[::-1]:
                    if w2 in posdict or w2 in negdict:
                        poscount3 += 2
                        negcount3 += 2
                        break
            i += 1

            pos_count = 0
            neg_count = 0
            if poscount3 < 0 and negcount3 > 0:
                neg_count += negcount3 - poscount3
                pos_count = 0
            elif negcount3 < 0 and poscount3 > 0:
                pos_count = poscount3 - negcount3
                neg_count = 0
            elif poscount3 < 0 and negcount3 < 0:
                neg_count = -poscount3
                pos_count = -negcount3
            else:
                pos_count = poscount3
                neg_count = negcount3

            count1.append([pos_count, neg_count])
        count2.append(count1)
        count1 = []

    return senti_score_words_result


def _mean(values):
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values):
    if not values:
        return 0.0
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def sentiment_score(senti_score_list_value):
    score = []
    for review in senti_score_list_value:
        if not review:
            score.append([0, 0, 0.0, 0.0, 0.0, 0.0])
            continue
        pos_values = [item[0] for item in review]
        neg_values = [item[1] for item in review]
        pos = sum(pos_values)
        neg = sum(neg_values)
        avg_pos = float("%.1f" % _mean(pos_values))
        avg_neg = float("%.1f" % _mean(neg_values))
        std_pos = float("%.1f" % _std(pos_values))
        std_neg = float("%.1f" % _std(neg_values))
        score.append([pos, neg, avg_pos, avg_neg, std_pos, std_neg])
    return score


def strs_filter(text_str):
    re_html = re.compile(r"<[^>]+>")
    return re_html.sub("", text_str)


def senti_content(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8", "ignore")
    text = strs_filter(text)
    tests = re.split(r"。|！|？|\n", text)
    tests_f = list(filter(not_empty, tests))
    senti_score_words_result = sentiment_score_list(tests_f)
    score_list = sentiment_score(senti_score_words_result["count2"])
    stats = {"pos": 0, "neg": 0, "midd": 0}
    analyzer_result = {"senti_result": 0}
    for score_item in score_list:
        result = score_item[4] - score_item[5]
        if result > 0:
            stats["pos"] += 1
        elif result < 0:
            stats["neg"] += 1
        else:
            stats["midd"] += 1
    if stats["pos"] > stats["neg"]:
        analyzer_result["senti_result"] = 1
    elif stats["pos"] < stats["neg"]:
        analyzer_result["senti_result"] = -1
    else:
        analyzer_result["senti_result"] = 0
    return analyzer_result

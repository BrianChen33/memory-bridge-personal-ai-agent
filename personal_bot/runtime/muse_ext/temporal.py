"""Small explicit Chinese calendar resolver; ambiguity is returned, not guessed."""
import re
from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))
WEEKDAYS = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
NUMBERS = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
           '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
N = r'[0-9零〇一二两三四五六七八九十百]+'


def _now(value=None):
    value = value or datetime.now(tz=BJ)
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=BJ)
    if value.tzinfo is None:
        raise ValueError('reference_timezone_required')
    return value.astimezone(BJ)


def _number(text):
    if text.isdigit():
        return int(text)
    if '百' in text:
        a, b = text.split('百', 1)
        return _number(a or '一')*100 + (_number(b.lstrip('零')) if b.lstrip('零') else 0)
    if '十' in text:
        a, b = text.split('十', 1)
        return (_number(a) if a else 1)*10 + (_number(b) if b else 0)
    if len(text) == 1 and text in NUMBERS:
        return NUMBERS[text]
    if text and all(c in NUMBERS for c in text):
        return int(''.join(str(NUMBERS[c]) for c in text))
    raise ValueError('invalid_number')


def _anchor(text, now, future=False):
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    explicit = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})|(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]', text)
    if explicit:
        if explicit.group(1):
            y, m, d = map(int, explicit.group(1, 2, 3))
        else:
            y, m, d = int(explicit.group(4) or now.year), int(explicit.group(5)), int(explicit.group(6))
        start = datetime(y, m, d, tzinfo=BJ)
        return start, start+timedelta(days=1), explicit.group(), [explicit.span()]
    month = re.search(r'上个月|上月|这个月|本月', text)
    if month:
        end = day.replace(day=1)
        if month.group() in ('上个月', '上月'):
            start = (end-timedelta(days=1)).replace(day=1)
        else:
            start = end
            end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
        return start, end, month.group(), [month.span()]
    week = re.search(r'(上|下|这|本)(?:周|星期|礼拜)([一二三四五六日天])?|(?:周|星期|礼拜)([一二三四五六日天])', text)
    if week:
        shift = {'上': -7, '下': 7}.get(week.group(1), 0)
        monday = day-timedelta(days=day.weekday())+timedelta(days=shift)
        weekday = week.group(2) or week.group(3)
        if weekday:
            start = monday+timedelta(days=WEEKDAYS[weekday])
            if future and week.group(1) is None and start < day:
                start += timedelta(days=7)
            end = start+timedelta(days=1)
        else:
            start, end = monday, monday+timedelta(days=7)
        return start, end, week.group(), [week.span()]
    relative = re.search(r'大前天|前天|昨天|昨日|今天|今日|明天|明日|后天|今早|今晚|昨晚', text)
    if relative:
        shift = {'大前天': -3, '前天': -2, '昨天': -1, '昨日': -1,
                 '昨晚': -1, '明天': 1, '明日': 1, '后天': 2}.get(relative.group(), 0)
        start = day+timedelta(days=shift)
        return start, start+timedelta(days=1), relative.group(), [relative.span()]
    return day, day+timedelta(days=1), None, []


def _period(text):
    found = re.search(r'凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|晚间|夜里|今早|今晚|昨晚', text)
    if not found:
        return None
    span = {'凌晨': (0, 5), '清晨': (5, 8), '早上': (5, 12), '上午': (5, 12),
            '今早': (5, 12), '中午': (11, 14), '下午': (12, 18),
            '傍晚': (17, 20)}.get(found.group(), (18, 24))
    return found, span


def _remaining(text, spans):
    chars = list(text)
    for a, b in spans:
        chars[a:b] = [' ']*(b-a)
    result = ''.join(chars)
    result = re.sub(r'(?:我|你|我们)?(?:跟你|和你)?(?:说|聊|谈)(?:过|了|的)?', ' ', result)
    for phrase in ('发生了什么', '发生什么', '还记得吗', '帮我查一下', '帮我查查',
                   '有哪些事情', '什么内容', '哪些内容', '了些什么', '什么', '哪些', '啥'):
        result = result.replace(phrase, ' ')
    return re.sub(r'\s+', ' ', result).strip(' 的，。！？?,.!:：吗呢一下')


def resolve_query(text, reference=None):
    now = _now(reference)
    if not isinstance(text, str):
        raise ValueError('invalid_time_query')
    recent = re.search(r'(?:过去|最近)('+N+r')(天|小时)|刚才|刚刚', text)
    if recent:
        seconds = 7200 if recent.group() in ('刚才', '刚刚') else _number(recent.group(1))*(86400 if recent.group(2) == '天' else 3600)
        return {'start': (now-timedelta(seconds=seconds)).timestamp(), 'end': now.timestamp()+.000001,
                'query': _remaining(text, [recent.span()]), 'label': recent.group()}
    start, end, label, spans = _anchor(text, now)
    period = _period(text)
    if not label and not period:
        return None
    if period:
        found, (a, b) = period
        start = start+timedelta(hours=a)
        end = start.replace(hour=0)+timedelta(hours=b)
        spans.append(found.span())
        label = (label or '')+found.group()
    actor = None
    if re.search(r'我(?:跟你|和你)?.*?(?:说|聊|讲)', text):
        actor = 'user'
    elif re.search(r'你.*?(?:说|回复|讲)', text):
        actor = 'assistant'
    return {'start': start.timestamp(), 'end': end.timestamp(), 'query': _remaining(text, spans),
            'label': label, 'actor': actor, 'timezone': 'Asia/Shanghai'}


def parse_due(text, reference=None):
    now = _now(reference)
    if not isinstance(text, str) or not text.strip():
        return {'ok': False, 'needs_clarification': True, 'reason': 'missing_time'}
    if re.search(r'纽约|伦敦|东京|美国时间|英国时间|日本时间|美东|美西', text):
        return {'ok': False, 'needs_clarification': True, 'reason': 'timezone_needs_clarification'}
    try:
        relative = re.search('('+N+r')(分钟|小时|天|秒)(?:之)?后', text)
        if relative:
            count = _number(relative.group(1))
            if count <= 0:
                raise ValueError('invalid_duration')
            unit = {'分钟': 60, '小时': 3600, '天': 86400, '秒': 1}[relative.group(2)]
            due = now+timedelta(seconds=count*unit)
        else:
            day, _, _, _ = _anchor(text, now, future=True)
            colon = re.search(r'(?<!\d)(\d{1,2})[:：](\d{2})(?::(\d{2}))?', text)
            chinese = re.search('('+N+r')(?:点|时)(?:(半|一刻|三刻)|('+N+r')分?)?', text)
            match = colon or chinese
            if not match:
                return {'ok': False, 'needs_clarification': True, 'reason': 'missing_clock'}
            h = int(match.group(1)) if colon else _number(match.group(1))
            if colon:
                minute, second = int(match.group(2)), int(match.group(3) or 0)
            else:
                minute = {'半': 30, '一刻': 15, '三刻': 45}.get(match.group(2), _number(match.group(3)) if match.group(3) else 0)
                second = 0
            period = _period(text)
            p = period[0].group() if period else None
            if p == '凌晨':
                if h == 12:
                    h = 0
                elif h > 6:
                    return {'ok': False, 'needs_clarification': True, 'reason': 'contradictory_clock'}
            if not colon and p is None and h <= 12:
                return {'ok': False, 'needs_clarification': True, 'reason': 'ambiguous_am_pm'}
            if p in ('下午', '傍晚', '晚上', '晚间', '夜里', '今晚', '昨晚'):
                if h < 12:
                    h += 12
                elif h == 12 and p in ('晚上', '晚间', '夜里', '今晚', '昨晚'):
                    h = 24
            elif p == '中午':
                if h < 11:
                    h += 12
            elif p and h > 12:
                return {'ok': False, 'needs_clarification': True, 'reason': 'contradictory_clock'}
            if not (0 <= h <= 24 and 0 <= minute < 60 and 0 <= second < 60) or (h == 24 and (minute or second)):
                raise ValueError('invalid_clock')
            due = day+timedelta(hours=h, minutes=minute, seconds=second)
        if due <= now:
            return {'ok': False, 'needs_clarification': True, 'reason': 'time_in_past'}
        return {'ok': True, 'due_at': due.timestamp(), 'timezone': 'Asia/Shanghai',
                'display': due.strftime('%Y-%m-%d %H:%M:%S')+' 北京时间'}
    except (ValueError, OverflowError):
        return {'ok': False, 'needs_clarification': True, 'reason': 'invalid_date_or_time'}

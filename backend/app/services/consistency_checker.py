"""Novel_Agent — 一致性检查器

增强版：
1. 规则层：2/3字名称检测 + 更精确的假阳性过滤
2. 跨章节追踪：人物出现/消失检测
3. 事件一致性：关键事件（死亡、觉醒等）跨章节追踪
"""

import re
from typing import Optional

# ── 常见中文姓氏（覆盖绝大多数单姓） ──
_COMMON_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张"
    "孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎"
    "鲁韦昌马苗凤花方俞任袁柳丰鲍史唐费廉岑薛雷贺倪汤"
    "滕殷罗毕郝邬安常乐于时傅皮下齐康伍余元卜顾孟平黄"
    "穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊"
    "纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅"
    "盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经"
    "房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚程"
    "嵇邢滑裴陆荣翁荀羊惠甄曲家封芮羿储靳汲邴糜松井"
    "段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁"
    "仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄"
    "印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿"
    "通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼"
    "容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄"
    "阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那"
    "简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)

# ── 名称中不可能作为第二字的字符 ──
_NON_NAME_SECOND = set(
    "了说问答喊叫笑骂哭怒喝道在是把被让给"
    "看听感想知觉上下来去过进出回走跑跳站坐躺"
    "的地得着过吧吗呢啊呀哦嗯哼是不是便会能以将正"
    "可要会能不能该推开封信万千百个位只次种条块"
    "天年日月分秒时刻周"
    "都还已经很也很更就才又再便却刚总正一直直也"
)

# ── 需排除的常见双字词（扩展版） ──
_EXCLUDE = {
    "时候","地方","东西","事情","问题","办法","样子","声音","表情",
    "眼神","心中","脸上","头上","身上","手上","脚下","面前","眼前",
    "背后","身后","周围","旁边","楼下","楼上","门外","窗外","路边",
    "床上","地上","墙上","路上","街上","怀里","手中","沉默","点头",
    "摇头","抬头","低头","转身","停下","站住","坐下","站起","回头",
    "终于","突然","忽然","然后","所以","因为","这个","那个","大家",
    "众人","对方","一起","那时","此刻","半天","良久","最后","后来",
    "以前","早晨","中午","傍晚","晚上","深夜","今天","明天","昨天",
    "那天","清晨","阳光","月光","天空","大地","远处","近处","身边",
    "目光","视线","神情","语气","心里","脑海","意识","觉得","多年",
    "几天","老人","姑娘","少年","青年","孩子","小孩","先生","女士",
    "小姐","父亲","母亲","妻子","丈夫","不是","就是","只是","可是",
    "还是","怎么","什么","这些","哪里","朋友","同学","同事","兄弟",
    "姐妹","因为","虽然","但是","然而","不过","看见","听到","感觉",
    "知道","发现","认为","起来","出来","回来","过来","下去","上去",
    "一点","一些","很多","很少","所有","全部","彼此","之间","之中",
    "名字","眼睛","鼻子","嘴巴","耳朵","头发","意识","醒来","睁眼",
    "闭眼","脚步","步伐","动作","神态","姿态","边走","边想","说道",
    "想到","开口","动手","抬脚","转身","摇头","点头","低头","抬头",
    "后面","前面","上面","下面","里面","外面","左面","右面","侧面",
    "后边","前边","上边","下边","里边","外边","左边","右边","旁边",
    "当时","此刻","这时","那时","刚才","之前","之后","随后","跟着",
    "接着","瞬间","片刻","良久","久久","很快","缓慢","渐渐","逐步",
    "慢慢","已经","曾经","从未","从未","没有","也许","大概","反正",
    "难道","究竟","到底","是否","能否","可否","不如","无论","不管",
    "只要","除非","如果","要是","假如","假使","纵使","即使","哪怕",
    "虽然","虽说","固然","尽管","虽然","但是","可是","然而","不过",
    "却","则","于是","因此","因而","以致","既然","就算","纵然",
    "所谓","所谓","所谓","那样","这样","这种","那种","各类","各种",
    "有关","相关","无关","关于","对于","于","在","从","被","把",
    "将","以","由","由于","为","为了","因为","按照","通过","根据",
    "与","和","跟","同","及","以及","以及","除了","除非", 
    "只见","只见","就听","就听","只听","但见","但见","忽听","忽见",
    "那封","几名",
}

# ── 关键事件关键词（用于跨章节追踪） ──
_KEY_EVENT_VERBS = {
    "死": "死亡",
    "杀": "死亡/谋杀",
    "亡": "死亡",
    "陨": "死亡",
    "牺牲": "死亡",
    "去世": "死亡",
    "觉醒": "觉醒",
    "突破": "突破/进阶",
    "成": "进阶/变化",
    "背叛": "背叛",
    "加入": "加入",
    "离开": "离开",
    "发现": "发现",
    "失去": "失去",
    "获": "获得",
    "得到": "获得",
    "掌握": "获得",
    "成为": "身份变化",
}


async def check_consistency(
    content: str,
    known_characters: list[str],
    chapter_number: int,
    previous_characters_seen: Optional[dict] = None,
) -> tuple[list[dict], set[str], dict]:
    """增强版一致性检查。

    返回 (alerts, characters_this_chapter, character_events)
    
    Args:
        content: 本章正文
        known_characters: 设定中定义的主要人物
        chapter_number: 当前章节号
        previous_characters_seen: 前面各章出现过的人物 {name: set_of_chapters}
    """
    if not known_characters:
        return [], set(), {}

    known_set_lower = {c.strip().lower() for c in known_characters}
    if previous_characters_seen is None:
        previous_characters_seen = {}

    alerts = []
    seen_names = set()
    character_events = {}

    def is_known(name: str) -> bool:
        nl = name.lower().strip()
        if nl in known_set_lower:
            return True
        for kn in known_set_lower:
            if kn in nl or nl in kn:
                return True
        return False

    # ── 1. 规则层：提取 2-3 字中文名称候选 ──
    candidates_2 = set()
    candidates_3 = set()
    i = 0
    n = len(content)
    while i < n:
        c = content[i]
        if '\u4e00' <= c <= '\u9fff':
            start = i
            while i < n and '\u4e00' <= content[i] <= '\u9fff':
                i += 1
            seq = content[start:i]
            for j in range(len(seq) - 1):
                candidates_2.add(seq[j:j+2])
            for j in range(len(seq) - 2):
                candidates_3.add(seq[j:j+3])
        else:
            i += 1

    def is_plausible_name(word: str) -> bool:
        if len(word) < 2 or word in _EXCLUDE:
            return False
        # 首字必须是姓氏
        if word[0] not in _COMMON_SURNAMES:
            return False
        # 第二字不能是动词/助词
        if len(word) >= 2 and word[1] in _NON_NAME_SECOND:
            return False
        # 三字名：首姓 + 二三字合理
        if len(word) == 3:
            if word[1] in _NON_NAME_SECOND or word[2] in _NON_NAME_SECOND:
                return False
        return True

    # 先检查 3 字名（更准确），再补 2 字名
    for word in sorted(candidates_3):
        if not is_plausible_name(word):
            continue
        if is_known(word):
            seen_names.add(word)
        elif word not in seen_names:
            seen_names.add(word)
            alerts.append({
                "chapter_number": chapter_number,
                "conflict_name": word,
                "type": "unknown_character",
                "detail": f"检测到设定中未定义的人物名称「{word}」",
            })

    for word in sorted(candidates_2):
        if word in seen_names or word not in candidates_2:
            continue
        if not is_plausible_name(word):
            continue
        if is_known(word):
            seen_names.add(word)
        elif word not in seen_names:
            seen_names.add(word)
            alerts.append({
                "chapter_number": chapter_number,
                "conflict_name": word,
                "type": "unknown_character",
                "detail": f"检测到设定中未定义的人物名称「{word}」",
            })

    # ── 2. 跨章节追踪：检测人物"死而复生"等矛盾 ──
    for name in seen_names:
        if name in previous_characters_seen:
            prev_chapters = previous_characters_seen[name]
            # 检查是否在相隔多章后重新出现（可能有人物复用）
            if max(prev_chapters) < chapter_number - 3:
                alerts.append({
                    "chapter_number": chapter_number,
                    "conflict_name": name,
                    "type": "character_hiatus",
                    "detail": f"人物「{name}」在相隔 {chapter_number - max(prev_chapters)} 章后再次出现，确认是否合理",
                })

    # ── 3. 检测关键事件（用于后续跨章节追踪） ──
    for verb, event_type in _KEY_EVENT_VERBS.items():
        for name in seen_names:
            pattern = name + verb
            if pattern in content:
                char_events = character_events.setdefault(name, [])
                char_events.append({"chapter": chapter_number, "event": event_type, "detail": pattern})

    # ── 4. 跨章节事件一致性检测 ──
    if previous_characters_seen and "cross_chapter_events" in previous_characters_seen:
        prev_events = previous_characters_seen.get("cross_chapter_events", {})
        for name, current_events in character_events.items():
            if name in prev_events:
                for prev_event in prev_events[name]:
                    if prev_event["event"] == "死亡":
                        for cur_event in current_events:
                            if cur_event["event"] not in ("回忆", "梦境"):
                                alerts.append({
                                    "chapter_number": chapter_number,
                                    "conflict_name": name,
                                    "type": "resurrection",
                                    "detail": f"人物「{name}」在第 {prev_event['chapter']} 章已死亡/牺牲，但在本章再次出现",
                                })

    # 更新 seen 字典用于下次调用
    for name in seen_names:
        previous_characters_seen.setdefault(name, set()).add(chapter_number)
    previous_characters_seen["cross_chapter_events"] = character_events

    return alerts, seen_names, previous_characters_seen
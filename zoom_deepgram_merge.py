# -*- coding: utf-8 -*-
"""
Склейка транскрипта планёрки: точный русский текст Deepgram + имена спикеров из Zoom.

Zoom AI Companion даёт имена спикеров и таймкоды, но слабо распознаёт русский.
Deepgram (nova-3/multi + диаризация) распознаёт русский кратно точнее, но спикеры
безымянные («Спикер 1/2/3»). Этот скрипт берёт лучшее от обоих: гоняет аудио через
Deepgram, а имена проставляет из Zoom-транскрипта по совпадению во времени (с
авто-подбором сдвига: запись стартует не в t0 встречи, и разбег бывает большой).

Использование:
  python zoom_deepgram_merge.py --audio "<аудио.mp3>" --zoom "<Zoom.json>" --out "<Транскрипт.md>"

  --audio  аудиофайл встречи (mp3/m4a/wav/ogg/flac/amr). Видео не принимается.
  --zoom   Zoom-транскрипт. Два формата, распознаются по расширению:
           .json — полный ответ get_meeting_assets либо список items [{text,start,end}];
           .txt/.vtt — файл, который Zoom кладёт рядом с записью (блоки
           «HH:MM:SS --> HH:MM:SS» + строка «Имя: реплика»).
           Необязателен — без него имена не проставляются (будет «Спикер N»).
  --out    куда писать Транскрипт.md. По умолчанию — рядом с аудио.
  --model  модель Deepgram (по умолчанию nova-3).
  --lang   язык (по умолчанию multi — ловит английские слова в русской речи).
  --force  перезаписать, даже если --out уже существует (иначе пропуск — инвариант «не платим дважды»).
  --dg-json  файл сырого ответа Deepgram (по умолчанию «Deepgram raw.json» рядом с --out).
           Есть файл — берём его и не платим; нет — сохраняем туда после запроса.
           Пересобрать имена/разбивку после этого можно бесплатно.
  --max-offset  предел поиска сдвига Zoom->аудио, сек (по умолчанию 1800).
  --speaker N=Имя  задать имя спикера вручную (можно несколько раз). Нужно, когда
           двое говорят в один микрофон: Zoom различает каналы, а не голоса, и
           обоих подписывает именем владельца канала. Кто есть кто — видно по
           репликам в сыром ответе Deepgram.

Ключ Deepgram — из окружения DEEPGRAM_API_KEY или из ближайшего `.env` вверх от
папки скрипта (как transcribe.py). Зависимостей нет — только стандартная
библиотека Python 3.8+. Windows и macOS — один и тот же путь.
"""
import sys, os, json, re, argparse, urllib.request, urllib.error
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from transcribe import (load_api_key, deepgram_urlopen,  # ключ, выход в сеть
                        MIME_BY_EXT, VIDEO_EXT)          # и таблицы форматов

MAX_OFFSET = 1800  # ±30 мин: локальная запись стартует не в t0 встречи, разбег бывает большой

# Канонизация имён спикеров Zoom -> короткие имена (совпадают с именами в people).
#
# ТАБЛИЦА ЖИВЁТ В ФАЙЛЕ РЯДОМ, А НЕ В КОДЕ. Zoom подписывает участника так, как
# он назвал себя в своём аккаунте («Ivan Petrov», «ivanp», «Иван П.»), и свести
# эти подписи к именам из `people` может только владелец состава. Список имён и
# логинов сотрудников — персональные данные: в код они не попадают, потому что
# код уезжает в общий установочный пакет, а состав у каждого свой.
#
# `Имена.json` (UTF-8, рядом с этим скриптом, в git не едет — см. `.gitignore`):
#
#     {
#       "Ivan Petrov": "Иван",
#       "ivanp":       "Иван",
#       "Анна С.":     "Анна"
#     }
#
# Файла нет — имена Zoom идут в расшифровку как есть. Это рабочее состояние, а
# не поломка: разбор по такой расшифровке делается точно так же, просто подписи
# длиннее.
NAMES_FILE = os.path.join(SCRIPT_DIR, "Имена.json")


def load_name_map(path=NAMES_FILE):
    """Таблица имён из файла рядом; нет файла — пустая, имена пойдут как есть.

    Поломка файла (не тот JSON, не словарь) ГРОМКАЯ, но не смертельная: работа
    продолжается без канонизации, а человек читает, что именно не прочиталось.
    Молчаливый возврат пустой таблицы был бы хуже — расшифровка вышла бы с
    чужими подписями, и причину пришлось бы искать глазами.
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"[имена] {path} не прочитан ({e}) — подписи Zoom пойдут как есть",
              file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"[имена] {path}: ожидался словарь «подпись Zoom»: «имя» — "
              f"подписи Zoom пойдут как есть", file=sys.stderr)
        return {}
    return {str(k).strip(): str(v).strip()
            for k, v in data.items() if str(k).strip()}


NAME_MAP = load_name_map()


def norm_name(n):
    return NAME_MAP.get((n or "").strip(), (n or "").strip())


def ts_to_sec(ts):
    """'HH:MM:SS.mmm' -> секунды (float). Пропускает уже числовые значения."""
    if isinstance(ts, (int, float)):
        return float(ts)
    h, m, s = str(ts).split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def find_items(obj):
    """Достаёт список transcript_items из любого места JSON (полный ответ или items)."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if "transcript_items" in obj:
            return obj["transcript_items"]
        if "meeting_transcript" in obj and isinstance(obj["meeting_transcript"], dict):
            return obj["meeting_transcript"].get("transcript_items", [])
        for v in obj.values():
            got = find_items(v)
            if got:
                return got
    return []


def split_speaker(text):
    """'Ivan Petrov: Привет' -> ('Иван', 'Привет'). Без двоеточия — имя '?'."""
    if ":" in text:
        name, rest = text.split(":", 1)
    else:
        name, rest = "?", text
    return norm_name(name), rest.strip()


# Блок txt-транскрипта Zoom: строка таймкодов, затем строка «Имя: реплика».
#   08:58:24 --> 08:58:26
#   Ivan Petrov: Я могу. Привет?
TXT_TS = re.compile(r"^(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*-->\s*(\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s*$")


def load_zoom_txt(path):
    """Транскрипт Zoom в виде .txt/.vtt (время суток или от начала записи).

    Zoom кладёт такой файл рядом с аудио под именем transcript.txt. Времена
    приводятся к нулю первой реплики: в абсолютном виде это десятки тысяч
    секунд, и поиск сдвига (±max_offset) их бы не достал."""
    with open(path, "r", encoding="utf-8-sig") as f:
        lines = [ln.rstrip("\n") for ln in f]

    out, i, base = [], 0, None
    while i < len(lines):
        m = TXT_TS.match(lines[i].strip())
        if not m:
            i += 1
            continue
        start, end = ts_to_sec(m.group(1)), ts_to_sec(m.group(2))
        i += 1
        buf = []
        while i < len(lines) and lines[i].strip():
            buf.append(lines[i].strip())
            i += 1
        if not buf:
            continue
        if base is None:
            base = start
        name, text = split_speaker(" ".join(buf))
        out.append({"name": name, "start": start - base, "end": end - base, "text": text})
    return out


def load_zoom(path):
    """Транскрипт Zoom: .json (ответ get_meeting_assets или items) либо .txt/.vtt."""
    if os.path.splitext(path)[1].lower() in (".txt", ".vtt"):
        return load_zoom_txt(path)
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    out = []
    for it in find_items(data):
        name, text = split_speaker(it.get("text", ""))
        out.append({"name": name,
                    "start": ts_to_sec(it["start"]),
                    "end": ts_to_sec(it["end"]),
                    "text": text})
    return out


def deepgram(audio_path, model, lang):
    key = load_api_key()
    if not key:
        raise RuntimeError(f"нет ключа DEEPGRAM_API_KEY (окружение или {os.path.join(SCRIPT_DIR, '.env')})")
    q = (f"model={model}&language={lang}&smart_format=true"
         "&punctuate=true&diarize=true&utterances=true")
    ext = os.path.splitext(audio_path)[1].lower()
    mime = MIME_BY_EXT.get(ext, "audio/mpeg")
    with open(audio_path, "rb") as f:
        audio = f.read()
    print(f"[Deepgram] отправляю {len(audio)/1024/1024:.0f} МБ, {model}/{lang} ... (~минута)", flush=True)
    req = urllib.request.Request("https://api.deepgram.com/v1/listen?" + q,
                                 data=audio, method="POST",
                                 headers={"Authorization": f"Token {key}", "Content-Type": mime})
    with deepgram_urlopen(req, timeout=1800) as r:
        return json.load(r)


def utts_of(dg):
    out = []
    for u in dg.get("results", {}).get("utterances", []):
        t = (u.get("transcript") or "").strip()
        if t:
            out.append((float(u["start"]), float(u["end"]), int(u.get("speaker", 0)), t))
    return out


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _speech_mask(spans):
    """Посекундная маска речи как длинное целое: бит i = 1, если в секунду i кто-то говорит.

    Целое, а не список: AND и popcount уходят в C, поэтому перебор тысяч сдвигов
    занимает доли секунды вместо минут."""
    mask = 0
    for start, end in spans:
        a, b = int(max(0.0, start)), int(max(0.0, end))
        if b > a:
            mask |= ((1 << (b - a)) - 1) << a
    return mask


def best_offset(utts, zoom, max_off=MAX_OFFSET):
    """Глобальный сдвиг Zoom->аудио (audio_t = zoom_t + off): перебор ±max_off, шаг 1с.

    Запись стартует не в t0 встречи, и разбег бывает в десятки
    минут — отсюда широкий диапазон. Совпадение меряем по маске «речь/тишина»:
    она не зависит от того, кто именно говорит, и ловит сдвиг по рисунку пауз.
    Возвращает (сдвиг, секунд перекрытия) — второе число показывает, верить ли сдвигу."""
    a_mask = _speech_mask((u[0], u[1]) for u in utts)
    z_mask = _speech_mask((z["start"], z["end"]) for z in zoom)
    best, best_ov = 0, -1
    for off in range(-max_off, max_off + 1):
        shifted = (z_mask << off) if off >= 0 else (z_mask >> -off)
        ov = (shifted & a_mask).bit_count()
        if ov > best_ov:
            best, best_ov = off, ov
    return best, best_ov


def map_speakers(utts, zoom, off):
    acc = defaultdict(lambda: defaultdict(float))
    for a0, a1, spk, txt in utts:
        for z in zoom:
            ov = overlap(a0, a1, z["start"] + off, z["end"] + off)
            if ov > 0:
                acc[spk][z["name"]] += ov
    mapping, purity = {}, {}
    for spk, names in acc.items():
        total = sum(names.values()) or 1.0
        name, ov = max(names.items(), key=lambda kv: kv[1])
        mapping[spk], purity[spk] = name, ov / total
    return mapping, purity


def split_by_zoom(utts, zoom, off, spk_no, fallback, exclude=()):
    """Имена на КАЖДУЮ реплику голоса ``spk_no`` — по Zoom, а не одно на голос.

    Обратный случай к `--speaker`. Там Zoom не различил двоих (один микрофон) и
    имя даёт человек; здесь наоборот — Zoom различает (у каждого свой аккаунт),
    а Deepgram свёл два близких мужских голоса в один кластер. Разобранный случай
    01.09.2026: двое говорили вперемежку весь звонок, чистота голоса вышла 83 %,
    и пятая часть реплик уехала бы не тому.

    Имя берём по наибольшему перекрытию с репликой Zoom в этот момент. Ничего
    не пересеклось — оставляем имя голоса: пустая подпись хуже приблизительной.

    ``exclude`` — имена, уже закреплённые за ДРУГИМИ голосами. Их из кандидатов
    выкидываем: у своего голоса человек уже есть, и появиться внутри чужого он
    может только перебивкой или огрехом Zoom. Без этого в том же разборе минута
    речи внутри одного голоса подписывалась вторым участником, у которого свой
    голос стоял рядом.
    """
    out = {}
    for i, (a0, a1, spk, _txt) in enumerate(utts):
        if spk != spk_no:
            continue
        acc = defaultdict(float)
        for z in zoom:
            if z["name"] in exclude:
                continue
            ov = overlap(a0, a1, z["start"] + off, z["end"] + off)
            if ov > 0:
                acc[z["name"]] += ov
        out[i] = max(acc.items(), key=lambda kv: kv[1])[0] if acc else fallback
    return out


def shared_names(mapping, forced):
    """Имена, доставшиеся больше чем одному спикеру: [(имя, [номера])].

    Zoom различает КАНАЛЫ, а не голоса. Двое за одним компьютером получают имя
    владельца микрофона, а сидящие под безымянным аккаунтом («Пользователь
    Zoom») — эту подпись оба. Deepgram их развёл, склейка снова свела, и
    расшифровка выглядит целой: в ней просто нет одного человека. Молчание тут
    дороже всего — разбор уйдёт на сервер с задачей, приписанной не тому.

    Заданные вручную (`--speaker`) не считаются: человек уже развёл спикеров, и
    повторять предупреждение значило бы кричать после того, как его услышали.
    """
    by_name = defaultdict(list)
    for spk, name in mapping.items():
        if spk not in forced:
            by_name[name].append(spk)
    return sorted((name, sorted(spks)) for name, spks in by_name.items() if len(spks) > 1)


def parse_overrides(pairs):
    """['1=Анна'] -> {1: 'Анна'}.

    Нужно, когда двое сидят за одним компьютером: Zoom различает каналы, а не
    голоса, и обоих подписывает именем владельца микрофона. Diarize их разделяет,
    но имя второго взять неоткуда — задаём руками."""
    out = {}
    for p in pairs:
        num, sep, name = p.partition("=")
        if not sep or not num.strip().isdigit() or not name.strip():
            raise ValueError(f"--speaker ждёт вид N=Имя, получено: {p!r}")
        out[int(num.strip())] = norm_name(name)
    return out


def hhmm(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def build_md(utts, mapping, meta, per_utt=None):
    """``per_utt`` (номер реплики -> имя) старше ``mapping``: им подписаны голоса,
    разобранные `--split` на нескольких человек."""
    per_utt = per_utt or {}
    lines = [meta, ""]
    cur, buf, block_start = None, [], 0.0
    for i, (a0, a1, spk, txt) in enumerate(utts):
        name = per_utt.get(i) or mapping.get(spk, f"Спикер {spk}")
        if name != cur:
            if buf:
                lines.append(f"[{hhmm(block_start)}] **{cur}:** " + " ".join(buf))
                lines.append("")
            cur, buf, block_start = name, [], a0
        buf.append(txt)
    if buf:
        lines.append(f"[{hhmm(block_start)}] **{cur}:** " + " ".join(buf))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deepgram + имена спикеров из Zoom")
    ap.add_argument("--audio", required=True)
    ap.add_argument("--zoom", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default="nova-3")
    ap.add_argument("--lang", default="multi")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-offset", type=int, default=MAX_OFFSET, dest="max_offset",
                    help="предел поиска сдвига Zoom->аудио в секундах (по умолчанию 1800)")
    ap.add_argument("--dg-json", default=None, dest="dg_json",
                    help="файл сырого ответа Deepgram: есть — читаем его, нет — сохраняем туда")
    ap.add_argument("--split", action="append", default=[], type=int, metavar="N",
                    help="разобрать голос N на людей по именам Zoom пореплично "
                         "(для тех, чьи голоса Deepgram свёл в один, а Zoom различает)")
    ap.add_argument("--speaker", action="append", default=[], metavar="N=Имя",
                    help="задать имя спикера Deepgram вручную, напр. --speaker 1=Анна "
                         "(для тех, кто говорит в чужой микрофон — Zoom их не различает)")
    a = ap.parse_args(argv)

    audio = a.audio.strip().strip('"').strip("'")
    if not os.path.isfile(audio):
        print(f"Ошибка: аудио не найдено: {audio}");  return 1
    if os.path.splitext(audio)[1].lower() in VIDEO_EXT:
        print("Это видео — Deepgram принимает только аудио. Выгрузите аудиодорожку (mp3).");  return 1

    out = (a.out or os.path.join(os.path.dirname(audio), "Транскрипт.md")).strip().strip('"').strip("'")
    if os.path.exists(out) and not a.force:
        print(f"[Пропуск] уже существует: {out} (для перезаписи --force)");  return 0

    zoom = []
    if a.zoom:
        try:
            zoom = load_zoom(a.zoom.strip().strip('"').strip("'"))
            print(f"[Zoom] реплик с именами: {len(zoom)}", flush=True)
        except Exception as e:
            print(f"[Zoom] не удалось прочитать ({e}) — имена не проставлю, будет «Спикер N».", flush=True)

    # Сырой ответ Deepgram кладём рядом и переиспользуем: пересобрать имена или
    # разбивку можно бесплатно, второй раз за то же аудио не платим.
    dg_path = (a.dg_json or os.path.join(os.path.dirname(out) or ".", "Deepgram raw.json")).strip().strip('"').strip("'")
    paid = False
    if os.path.isfile(dg_path):
        with open(dg_path, "r", encoding="utf-8") as f:
            dg = json.load(f)
        print(f"[Deepgram] беру сохранённый ответ: {dg_path} (повторно не плачу)", flush=True)
    else:
        dg = deepgram(audio, a.model, a.lang)
        paid = True
        os.makedirs(os.path.dirname(dg_path) or ".", exist_ok=True)
        with open(dg_path, "w", encoding="utf-8") as f:
            json.dump(dg, f, ensure_ascii=False)
        print(f"[Deepgram] сырой ответ сохранён: {dg_path}", flush=True)

    utts = utts_of(dg)
    dur = float(dg.get("metadata", {}).get("duration", 0))
    print(f"[Deepgram] реплик: {len(utts)}, спикеров: {len(set(u[2] for u in utts))}", flush=True)

    forced = parse_overrides(a.speaker)
    per_utt = {}
    if zoom and utts:
        off, ov_sec = best_offset(utts, zoom, a.max_offset)
        mapping, purity = map_speakers(utts, zoom, off)
        mapping.update(forced)
        print(f"[Склейка] сдвиг Zoom->аудио: {off:+d}с (перекрытие речи {ov_sec/60:.0f} мин)", flush=True)
        if abs(off) >= a.max_offset:
            print("   ВНИМАНИЕ: сдвиг упёрся в границу поиска — увеличь --max-offset.", flush=True)
        for spk in sorted(mapping):
            mark = "задано вручную" if spk in forced else f"чистота {purity.get(spk, 0)*100:.0f}%"
            print(f"   Спикер {spk} -> {mapping[spk]}  ({mark})", flush=True)
        for name, spks in shared_names(mapping, forced):
            hands = " ".join(f"--speaker {s}=Имя" for s in spks)
            print(f"   ВНИМАНИЕ: одно имя «{name}» досталось спикерам "
                  f"{', '.join(str(s) for s in spks)} — Zoom их не различил "
                  f"(один микрофон на двоих или безымянный аккаунт).", flush=True)
            print(f"      Кто есть кто, видно по репликам в сыром ответе Deepgram; "
                  f"доопредели вручную: {hands}", flush=True)
        for spk_no in a.split:
            if spk_no not in mapping:
                print(f"   [--split {spk_no}] такого голоса в записи нет — пропускаю.", flush=True)
                continue
            taken = {nm for sp, nm in mapping.items() if sp != spk_no}
            part = split_by_zoom(utts, zoom, off, spk_no, mapping[spk_no], taken)
            per_utt.update(part)
            share = defaultdict(float)
            for i, nm in part.items():
                share[nm] += utts[i][1] - utts[i][0]
            got = ", ".join(f"{nm} — {sec/60:.0f} мин"
                            for nm, sec in sorted(share.items(), key=lambda kv: -kv[1]))
            print(f"   Голос {spk_no} разобран по Zoom пореплично: {got}", flush=True)

        spk_line = ", ".join(f"{s}→{mapping[s]}" for s in sorted(mapping))
        hand = " · имена вручную: " + ", ".join(sorted(set(forced.values()))) if forced else ""
        if per_utt:
            hand += " · голоса " + ", ".join(str(n) for n in sorted(a.split)) + " разобраны по Zoom пореплично"
        meta = (f"# Транскрипт (Deepgram + имена из Zoom)\n"
                f"Движок: Deepgram {a.model}/{a.lang} · диаризация · имена сшиты с Zoom "
                f"по таймкодам (сдвиг {off:+d}с) · {dur/60:.0f} мин · спикеры: {spk_line}{hand}")
    else:
        mapping = forced
        meta = (f"# Транскрипт (Deepgram, без имён)\n"
                f"Движок: Deepgram {a.model}/{a.lang} · диаризация · {dur/60:.0f} мин "
                f"· Zoom-имена не подключены (восстанови по контексту)")

    md = build_md(utts, mapping, meta, per_utt)
    if len(md.strip()) < 100:
        print("ВНИМАНИЕ: пустой/короткий ответ, файл не сохранён.");  return 1
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    cost = (dur / 60.0) * (0.0092 + 0.0020)  # nova-3 + диаризация, ориентир
    price = f", ~${cost:.2f}" if paid else ", из кэша — бесплатно"
    print(f"[OK] сохранено: {out} ({len(md)} симв.{price})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""meeting.py — механика разбора планёрки: где мы и что дальше (блок 5).

ЗАЧЕМ ОН ЕСТЬ. Раньше весь путь разбора жил инструкцией на 170 строк, которую
агент исполнял «на глаз»: пересказ инструкции каждый раз чуть другой, и порядок
шагов зависел от того, что агент вспомнил. Здесь порядок задан кодом. За агентом
остаётся ровно одно — ИЗВЛЕЧЬ ЗАДАЧИ ИЗ РАЗГОВОРА; всё остальное вызывается.

СОСТОЯНИЕ ЖИВЁТ В ФАЙЛАХ ПАПКИ РАЗБОРА, А НЕ В ПАМЯТИ СЕССИИ. Отсюда «повторный
запуск не переделывает уже сделанное»: `status` смотрит на файлы и называет
следующий шаг, а каждая команда сама пропускает свою работу, если её результат
уже лежит. Прерванный разбор продолжается с того же места хоть завтра.

    Транскрипт.md        расшифровка со сшитыми именами  (шаг «расшифровка»)
    Deepgram raw.json    сырой ответ Deepgram — второй раз за то же аудио не платим
    tasks.json           снимок задач с боевого сервера  (шаг «выгрузка»)
    package.draft.json   разбор агента, ещё НЕ подтверждённый человеком
    package.json         тот же разбор ПОСЛЕ слова «запиши» (шаг «подтверждение»)
    Подтверждение.json   отпечаток подтверждённого пакета и сказанное слово
    Ответ сервера.json   след последней отправки: чей пакет, когда, с каким кодом

ГЕЙТ «ЗАПИШИ» СТАЛ МЕХАНИЧЕСКИМ (инвариант 15, инцидент 14.07). Агент пишет
разбор в ЧЕРНОВИК, а `confirm --word "<то, что сказал человек>"` проверяет само
слово («ок», «понял», «не записывай» — отказ) и делает из черновика пакет.
`send` при этом верит не имени файла, а ОТПЕЧАТКУ: он сверяет `package.json` с
подтверждённым и отвергает любой другой. Агент, записавший пакет напрямую, мимо
слова человека не пройдёт — а держись это одной фразой инструкции «пиши только в
черновик», он прошёл бы. Раньше правило и держалось только фразой.

СУДЬЯ ПАКЕТА — СЕРВЕР, И ТОЛЬКО ОН. `preview` сверяет ровно то, на что у него
есть местный ответ: людей и задачи по `tasks.json`. Формат, даты, ключи пунктов и
права судит `core` на сервере — целиком и до первой записи в базу. Повторять его
правила здесь значило бы завести второго судью, который однажды разойдётся с
первым.

`Ответ сервера.json` — РАСПИСКА КЛИЕНТА, А НЕ РЕЕСТР. Правда о применённом пакете
живёт в базе сервера, и он же судит повтор по отпечатку. Расписка нужна одному:
чтобы `status` знал, чем кончилась прошлая отправка, не ходя в сеть. Пакет
изменился — расписка перестаёт его прикрывать, и отправка идёт заново.

Команды (`--date` по умолчанию сегодня, формат ДД.ММ.ГГ — как имя папки разбора):

    python meeting.py status  --date 09.08.26 [--json]
    python meeting.py find    --date 09.08.26
    python meeting.py transcribe --date 09.08.26 [--audio Ф] [--names Ф] [--speaker N=Имя]
    python meeting.py tasks   --date 09.08.26 [--team Т] [--force]
    python meeting.py preview --date 09.08.26
    python meeting.py confirm --date 09.08.26 --word "запиши"
    python meeting.py send    --date 09.08.26 --team Т [--dry-run]
    python meeting.py publish --date 09.08.26 --team Т

Коды выхода — общие у всего контура ПК, см. `oblako_client`. Команда-скилл ходит
по ним, а не по тексту вывода.

Зависимостей нет — только стандартная библиотека. Windows и macOS — один путь.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import fetch_tasks
import oblako_client as client
import send_package
import transcribe
import zoom_deepgram_merge

SCRIPT = Path(__file__).resolve()

# --- имена файлов состояния -------------------------------------------------
TRANSCRIPT = "Транскрипт.md"
TASKS = "tasks.json"
DRAFT = "package.draft.json"
# Имена подтверждённого пакета и самого подтверждения знает `oblako_client`:
# гейт «запиши» стоит и у прямого клиента, а имя файла — половина этого гейта.
PACKAGE = client.PACKAGE
CONFIRMED = client.CONFIRMED
RECEIPT = "Ответ сервера.json"
CLOUD_NAMES = "Zoom.json"           # timeline из облака Zoom — источник имён

REVIEWS_DIR = "Разборы"             # папка разборов в корне рабочей копии
AUDIO_DIR = "Аудио"                 # запасное место записи, заводит его установка
DATE_FMT = "%d.%m.%y"

# Где искать запись, если её нет в папке разбора. Zoom кладёт локальную запись в
# «Документы/Zoom/<дата время тема>/», облачную человек забирает в «Загрузки».
# Список переопределяется `OBLAKO_AUDIO_DIRS` в `.env` (разделитель — `;`).
AUDIO_DIRS_ENV = "OBLAKO_AUDIO_DIRS"
DEFAULT_AUDIO_DIRS = ("~/Documents/Zoom", "~/Zoom", "~/Downloads", "~/Загрузки")

# Как Zoom называет транскрипт рядом с локальной записью. Имена ТОЧНЫЕ, а не
# «любой .txt»: в той же папке лежит `chat.txt`, и разбор по чату вышел бы без
# единого имени говорящего — молча и правдоподобно.
NAME_SOURCES = ("*.vtt", "transcript.txt", "closed_caption.txt")

# Слово-команда человека. Формы ТОЛЬКО ПОВЕЛИТЕЛЬНЫЕ, а не общий стебель «запиш»:
# «я сам запишу» и «запишем потом» — не поручение агенту, а разговор о себе, и
# по стеблю они прошли бы за команду. Одно и то же решение, сказанное по-разному
# («запиши», «запишите», «записывай»), при этом принимается.
COMMAND = r"(запиши(те)?|записывай(те)?)"
CONFIRM_WORD = re.compile(rf"\b{COMMAND}\b", re.IGNORECASE)
# Отрицание считается ТОЛЬКО непосредственно перед словом-командой: «не
# записывай» — отказ, а «запиши, но не Борису» — законная команда с оговоркой.
CONFIRM_DENIED = re.compile(rf"\bне\s+{COMMAND}\b", re.IGNORECASE)

OP_MARK = {"add": "➕", "close": "✅", "edit": "✏️"}
OP_TITLE = {"add": "Новые", "close": "Закрыть", "edit": "Править"}


# ---------------------------------------------------------------------------
# Папка разбора
# ---------------------------------------------------------------------------
def repo_root() -> Path:
    """Корень рабочей копии: папка, в которой заводится `Разборы`.

    Отвечает на вопрос один `oblako_client.work_root` — тот же, что называет
    место папкам скиллов: разъехавшись, разборы и команды агенту легли бы в
    разные корни. Искать саму `Разборы` для этого нельзя — в свежем клоне пакета
    её может не быть, и корень уехал бы выше клона.
    """
    return client.work_root(SCRIPT)


def meeting_date(stated: str | None) -> date:
    """Дата планёрки. Без аргумента — сегодня; иначе ДД.ММ.ГГ, как имя папки."""
    if not stated:
        return date.today()
    try:
        return datetime.strptime(stated.strip(), DATE_FMT).date()
    except ValueError:
        raise client.Usage(
            f"Дату не разобрать: {stated!r}. Формат — ДД.ММ.ГГ, как имя папки разбора "
            f"(например {date.today().strftime(DATE_FMT)})."
        ) from None


def folder_for(args) -> Path:
    """Папка разбора: явная `--folder` или `Разборы/<ДД.ММ.ГГ>`.

    Явная нужна там, где папку назвали руками («14.07.26 розница»): угадать её
    по дате нечем, а разбор в такой папке — обычное дело.
    """
    if getattr(args, "folder", None):
        return Path(args.folder).expanduser()
    return repo_root() / REVIEWS_DIR / meeting_date(getattr(args, "date", None)).strftime(DATE_FMT)


# ---------------------------------------------------------------------------
# Поиск записи
# ---------------------------------------------------------------------------
def audio_dirs(env: dict) -> list:
    """Папки, где ищем запись: своя `Аудио` и дальше — из `.env` или умолчания.

    Папка `Аудио` рабочей копии стоит ПЕРВОЙ и не убирается ничем. Её заводит
    установка (`setup_check`), на неё же указывает мастер как на запасной путь —
    и пока её не было в этом списке, положенная туда запись не находилась:
    проверка отчитывалась «готово», а разбор отвечал «записи нет». Свой
    `OBLAKO_AUDIO_DIRS` заменяет системные умолчания, а не эту папку.
    """
    stated = (env.get(AUDIO_DIRS_ENV) or "").strip()
    raw = [part for part in stated.split(";") if part.strip()] if stated else DEFAULT_AUDIO_DIRS
    return [repo_root() / AUDIO_DIR] + [Path(part.strip()).expanduser() for part in raw]


def _audio_files(folder: Path, recursive: bool) -> list:
    """Аудио поддерживаемых Deepgram форматов в папке (при нужде — с деревом)."""
    if not folder.is_dir():
        return []
    walk = folder.rglob("*") if recursive else folder.glob("*")
    return [item for item in walk
            if item.is_file() and item.suffix.lower() in transcribe.MIME_BY_EXT]


ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
# Облачная запись Zoom приезжает под именем «GMT20260807-085446_Recording.m4a» —
# дата в нём есть, но слитная. Без этого шаблона файл считался бы «без даты».
PACKED_DATE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
# Скачивают запись ПОСЛЕ встречи, никогда до. Окно нужно тем файлам, у которых
# даты в имени нет вовсе: разбор наутро — обычное дело, и требовать mtime ровно
# в день планёрки значило бы не находить вчерашнюю запись.
DOWNLOAD_WINDOW_DAYS = 7


def _named_dates(path: Path) -> set:
    """Даты, названные в самом пути. Невозможное число (13-й месяц) отбрасывается."""
    found = set()
    for pattern in (ISO_DATE, PACKED_DATE):
        for year, month, day in pattern.findall(str(path)):
            try:
                found.add(date(int(year), int(month), int(day)))
            except ValueError:
                continue
    return found


def _of_date(path: Path, when: date) -> bool:
    """Файл относится к дате встречи. ИМЯ СИЛЬНЕЕ ВРЕМЕНИ ФАЙЛА.

    Zoom называет папку локальной записи «2026-08-07 10.54.46 …», а облачный
    файл — «GMT20260807-…»: там дата сказана прямо, и время файла её не
    отменяет — скопированная запись прошлой планёрки получает сегодняшний mtime
    и иначе выдавала бы себя за эту. Даты в имени нет вовсе — остаётся время
    файла, и годится окно после встречи, а не ровно её день.
    """
    named = _named_dates(path)
    if named:
        return when in named
    try:
        touched = date.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    return when <= touched <= when + timedelta(days=DOWNLOAD_WINDOW_DAYS)


def find_audio(review: Path, when: date, env: dict) -> tuple:
    """(запись, где искали). Сначала папка разбора, затем папки записей.

    Из нескольких кандидатов берём САМЫЙ БОЛЬШОЙ файл: у локальной записи Zoom
    рядом с `audio_only.m4a` лежат обрывки и звуковые эффекты, и «первый по
    алфавиту» однажды окажется не встречей.
    """
    searched = [review]
    found = _audio_files(review, recursive=False)
    if not found:
        for folder in audio_dirs(env):
            searched.append(folder)
            found.extend(item for item in _audio_files(folder, recursive=True)
                         if _of_date(item, when))
    if not found:
        return None, searched
    return max(found, key=lambda item: item.stat().st_size), searched


def find_names(review: Path, audio: Path | None) -> Path | None:
    """Источник имён говорящих: облачный `Zoom.json` или транскрипт рядом с записью.

    Оба пути равноправны (решение 3.3.16): в облаке имена лежат в timeline JSON,
    у локальной записи Zoom — в `transcript.txt`/`.vtt` рядом с аудио.
    """
    cloud = review / CLOUD_NAMES
    if cloud.is_file():
        return cloud
    # Ловить имена «любым файлом рядом» нельзя: в папке разбора лежат
    # `tasks.json`, `Deepgram raw.json` и сам пакет, а у локальной записи —
    # `chat.txt`. Поэтому список видов закрытый.
    for folder in filter(None, (review, audio.parent if audio else None)):
        for pattern in NAME_SOURCES:
            for item in sorted(folder.glob(pattern)):
                return item
    return None


# ---------------------------------------------------------------------------
# Состояние разбора
# ---------------------------------------------------------------------------
# Оба живут в `oblako_client`: их спрашивает и прямой клиент, где стоит тот же
# гейт «запиши». Второе определение здесь разошлось бы с первым молча — и
# отпечаток, которым гейт узнаёт свой пакет, считался бы двумя способами.
read_json = client.read_json
digest = client.digest


def tasks_fresh(snapshot: dict | None) -> bool:
    """Снимок годен, только если снят СЕГОДНЯ.

    Вчерашняя выгрузка — та же ошибка, что разбор по локальной базе: задачи за
    сутки закрывают и переписывают, и пакет по устаревшим id сервер отвергнет
    целиком. Штамп ставит `fetch_tasks`; нет штампа — снимок сделан не им.
    """
    at = ((snapshot or {}).get("source") or {}).get("at")
    if not isinstance(at, str):
        return False
    try:
        return datetime.fromisoformat(at).date() == date.today()
    except ValueError:
        return False


def confirmed_package(review: Path) -> bool:
    """Лежащий пакет — ТОТ САМЫЙ, что подтвердил человек словом.

    Проверяется отпечаток, а не наличие файла. Иначе гейт держался бы одной
    фразой инструкции «пиши только в черновик»: агент, записавший `package.json`
    напрямую, прошёл бы отправку без единого слова человека — то есть ровно тем
    способом, ради закрытия которого гейт и переносился в код.

    Здесь это ВОПРОС СОСТОЯНИЯ («на каком мы шаге»), а не разрешение на отправку:
    разрешение спрашивают у `client.require_confirmation`, и оно сверяет ещё и
    отдел. Разные вопросы — разные функции: `status` про отдел ничего не знает,
    флага `--team` у него нет.
    """
    package = review / PACKAGE
    record = read_json(review / CONFIRMED)
    return bool(record) and package.is_file() and record.get("package") == digest(package)


def snapshot_team(review: Path) -> dict | None:
    """Отдел, по составу которого снят снимок задач, — или None, если он не назван.

    Отдел разбора называется ОДИН РАЗ, на выгрузке: дальше по нему собран весь
    разбор — люди, их открытые задачи, превью. Все следующие шаги сверяются с
    ним, а не спрашивают человека заново.
    """
    snapshot = read_json(review / TASKS)
    team = (snapshot or {}).get("team")
    return team if isinstance(team, dict) else None


def snapshot_fits(review: Path, selector: str | None) -> bool:
    """Снимок в папке снят по ТОМУ кругу людей, что просят сейчас.

    Без `--team` просят всех своих людей — снимок отдела таким кругом не
    является, и наоборот. Поэтому «отдела нет» с обеих сторон — совпадение, а с
    одной — нет.
    """
    team = snapshot_team(review)
    if not (selector or "").strip():
        return team is None
    return client.same_team(selector, team) is True


def state(review: Path, env: dict, when: date) -> dict:
    """Что уже сделано. Единственное место, где это считается."""
    package = review / PACKAGE
    receipt = read_json(review / RECEIPT)
    snapshot = read_json(review / TASKS)
    audio, searched = (None, [])
    if not (review / TRANSCRIPT).is_file():
        audio, searched = find_audio(review, when, env)

    applied = bool(receipt) and receipt.get("exit_code") in (client.EXIT_OK,
                                                            client.EXIT_PUBLISH_INCOMPLETE)
    if applied and package.is_file() and receipt.get("package") != digest(package):
        applied = False                      # пакет переписали — расписка не про него

    return {
        "folder": str(review),
        "date": when.strftime(DATE_FMT),
        "audio": str(audio) if audio else None,
        "searched": [str(item) for item in searched],
        "transcript": (review / TRANSCRIPT).is_file(),
        "tasks": tasks_fresh(snapshot),
        "tasks_stale": snapshot is not None and not tasks_fresh(snapshot),
        "draft": (review / DRAFT).is_file(),
        "package": confirmed_package(review),
        "sent": applied,
        "published": applied and receipt.get("exit_code") == client.EXIT_OK,
        "receipt": receipt,
    }


def next_step(st: dict) -> tuple:
    """(ключ шага, что сделать словами). Порядок шагов задан ЗДЕСЬ и больше нигде."""
    if not st["transcript"] and not st["audio"]:
        return "recording", ("Записи нет. Возьми её из облака Zoom (коннектор) или положи "
                             "файл в папку разбора — и запусти find.")
    if not st["transcript"]:
        return "transcribe", "Расшифровать запись: meeting.py transcribe"
    if not st["tasks"]:
        return "tasks", "Свежая выгрузка с боевого сервера: meeting.py tasks"
    if not st["draft"] and not st["package"]:
        return "extract", ("Извлечь задачи из расшифровки и записать разбор в "
                           f"{DRAFT}. Это работа агента, скриптом её не сделать.")
    if not st["package"]:
        return "confirm", ('Показать превью (meeting.py preview) и ждать слова человека. '
                           'Сказал «запиши» — meeting.py confirm --word "<его слова>"')
    if not st["sent"]:
        return "send", "Отправить пакет на сервер: meeting.py send --team <отдел>"
    if not st["published"]:
        return "publish", ("Итог в группе неполон — досдать: "
                           "meeting.py publish --team <отдел>")
    return "done", "Разбор доведён до публикации. Делать нечего."


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------
def cmd_status(args, env: dict) -> int:
    review = folder_for(args)
    st = state(review, env, meeting_date(getattr(args, "date", None)))
    key, what = next_step(st)
    st["next"] = key
    st["next_hint"] = what
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return client.EXIT_OK

    done = {True: "✔", False: "·"}
    print(f"Разбор {st['date']} · {st['folder']}")
    print(f"  {done[bool(st['audio'] or st['transcript'])]} запись        "
          f"{st['audio'] or ('уже расшифрована' if st['transcript'] else 'не найдена')}")
    print(f"  {done[st['transcript']]} расшифровка   {TRANSCRIPT}")
    print(f"  {done[st['tasks']]} выгрузка      "
          f"{'снимок не сегодняшний — нужен свежий' if st['tasks_stale'] else TASKS}")
    print(f"  {done[st['draft'] or st['package']]} разбор        "
          f"{PACKAGE if st['package'] else DRAFT}")
    print(f"  {done[st['package']]} «запиши»      {PACKAGE}")
    print(f"  {done[st['sent']]} отправлено")
    print(f"  {done[st['published']]} итог в группе")
    print(f"\nДальше: {what}")
    return client.EXIT_OK


def cmd_find(args, env: dict) -> int:
    review = folder_for(args)
    when = meeting_date(getattr(args, "date", None))
    audio, searched = find_audio(review, when, env)
    if not audio:
        raise client.Usage(
            f"Запись за {when.strftime(DATE_FMT)} не найдена.",
            [f"искал в: {item}" for item in searched] +
            ["облачную запись Zoom скачай в одну из этих папок, локальная попадает туда сама",
             f"или положи файл прямо в {review}"])
    names = find_names(review, audio)
    print(f"Запись: {audio} ({audio.stat().st_size / (1024 * 1024):.0f} МБ)")
    print(f"Имена:  {names or 'источника нет — спикеры будут «Спикер N»'}")
    if not names:
        print(f"  Имена берутся из облака Zoom (сохрани timeline в {review / CLOUD_NAMES}) "
              f"или из transcript.txt/.vtt рядом с локальной записью.")
    return client.EXIT_OK


def cmd_transcribe(args, env: dict) -> int:
    """Расшифровка со сшитыми именами. Идемпотентна дважды.

    Готовый `Транскрипт.md` не переписывается, а уже оплаченный ответ Deepgram
    лежит рядом и переиспользуется: пересобрать имена после `--force` можно
    бесплатно, второй раз за то же аудио не платим.

    ЛЮБОЙ СБОЙ РАСШИФРОВКИ — код 1, и это осознанно. Кодов 2 и 3 у контура ПК
    свой смысл, они про СЕРВЕР OBLAKO; Deepgram — чужая машина, и мешать их в
    одну таблицу значило бы врать вызывающей команде. Причину человек всё равно
    видит: её печатает сам склейщик строкой выше.
    """
    review = folder_for(args)
    when = meeting_date(getattr(args, "date", None))
    out = Path(args.out).expanduser() if args.out else review / TRANSCRIPT
    if out.is_file() and not args.force:
        print(f"[Пропуск] расшифровка уже есть: {out}")
        return client.EXIT_OK

    if args.audio:
        audio = Path(args.audio).expanduser()
        if not audio.is_file():
            raise client.Usage(f"Записи нет: {audio}")
    else:
        audio, searched = find_audio(review, when, env)
        if not audio:
            raise client.Usage(
                f"Записи за {when.strftime(DATE_FMT)} нет — расшифровывать нечего.",
                [f"искал в: {item}" for item in searched])

    names = Path(args.names).expanduser() if args.names else find_names(review, audio)
    review.mkdir(parents=True, exist_ok=True)
    argv = ["--audio", str(audio), "--out", str(out)]
    if names:
        argv += ["--zoom", str(names)]
    if args.force:
        argv.append("--force")
    for pair in args.speaker:
        argv += ["--speaker", pair]
    code = zoom_deepgram_merge.main(argv)
    return client.EXIT_OK if code == 0 else client.EXIT_USAGE


def cmd_tasks(args, env: dict) -> int:
    """Свежий снимок задач с боевого сервера — обязательное основание разбора."""
    review = folder_for(args)
    out = review / TASKS
    # «Снят сегодня» — половина годности; вторая половина в том, ТОТ ЛИ это
    # отдел. Снимок Продаж, оставшийся в папке, пропускал бы выгрузку Логистики,
    # и разбор Логистики собрался бы по людям и задачам Продаж — молча и
    # правдоподобно.
    if not args.force and tasks_fresh(read_json(out)) and snapshot_fits(review, args.team):
        print(f"[Пропуск] снимок снят сегодня: {out}")
        return client.EXIT_OK
    argv = ["--out", str(out)]
    if args.team:
        argv += ["--team", args.team]
    return fetch_tasks.main(argv)


def _people_index(snapshot: dict) -> dict:
    """id → человек из снимка. Разбор опирается на него и ни на что другое."""
    return {person.get("id"): person for person in (snapshot.get("people") or [])}


def _task_index(person: dict) -> dict:
    return {task.get("id"): task for task in (person.get("open_tasks") or [])}


def _dates_of(item: dict) -> str:
    """Даты пункта словами. У новой задачи и у правки они значат РАЗНОЕ.

    В `add` пустая дата — просто её отсутствие. В `edit` у обеих дат три
    состояния, и `null` там — «снять»; показать его как «нет даты» значило бы
    спрятать от человека снятие срока, которое он подтверждает словом «запиши».
    """
    parts = []
    for key, label in (("due", "рабочий день"), ("deadline", "дедлайн")):
        if item.get(key):
            parts.append(f"{label} {item[key]}")
    for key, label in (("new_due", "рабочий день →"), ("new_deadline", "дедлайн →")):
        if key in item:
            parts.append(f"{label} {item[key] or 'снять'}")
    if "new_text" in item:
        parts.append(f"текст → «{item['new_text']}»")
    return " · ".join(parts)


def preview_lines(package: dict, snapshot: dict) -> tuple:
    """Превью по людям и список расхождений со снимком.

    Сверяются ровно две вещи, на которые есть местный ответ: тот ли человек и та
    ли задача. Остальное — дело сервера, и повторять его правила здесь нельзя.
    """
    people = _people_index(snapshot)
    by_person: dict = {}
    problems: list = []
    for number, item in enumerate(package.get("items") or [], start=1):
        op = str(item.get("op", "?"))
        person_id = item.get("person_id")
        person = people.get(person_id)
        if person is None:
            problems.append(f"пункт {number}: человека id={person_id} нет в снимке — "
                            f"пакет будет отвергнут целиком")
        elif op in ("close", "edit"):
            task = _task_index(person).get(item.get("task_id"))
            if task is None:
                problems.append(f"пункт {number}: у «{person.get('name')}» нет открытой "
                                f"задачи id={item.get('task_id')}")
            elif (task.get("text") or "").strip() != (item.get("task_text") or "").strip():
                problems.append(f"пункт {number}: текст задачи id={item.get('task_id')} "
                                f"разошёлся со снимком — в снимке «{task.get('text')}»")
        name = (person or {}).get("name") or f"id={person_id}"
        by_person.setdefault(name, {}).setdefault(op, []).append(item)

    lines = []
    for name in sorted(by_person):
        lines.append(f"### {name}")
        for op in ("close", "add", "edit"):
            items = by_person[name].get(op)
            if not items:
                continue
            lines.append(f"{OP_TITLE.get(op, op)}:")
            for item in items:
                head = (f"[#{item['task_id']}] {item.get('task_text', '')}"
                        if op in ("close", "edit") else item.get("text", ""))
                tail = _dates_of(item)
                lines.append(f"  {OP_MARK.get(op, '•')} {head}" + (f" — {tail}" if tail else ""))
        lines.append("")
    return lines, problems


def cmd_preview(args, env: dict) -> int:
    """Превью показывает ЧЕРНОВИК, пока он есть, — иначе подтверждённый пакет.

    Порядок именно такой: после правок руководителя агент переписывает черновик,
    и превью обязано показать новое. Показав вместо него уже подтверждённый
    пакет, оно рассказывало бы человеку о том, что он правил минуту назад.
    """
    review = folder_for(args)
    source = review / (DRAFT if (review / DRAFT).is_file() else PACKAGE)
    package = read_json(source)
    if package is None:
        raise client.Usage(f"Разбора нет: положи его в {review / DRAFT} и покажи превью снова")
    snapshot = read_json(review / TASKS)
    if snapshot is None:
        raise client.Usage(f"Нет снимка задач ({review / TASKS}) — сверять пункты не с чем. "
                           f"Сделай выгрузку: meeting.py tasks")

    meeting = package.get("meeting") or {}
    lines, problems = preview_lines(package, snapshot)
    print(f"Разбор: {meeting.get('kind', 'встреча')} {meeting.get('date', '')} · "
          f"пунктов {len(package.get('items') or [])} · источник {source.name}")
    if source.name == DRAFT and (review / PACKAGE).is_file() and \
            digest(review / DRAFT) != digest(review / PACKAGE):
        print("Черновик расходится с подтверждённым пакетом — на него нужно новое «запиши».")
    print("\n".join(lines))
    if problems:
        print("Расхождения со снимком — пакет в таком виде сервер отвергнет:")
        for line in problems:
            print(f"  · {line}")
        return client.EXIT_USAGE
    print("Люди и задачи сошлись со снимком. Формат и права судит сервер при отправке.")
    return client.EXIT_OK


def confirmed_by(word: str) -> None:
    """Гейт «запиши»: пропускает только явную команду человека.

    Слово приезжает СЛОВАМИ ЧЕЛОВЕКА, а не признаком «агент решил, что можно».
    Пересказ можно сделать любым, а «ок» вместо «запиши» отсюда не проходит —
    это и есть первый пояс от инцидента 14.07 на дороге разбора планёрки.
    """
    said = (word or "").strip()
    if not said:
        raise client.Usage('Гейт «запиши»: не сказано ничего. Передай слова человека: '
                           '--word "запиши"')
    if CONFIRM_DENIED.search(said):
        raise client.Usage(f'Это отказ, а не команда: «{said}». В чужой список ничего не уходит.')
    if not CONFIRM_WORD.search(said):
        raise client.Usage(
            f'«{said}» командой не считается — нужно слово «запиши».',
            ['«ок», «понял», «хорошо», «согласен» — это не команда записи',
             'пока человек не сказал «запиши», в чужой список не уезжает ни одна задача'])


def cmd_confirm(args, env: dict) -> int:
    review = folder_for(args)
    draft, package = review / DRAFT, review / PACKAGE
    confirmed_by(args.word)
    if not draft.is_file():
        if confirmed_package(review):
            print(f"[Пропуск] пакет уже подтверждён: {package}")
            return client.EXIT_OK
        raise client.Usage(f"Черновика разбора нет: {draft}")
    body = read_json(draft)
    if body is None:                                   # битый JSON — до записи пакета
        raise client.Usage(f"Черновик не разобрать: {draft}")
    # Версия формата сверяется ЗДЕСЬ, а не только на сервере. Число живёт в трёх
    # местах — две константы (сервер и клиент, их равенство заперто тестом) и
    # ТЕКСТ инструкции агенту, по которому черновик и пишется. Разойдись текст с
    # константой — свежий пакет получал бы от сервера «сначала обновите пакет»
    # сразу после обновления, и человек ходил бы по кругу. Здесь круг рвётся:
    # отказ приходит до отправки и называет настоящую причину.
    version = body.get("version")
    if version != client.PACKAGE_FORMAT_VERSION:
        raise client.Usage(
            f"Черновик собран по версии формата {version!r}, а этот пакет говорит "
            f"на v{client.PACKAGE_FORMAT_VERSION}",
            ["исправь `version` в черновике разбора и подтверди заново",
             "если черновик писался по инструкции — устарела она, а не разбор: "
             "скажи владельцу системы"])
    package.write_bytes(draft.read_bytes())
    # Отпечаток и слово пишутся ПОСЛЕ пакета: оборвись запись посередине, лучше
    # остаться с неподтверждённым пакетом, чем с подтверждением на пустое место.
    #
    # Отдел приезжает из СНИМКА, а не из флага: флага у `confirm` нет и быть не
    # должно — человек подтверждает тот разбор, который ему показали, а показан
    # он по составу снимка. Записанный здесь отдел потом сверяет отправка.
    (review / CONFIRMED).write_text(json.dumps({
        "package": digest(package),
        "team": snapshot_team(review),
        "word": args.word.strip(),
        "at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f'Слово сказано («{args.word.strip()}») — разбор подтверждён: {package}')
    print("Дальше: meeting.py send --team <отдел>")
    return client.EXIT_OK


def _same_receipt_team(recorded, selector: str) -> bool:
    """Тот ли отдел назван, что записан в расписке.

    В расписке лежит СЕЛЕКТОР словом человека («1» или «Продажи»), а не номер:
    что назвали, то и записали. Поэтому два написания одного отдела расписка
    различить не может, и расхождение ведёт не к отказу, а к повторному вызову
    сервера — тот узнаёт пакет по отпечатку и второй раз задачи не заводит.
    """
    return isinstance(recorded, str) and recorded.strip().lower() == selector.strip().lower()


def write_receipt(review: Path, package: Path, team: str, code: int) -> None:
    """След отправки. Пишется ВСЕГДА — и на успех, и на отказ."""
    (review / RECEIPT).write_text(json.dumps({
        "package": digest(package),
        "team": team,
        "at": datetime.now().isoformat(timespec="seconds"),
        "exit_code": code,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_send(args, env: dict) -> int:
    """Отправка пакета. Повтор по тому же пакету на сервер не идёт.

    Сервер и сам узнал бы повтор по отпечатку, но идти к нему незачем: расписка
    уже знает исход, а лишний вызов на неполном итоге читался бы как «досдал».
    """
    review = folder_for(args)
    # Отдел спрашивается ДО всего остального: забытый флаг не должен оставлять
    # ни расписки, ни половины работы.
    team = client.team(args.team)
    package = review / PACKAGE
    if not (review / CONFIRMED).is_file() and (review / DRAFT).is_file():
        raise client.Usage(
            f"Этот пакет человек не подтверждал: {package}",
            ["сначала превью и слово человека: meeting.py preview, затем "
             'confirm --word "<его слова>"',
             f"черновик разбора на месте: {review / DRAFT}"])
    # Гейт «запиши» и сверку отдела судит ОДНА функция на обоих клиентов —
    # прямой `send_package.py` спрашивает её же.
    client.require_confirmation(package, team)
    st = state(review, env, meeting_date(getattr(args, "date", None)))
    # Пропуск повтора — только если отдел ТОТ ЖЕ. Расписка знает свой отдел, и
    # без сверки первая же опечатка в `--team` пряталась бы за «уже отправлено»:
    # разбор ушёл в чужой отдел, нужный не получил ничего, а человеку сказали,
    # что всё сделано.
    receipt_team = (st["receipt"] or {}).get("team")
    if st["sent"] and not args.dry_run and _same_receipt_team(receipt_team, team):
        code = (st["receipt"] or {}).get("exit_code", client.EXIT_OK)
        print(f"[Пропуск] этот пакет уже отправлен {(st['receipt'] or {}).get('at')} "
              f"(код {code}) — второй раз задачи не заводим.")
        if code == client.EXIT_PUBLISH_INCOMPLETE:
            print(f"Итог в группе неполон — досдать: meeting.py publish --team {team}")
        return code

    argv = ["--package", str(package), "--team", team]
    if args.dry_run:
        argv.append("--dry-run")
    code = send_package.main(argv)
    if not args.dry_run:
        write_receipt(review, package, team, code)
    return code


def cmd_publish(args, env: dict) -> int:
    """Досдача итога в чат отдела. Всегда идёт на сервер — это её работа."""
    review = folder_for(args)
    team = client.team(args.team)
    # Отдел сверяется с распиской ЭТОГО разбора. Досдача публикует последний
    # применённый пакет НАЗВАННОГО отдела, а не пакет этой папки: назови другой
    # отдел — и в его чат уедет второй раз чужой позавчерашний итог, а здешний
    # так и останется недосданным. Расписки ещё нет (пакет не отправляли) —
    # сверять не с чем, отказ даст сервер.
    receipt = read_json(review / RECEIPT)
    recorded = (receipt or {}).get("team")
    if receipt and not _same_receipt_team(recorded, team):
        raise client.Usage(
            f"Этот разбор сдавали в отдел «{recorded}», а досдаём в «{team}»",
            ["досдача публикует итог названного отдела — чужой чат получил бы "
             "чужую планёрку второй раз",
             f"тот же отдел: meeting.py publish --team \"{recorded}\""])
    package = review / PACKAGE
    argv = ["--publish-only", "--team", team]
    # Своя встреча называется серверу, когда пакет ещё под рукой: досдача
    # публикует последний применённый пакет отдела, а разбор планёрки и разбор
    # 1:1 одного отдела в один день — обычное дело.
    meeting = (read_json(package) or {}).get("meeting") or {}
    if meeting.get("date") and meeting.get("kind"):
        argv += ["--meeting-date", str(meeting["date"]),
                 "--meeting-kind", str(meeting["kind"])]
    code = send_package.main(argv)
    if package.is_file() and code in (client.EXIT_OK, client.EXIT_PUBLISH_INCOMPLETE):
        write_receipt(review, package, team, code)
    return code


COMMANDS = {
    "status": cmd_status, "find": cmd_find, "transcribe": cmd_transcribe,
    "tasks": cmd_tasks, "preview": cmd_preview, "confirm": cmd_confirm,
    "send": cmd_send, "publish": cmd_publish,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Механика разбора планёрки Oblako")
    subs = parser.add_subparsers(dest="command", required=True)

    def common(name: str, help_text: str):
        sub = subs.add_parser(name, help=help_text)
        sub.add_argument("--date", help="дата планёрки ДД.ММ.ГГ (по умолчанию сегодня)")
        sub.add_argument("--folder", help="папка разбора целиком (вместо --date)")
        return sub

    status = common("status", "где мы и что дальше")
    status.add_argument("--json", action="store_true", help="машинный вид для агента")

    common("find", "какая запись и какой источник имён нашлись")

    tr = common("transcribe", "расшифровать запись и сшить имена")
    tr.add_argument("--audio", help="файл записи (без него — поиск)")
    tr.add_argument("--names", help="источник имён: Zoom.json, transcript.txt или .vtt")
    tr.add_argument("--out", help="куда писать расшифровку (без него — Транскрипт.md в папке)")
    tr.add_argument("--speaker", action="append", default=[], metavar="N=Имя",
                    help="назначить имя спикера вручную (общий микрофон)")
    tr.add_argument("--force", action="store_true", help="перезаписать готовую расшифровку")

    tasks = common("tasks", "свежая выгрузка задач с боевого сервера")
    tasks.add_argument("--team", help="отдел: номер или имя (без него — все свои люди)")
    tasks.add_argument("--force", action="store_true", help="выгрузить заново")

    common("preview", "превью разбора по людям и сверка со снимком")

    confirm = common("confirm", "гейт «запиши»: черновик становится пакетом")
    confirm.add_argument("--word", required=True, help="то, что сказал человек, дословно")

    send = common("send", "отправить пакет на сервер")
    send.add_argument("--team", help="отдел разбора: номер или имя (обязателен)")
    send.add_argument("--dry-run", action="store_true", dest="dry_run",
                      help="показать, что уедет, и не отправлять")

    publish = common("publish", "досдать итог планёрки в чат отдела")
    publish.add_argument("--team", help="отдел разбора: номер или имя (обязателен)")
    return parser


def main(argv=None) -> int:
    client.setup_console()
    args = _parser().parse_args(argv)
    env = client.settings(SCRIPT)
    try:
        return COMMANDS[args.command](args, env)
    except client.ClientError as error:
        return client.fail(error, env.get(client.KEY_ENV))
    except Exception:                         # трассировка — только очищенная от ключа
        return client.crash(env.get(client.KEY_ENV))


if __name__ == "__main__":
    sys.exit(main())

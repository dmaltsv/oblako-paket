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

    Встреча.json         карточка встречи с сервера (какая встреча, чей отдел,
                         отчитался ли автомат, uuid записи) — шаг «встреча»,
                         нужен команде «разбери встречу с <кем> <когда>»
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

СУДЬЯ ПАКЕТА — СЕРВЕР, И ТОЛЬКО ОН. Формат, ключи пунктов, права и даты судит
`core` — целиком и до первой записи в базу; отказ сервера окончателен, а местная
сверка не даёт пакету ни одного разрешения, которого сервер не дал бы сам.

`preview` сверяет то, на что у него есть местный ответ по `tasks.json`: людей,
задачи и — с #467 — РАЗВИЛКУ ДВУХ КРУГОВ (новую задачу можно любому в компании,
закрыть и править — только у состава отдела, чужому из дат положен лишь
`deadline`). Это повтор серверных правил, и заведён он сознательно: гейт
«запиши» механический, и узнать об отказе руководитель обязан ДО своего слова, а
не после того, как поверил, что разбор сдан. Цена повтора известна — второй
судья однажды разойдётся с первым, — поэтому правила повторяются ТЕМИ ЖЕ
СЛОВАМИ, что скажет сервер, и держатся сквозными тестами разбора. Всё, чему
местного ответа нет, здесь не судится вовсе.

`Ответ сервера.json` — РАСПИСКА КЛИЕНТА, А НЕ РЕЕСТР. Правда о применённом пакете
живёт в базе сервера, и он же судит повтор по отпечатку. Расписка нужна одному:
чтобы `status` знал, чем кончилась прошлая отправка, не ходя в сеть. Пакет
изменился — расписка перестаёт его прикрывать, и отправка идёт заново.

СНАЧАЛА БИБЛИОТЕКА, ПОТОМ DEEPGRAM (волна 2, #459). Планёрку отдела к утру уже
расшифровал автомат организатора и положил текст в Библиотеку — платить Deepgram
второй раз за тот же час незачем. Поэтому `status` ищет готовый текст и в КЛОНЕ
Библиотеки: правило пути там одно и держит его `library.py`
(`Транскрипты/<ГГГГ-ММ-ДД> <название>.md`; у отделов — внутри `Отделы/<Отдел>/`).
Найденный текст — сделанный шаг «расшифровка», и `transcribe` его не заказывает.
Обновить клон (`library.py pull`) — дело агента: этот скрипт в сеть за
Библиотекой не ходит, иначе «где мы?» зависало бы в поезде. КАКОЙ ИЗ ТЕКСТОВ ДНЯ
ПРО ЭТУ ВСТРЕЧУ, РЕШАЕТ КАРТОЧКА (`Встреча.json`, команда `meetings --pick`), а
не скрипт, — и решает всегда, даже когда текст за день один: Библиотека общая на
всю компанию, и единственная расшифровка «за сегодня» бывает планёркой другого
отдела. Взятый наугад чужой текст дошёл бы до разбора неотличимым от нужного.

СВОЙ ТРАНСКРИПТ УЕЗЖАЕТ В БИБЛИОТЕКУ ПОСЛЕДНИМ ШАГОМ (решение Р3): текст
планёрки отдела и совета, расшифрованный на этом ПК, после отправки пакета
кладётся `library.py put --kind transcript`. `status` видит, лежит ли он там уже
(тот же файл байт в байт), и пока нет — называет этот шаг. Встречи 1:1 и разовые
— по решению организатора (Р16), для них шаг не обязателен.

Команды (`--date` по умолчанию сегодня, формат ДД.ММ.ГГ — как имя папки разбора):

    python meeting.py status  --date 09.08.26 [--json]
    python meeting.py meetings --date 09.08.26 [--to 10.08.26] [--json] [--pick НОМЕР]
    python meeting.py find    --date 09.08.26
    python meeting.py transcribe --date 09.08.26 [--audio Ф] [--names Ф] [--speaker N=Имя]
    python meeting.py tasks   --date 09.08.26 [--team Т] [--force]
    python meeting.py preview --date 09.08.26
    python meeting.py confirm --date 09.08.26 --word "запиши"
    python meeting.py send    --date 09.08.26 --team Т [--dry-run] [--no-publish]
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
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import avtomat
import fetch_tasks
import library
import oblako_client as client
import send_package
import transcribe
import zoom_deepgram_merge

SCRIPT = Path(__file__).resolve()

# --- имена файлов состояния -------------------------------------------------
MEETING = "Встреча.json"            # карточка встречи с сервера (meetings --pick)
TRANSCRIPT = "Транскрипт.md"
TASKS = "tasks.json"
DRAFT = "package.draft.json"
# Имена подтверждённого пакета и самого подтверждения знает `oblako_client`:
# гейт «запиши» стоит и у прямого клиента, а имя файла — половина этого гейта.
PACKAGE = client.PACKAGE
CONFIRMED = client.CONFIRMED
RECEIPT = "Ответ сервера.json"
CLOUD_NAMES = "Zoom.json"           # ответ Zoom-коннектора целиком — источник имён

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

# Виды, по имени которых видно, ЧЬИ это имена: `GMT…_Recording.vtt` называет
# запись, к которой он положен. В общей папке записей такой файл берётся только
# у своей записи (`find_names`); остальные два вида — постоянные имена внутри
# папки локальной записи Zoom, и различать ими нечего.
NAME_BY_MEETING = ("*.vtt",)

# Слово человека судит `oblako_client.confirmed_by` — тот же судья, что у записи
# в Библиотеку (`library.py put`). Копии правила здесь нет намеренно: разойдясь,
# две копии дали бы одному сказанному слову два разных смысла.

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

    ИМЯ СИЛЬНЕЕ РАЗМЕРА — по той же причине, по какой в `_of_date` имя сильнее
    времени файла. Дата встречи, названная в пути («2026-08-21 08.58.54 Планёрка
    Розница»), — свидетельство о самой встрече; размер не свидетельствует ни о
    чём. Пока правило было «просто самый большой», посторонний mp3 экранного
    рекордера на 124 МБ в корне выигрывал у записи планёрки в соседней папке
    Zoom, и разбор шёл по чужому файлу — молча и без единого имени (#278).

    Из равных по этому признаку берём САМЫЙ БОЛЬШОЙ: у локальной записи Zoom
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
    return max(found, key=lambda item: (when in _named_dates(item),
                                        item.stat().st_size)), searched


def find_names(review: Path, audio: Path | None) -> Path | None:
    """Источник имён говорящих: `Zoom.json` в папке разбора или транскрипт рядом с записью.

    Оба пути равноправны (решение 3.3.16): `Zoom.json` — ответ коннектора,
    сохранённый агентом; у локальной записи Zoom имена бывают в
    `transcript.txt`/`.vtt` рядом с аудио.

    ФАЙЛА НЕТ — ЭТО НЕ «ИМЁН НЕТ». Имена лежат у самой встречи Zoom и тогда,
    когда записи в облаке не было вовсе; принести их сюда может только агент
    (`search_meetings` → `get_meeting_assets`), и об этом говорит подсказка
    `find`. Скрипт в сеть не ходит: коннектор Zoom есть у агента, не у него.
    """
    cloud = review / CLOUD_NAMES
    if cloud.is_file():
        return cloud
    # Ловить имена «любым файлом рядом» нельзя: в папке разбора лежат
    # `tasks.json`, `Deepgram raw.json` и сам пакет, а у локальной записи —
    # `chat.txt`. Поэтому список видов закрытый.
    #
    # ТЁЗКА ЗАПИСИ — ПЕРВЫЙ, А В ПАПКЕ ЗАПИСЕЙ — ЕДИНСТВЕННЫЙ ГОДНЫЙ.
    # `zoom_pull.py --meeting` (#450) кладёт транскрипт Zoom под именем звука
    # («GMT…_Recording.vtt» рядом с «…_Recording.m4a») в ОБЩУЮ папку записей, где
    # копятся и прошлые планёрки со своими `.vtt`. «Первый по алфавиту» там —
    # транскрипт самой старой встречи, и её имена пришивались бы к сегодняшнему
    # разговору МОЛЧА: склейка сдвиг подбирает всегда и о чужом тексте не знает,
    # а разбор потом ставит задачи не тем людям. Свежая запись без своего `.vtt`
    # — случай штатный (Zoom дописывает транскрипт ПОЗЖЕ звука), и «Спикер N»
    # здесь честнее чужих имён.
    #
    # СВОЙ — И ТОТ, ЧЬЁ ИМЯ НАЧИНАЕТСЯ С ИМЕНИ ЗВУКА, а не только точный тёзка.
    # Скачанный из кабинета Zoom транскрипт зовётся «GMT…_Recording.transcript.
    # vtt» при звуке «GMT…_Recording.m4a»: стволы имён РАЗНЫЕ, хотя это свой
    # текст своей записи. Пока годился один точный тёзка, такие имена молча
    # терялись, расшифровка выходила «Спикер 1…8», и восстановление стоило
    # получаса ручной работы. Чужая планёрка под это не подходит: её имя
    # начинается со своего времени, а не со времени этой записи.
    #
    # `transcript.txt` и `closed_caption.txt` под правило имени не попадают: их
    # кладёт локальная запись Zoom в СВОЮ папку встречи, где чужому взяться
    # неоткуда, а имя у них одно на любую запись — тёзкой звука им не стать.
    stem = audio.stem if audio else None

    def _mine(item: Path) -> bool:
        return bool(stem) and (item.stem == stem or item.stem.startswith(stem))

    for folder, mine_only in ((review, False), (audio.parent if audio else None, True)):
        if folder is None:
            continue
        for pattern in NAME_SOURCES:
            for item in sorted(folder.glob(pattern),
                               key=lambda item: (item.stem != stem, not _mine(item), item.name)):
                if mine_only and pattern in NAME_BY_MEETING and not _mine(item):
                    break          # своего нет (он был бы первым) — чужой не годится
                return item
    return None


# ---------------------------------------------------------------------------
# Карточка встречи и готовый текст в Библиотеке
# ---------------------------------------------------------------------------
def meeting_card(review: Path) -> dict | None:
    """Карточка встречи из `Встреча.json` — то, что сервер отдал `meetings --pick`.

    Короткая выжимка, а не весь ответ: разбору нужны название (по нему ищется
    транскрипт в Библиотеке), отдел (для `--team`), отчитался ли автомат, uuid
    записи в облаке Zoom и АДРЕС ГОТОВОГО ТЕКСТА, если автомат уже отчитался.
    Файла нет — разбор идёт как прежде, по одной дате.

    Адрес (`report_repo`/`report_path`) кладёт сервер из отчёта автомата. Его
    может не быть вовсе — у задания, которое ещё не отчиталось, и у сервера
    старее этой правки; тогда транскрипт ищется прежним путём, по названию
    встречи. Отступление обязательно: пакет и сервер обновляются порознь.
    """
    one = read_json(review / MEETING)
    if not isinstance(one, dict) or not one.get("title"):
        return None
    job = one.get("job") if isinstance(one.get("job"), dict) else {}
    return {
        "id": one.get("id"),
        "title": str(one.get("title")),
        "date": one.get("date"),
        "start_time": one.get("start_time"),
        "organizer": (one.get("organizer") or {}).get("name"),
        "team": (one.get("team") or {}).get("name"),
        "automaton": job.get("status"),
        "zoom_uuid": job.get("zoom_uuid"),
        "report_repo": job.get("report_repo"),
        "report_path": job.get("report_path"),
    }


def reported_transcript(found: list, card: dict | None) -> Path | None:
    """Текст по адресу, НАЗВАННОМУ СЕРВЕРОМ, — точнее любой догадки по имени.

    Автомат отчитывается репозиторием и путём внутри клона, и сервер держит их у
    задания. Пока разбор их не спрашивал, адрес приходилось вычислять заново из
    НЫНЕШНЕГО названия встречи (`library_transcripts`) — а подписан файл был
    названием НА МОМЕНТ расшифровки. Встречу переименовали — имена расходятся,
    готовый текст перестаёт находиться, и Deepgram платится второй раз за тот же
    час. Адрес от сервера этого не знает: он не догадка, а факт.

    Ключей нет или они пусты (задание не отчитывалось, сервер старее этой
    правки) — `None`, и вызывающий идёт прежним путём. Путь за пределы клона
    («..», абсолютный) отвергается: он приходит по сети, и проверить его дешевле
    один раз здесь, чем объяснять потом, откуда взялся чужой файл.
    """
    where = str((card or {}).get("report_path") or "").strip().replace("\\", "/")
    if not where:
        return None
    parts = [part for part in where.split("/") if part]
    if not parts or ".." in parts or where.startswith("/") or ":" in parts[0]:
        return None
    name = str((card or {}).get("report_repo") or "").strip().lower()
    for repo in found:
        if not repo.cloned or (name and repo.name.lower() != name):
            continue
        item = repo.path.joinpath(*parts)
        if item.is_file():
            return item
    return None


def library_transcripts(when: date, env: dict, card: dict | None) -> tuple:
    """(готовый текст, все транскрипты этого дня) в клонах Библиотеки.

    ПРАВИЛО ПУТИ БЕРЁТСЯ У `library.py`, а не повторяется здесь: имя файла
    складывается из его же шаблона вида `transcript`, папка отдела — из его же
    `TEAMS_DIR`. Разойдись две копии правила — автомат клал бы текст туда, где
    разбор его не ищет, и Deepgram оплачивался бы дважды молча.

    ВЫБОР — ПО НАЗВАНИЮ ВСТРЕЧИ, А НЕ ПО РАЗМЕРУ, АЛФАВИТУ ИЛИ ЧИСЛУ ФАЙЛОВ.
    Название приезжает в карточке (`Встреча.json`) и чистится так же, как его
    чистит автомат перед записью (`avtomat.title_of`) — иначе «Планёрка (Розница
    / север)» не нашла бы саму себя.

    КАРТОЧКИ НЕТ — ГОТОВОГО ТЕКСТА НЕТ, даже когда транскрипт за день ровно один.
    Библиотека общая на всю компанию: единственный текст этого дня — это скорее
    планёрка ДРУГОГО отдела, положенная чужим автоматом. Пока «один за день»
    считался своим, разбор шёл по чужому разговору целиком: Deepgram молчал,
    `status` говорил «расшифровка есть», агент читал чужой текст — и задачи
    уезжали людям со встречи, на которой их не было. Один файл или десять,
    вопрос «этот ли текст про эту встречу» решает карточка; другого ответа у
    скрипта нет и быть не может.

    ПЕРВЫМ СПРАШИВАЕТСЯ АДРЕС ОТ СЕРВЕРА (`reported_transcript`), и только если
    его нет — имя складывается по названию встречи. Порядок именно такой:
    название встречи меняют кнопкой на экране, а файл в Библиотеке остаётся под
    старым именем, и вычисленное имя перестаёт совпадать с ним навсегда.

    Второй список (`seen`) — ВСЕ транскрипты дня, а не только подходящие: по
    нему `state` сверяет байты своего текста с тем, что уже лежит в Библиотеке,
    и обрезать его до кандидатов на выбор нельзя. Из чего выбирает человек,
    решает `library_choice`.

    Сети здесь нет: клон обновляет агент (`library.py pull`). Библиотека не
    настроена или клонов нет — пустой ответ, а не отказ: пакет без Библиотеки
    разбирает планёрки ровно как прежде.
    """
    try:
        found = library.repos(env)
    except client.Usage:
        return None, []
    inside = library.KINDS["transcript"]["path"]
    day = when.strftime(library.ISO_DATE)
    seen: list = []
    for repo in found:
        if not repo.cloned:
            continue
        pattern = inside.format(date=day, title="*")
        if not repo.root_level:
            pattern = f"{library.TEAMS_DIR}/*/{pattern}"
        seen.extend(item for item in sorted(repo.path.glob(pattern)) if item.is_file())
    reported = reported_transcript(found, card)
    if reported is not None:
        return reported, seen
    if not seen or not card:
        return None, seen
    wanted = inside.format(date=day, title=avtomat.title_of(card)).split("/")[-1]
    exact = [item for item in seen if item.name == wanted]
    return (exact[0] if exact else None), seen


def library_choice(seen: list, card: dict | None) -> list:
    """Из чего выбирает ЧЕЛОВЕК: чужие тексты дня — выбор только без карточки.

    Карточка есть, а файла под названием этой встречи среди них нет — значит все
    они про ДРУГИЕ встречи, и выбирать не из чего: разбор идёт к записи и к
    расшифровке. Пока эти файлы считались кандидатами, шаг `choose` вставал
    поперёк дороги — «в Библиотеке несколько транскриптов» при одном чужом, — и
    ветки «забрать запись» и «расшифровать» становились недостижимы вовсе:
    выйти можно было только `transcribe --force`, который инструкция разрешает
    лишь по слову человека «текст автомата не годится».
    """
    return [] if card else list(seen)


def same_bytes(one: Path, others: list) -> bool:
    """Лежит ли ЭТОТ файл среди других байт в байт — так `status` узнаёт, что
    свой транскрипт уже в Библиотеке, не запоминая этого нигде."""
    if not one.is_file():
        return False
    mine = digest(one)
    return any(item.is_file() and digest(item) == mine for item in others)


def package_kind(review: Path) -> str | None:
    """Вид встречи из пакета (или черновика): «планёрка» или «1:1»."""
    body = read_json(review / PACKAGE) or read_json(review / DRAFT) or {}
    meeting = body.get("meeting") if isinstance(body, dict) else None
    return (meeting or {}).get("kind") if isinstance(meeting, dict) else None


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
    card = meeting_card(review)
    own = review / TRANSCRIPT
    # Готовый текст — свой или из Библиотеки. Свой сильнее: агент мог
    # расшифровать заново (`--force`) поверх плохого текста автомата.
    ready, in_library = library_transcripts(when, env, card)
    transcript = own if own.is_file() else ready
    audio, searched = (None, [])
    if transcript is None:
        audio, searched = find_audio(review, when, env)

    applied = bool(receipt) and receipt.get("exit_code") in (client.EXIT_OK,
                                                            client.EXIT_PUBLISH_INCOMPLETE,
                                                            client.EXIT_NO_PUBLISH)
    if applied and package.is_file() and receipt.get("package") != digest(package):
        applied = False                      # пакет переписали — расписка не про него

    return {
        "folder": str(review),
        "date": when.strftime(DATE_FMT),
        "meeting": card,
        "audio": str(audio) if audio else None,
        "searched": [str(item) for item in searched],
        "transcript": transcript is not None,
        "transcript_file": str(transcript) if transcript else None,
        "transcript_here": own.is_file(),
        "library": bool(client.library_urls(env)),
        "library_transcript": str(ready) if ready else None,
        "library_candidates": [str(item) for item in library_choice(in_library, card)],
        # ВСЕ транскрипты дня, а не только те, из чего выбирают. `candidates` —
        # судья ШАГА, и с карточкой он пуст по построению; пока другого ключа не
        # было, файлы дня при названной встрече не показывались НИГДЕ. А именно
        # там и живёт беда переименования: текст этой самой встречи лежит под
        # прежним названием, разбор его не узнаёт и платит Deepgram второй раз.
        # Видит их теперь и человек, и агент — до того, как деньги уйдут.
        "library_seen": [str(item) for item in in_library],
        # Свой текст уже в Библиотеке — ТОЛЬКО тот же файл байт в байт. Помнить
        # об этом негде и незачем: клон и есть ответ.
        #
        # Совпадения имени НЕ ХВАТАЕТ, и это не придирка. `transcribe --force`
        # значит «текст автомата не годится»: файл под названием встречи в
        # Библиотеке уже лежит — плохой, — а свой, исправленный, туда ещё не
        # положен. Пока имя считалось за ответ, шаг Р3 не появлялся никогда, и
        # забракованный текст оставался в Библиотеке насовсем: его читают
        # подготовка, повестка и следующий разбор той же встречи.
        "transcript_in_library": bool(ready) if not own.is_file()
        else same_bytes(own, in_library),
        "kind": package_kind(review),
        "tasks": tasks_fresh(snapshot),
        "tasks_stale": snapshot is not None and not tasks_fresh(snapshot),
        "draft": (review / DRAFT).is_file(),
        "package": confirmed_package(review),
        "sent": applied,
        "published": applied and receipt.get("exit_code") == client.EXIT_OK,
        # Публиковать было НЕКУДА — не «не удалось». Отдельный признак, а не
        # `published: true`, потому что итога в группе нет и говорить обратное
        # нельзя; и не `published: false`, потому что доделывать нечего.
        "publish_off": applied and receipt.get("exit_code") == client.EXIT_NO_PUBLISH,
        "receipt": receipt,
    }


def next_step(st: dict) -> tuple:
    """(ключ шага, что сделать словами). Порядок шагов задан ЗДЕСЬ и больше нигде."""
    card = st.get("meeting") or {}
    if not st["transcript"] and st["library_candidates"]:
        # В Библиотеке за этот день лежит чужой текст (или несколько), а встреча
        # не названа. Годится ли он — решает карточка, и только она: Библиотека
        # общая, и текст «за сегодня» бывает планёркой другого отдела.
        return "choose", (f"В Библиотеке за этот день лежат расшифровки "
                          f"({len(st['library_candidates'])}): "
                          + "; ".join(st["library_candidates"])
                          + ". Про эту ли они встречу, скрипт не решает — назови встречу: "
                          f"meeting.py meetings --date {st['date']} покажет встречи дня, "
                          "meeting.py meetings --pick <номер встречи> запишет карточку. "
                          "После неё спроси status снова: текст найдётся по названию "
                          "встречи, а не найдётся — разбор пойдёт к записи и расшифровке. "
                          "Этой встречи в Oblako нет вовсе (разовый созвон) — тогда "
                          "расшифровывай запись сам: meeting.py transcribe --force")
    if not st["transcript"] and not st["audio"]:
        hint = ("Ни готового текста в Библиотеке, ни записи. Сначала обнови Библиотеку "
                "(library.py pull) и спроси status снова")
        if card.get("automaton") == "reported":
            hint += " — автомат этой встречи отчитался «готово», текст должен быть там"
        hint += ". Текста нет — возьми запись: из облака Zoom "
        hint += (f"(zoom_pull.py --meeting {card['zoom_uuid']}) " if card.get("zoom_uuid")
                 else "(zoom_pull.py --date <ДД.ММ.ГГ>) ")
        hint += "или положи файл в папку разбора — и запусти find."
        return "recording", hint
    if not st["transcript"]:
        return "transcribe", "Расшифровать запись: meeting.py transcribe"
    if not st["tasks"]:
        return "tasks", "Свежая выгрузка с боевого сервера: meeting.py tasks"
    if not st["draft"] and not st["package"]:
        return "extract", (f"Извлечь задачи из расшифровки ({st['transcript_file']}) и "
                           f"записать разбор в {DRAFT}. Это работа агента, скриптом её "
                           "не сделать.")
    if not st["package"]:
        return "confirm", ('Показать превью (meeting.py preview) и ждать слова человека. '
                           'Сказал «запиши» — meeting.py confirm --word "<его слова>"')
    if not st["sent"]:
        return "send", "Отправить пакет на сервер: meeting.py send --team <отдел>"
    if not st["publish_off"] and not st["published"]:
        return "publish", ("Итог в группе неполон — досдать: "
                           "meeting.py publish --team <отдел>")
    finished = ("Разбор закончен: задачи применены, публиковать итог было некуда — у "
                "отдела нет группового чата." if st["publish_off"]
                else "Разбор доведён до публикации.")
    # Транскрипт, сделанный здесь, — в Библиотеку (Р3). Планёрка отдела и совет
    # — всегда, это шаг разбора; 1:1 и разовая — по решению организатора (Р16),
    # и разбор без этого закончен. Взятый ИЗ Библиотеки текст класть некуда.
    if st["library"] and st["transcript_here"] and not st["transcript_in_library"]:
        put = ('library.py put --repo <имя> --kind transcript --date <ГГГГ-ММ-ДД> '
               '--title "<название встречи>" [--team "<Отдел>"] --word "<слово человека>" '
               f'--file "{st["transcript_file"]}", затем library.py push')
        if st["kind"] == "планёрка":
            return "library", f"{finished} Осталось положить транскрипт в Библиотеку: {put}"
        return "done", (f"{finished} Транскрипт в Библиотеку — по решению организатора: "
                        f"спроси его; скажет «запиши» — {put}. Иначе делать нечего.")
    return "done", f"{finished} Делать нечего."


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
    card = st["meeting"]
    if card:
        print(f"  ✔ встреча       #{card['id']} «{card['title']}» {card['start_time'] or ''} · "
              f"{card['team'] or 'совет / без отдела'} · автомат: {card['automaton'] or 'не было'}")
    print(f"  {done[bool(st['audio'] or st['transcript'])]} запись        "
          f"{st['audio'] or ('уже расшифрована' if st['transcript'] else 'не найдена')}")
    if st["transcript_here"] or not st["transcript"]:
        print(f"  {done[st['transcript']]} расшифровка   {TRANSCRIPT}")
    else:
        print(f"  ✔ расшифровка   в Библиотеке: {st['transcript_file']}")
    print(f"  {done[st['tasks']]} выгрузка      "
          f"{'снимок не сегодняшний — нужен свежий' if st['tasks_stale'] else TASKS}")
    print(f"  {done[st['draft'] or st['package']]} разбор        "
          f"{PACKAGE if st['package'] else DRAFT}")
    print(f"  {done[st['package']]} «запиши»      {PACKAGE}")
    print(f"  {done[st['sent']]} отправлено")
    print(f"  {'—' if st['publish_off'] else done[st['published']]} итог в группе"
          f"{'  публиковать некуда — так и сдавали' if st['publish_off'] else ''}")
    if st["library"] and st["transcript_here"]:
        print(f"  {done[st['transcript_in_library']]} транскрипт в Библиотеке"
              f"{'' if st['transcript_in_library'] else '  свой, ещё не положен'}")
    print(f"\nДальше: {what}")
    return client.EXIT_OK


def cmd_meetings(args, env: dict) -> int:
    """Встречи дня (или окна) с сервера — и карточка выбранной в папку разбора.

    Нужна команде «разбери встречу с <кем> <когда>»: встречу находит не память
    агента и не догадка по названию папки, а сервер — по ключу, и только те, что
    человек вправе видеть. Ходит через `oblako_client.meetings`, как автомат:
    второй дороги к серверу у пакета нет. Формат и версия сверяются ДО показа.

    `--pick` кладёт карточку выбранной встречи в `Встреча.json`: по ней `status`
    находит транскрипт в Библиотеке по названию, а подсказка «записи нет» знает
    uuid облачной записи. Выбирает агент вместе с человеком, а не скрипт: у
    сервера нет участников в карточке, и «встреча с Дашей» узнаётся по названию
    и организатору.
    """
    since = meeting_date(getattr(args, "date", None))
    until = meeting_date(args.to) if args.to else since
    if until < since:
        raise client.Usage(f"Окно перевёрнуто: --to {args.to} раньше --date {since.strftime(DATE_FMT)}")
    url, key = client.base_url(env), client.access_key(env)
    if args.pick:
        answer = client.meeting(args.pick, url=url, key=key)
        client.check_meetings(answer)
        one = answer.get("meeting") or {}
        # Папка — по ДАТЕ ВСТРЕЧИ из карточки, а не по `--date` запроса: окно
        # могло быть за неделю, а разбор живёт в папке своего дня.
        review = folder_for(args)
        if not getattr(args, "folder", None) and one.get("date"):
            try:
                day = datetime.strptime(str(one["date"]), library.ISO_DATE).date()
                review = repo_root() / REVIEWS_DIR / day.strftime(DATE_FMT)
            except ValueError:
                pass
        review.mkdir(parents=True, exist_ok=True)
        (review / MEETING).write_text(json.dumps(one, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        print(f"Встреча #{one.get('id')} «{one.get('title')}» {one.get('date')} "
              f"{one.get('start_time') or ''} — карточка записана: {review / MEETING}")
        print("Дальше: library.py pull, затем meeting.py status")
        return client.EXIT_OK
    answer = client.meetings(url=url, key=key, date_from=since.strftime(library.ISO_DATE),
                             date_to=until.strftime(library.ISO_DATE))
    client.check_meetings(answer)
    found = answer.get("meetings") or []
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
        return client.EXIT_OK
    window = since.strftime(DATE_FMT) + (f" — {until.strftime(DATE_FMT)}" if until != since else "")
    print(f"Встречи {window} (видит {answer.get('actor', {}).get('name', '?')}):")
    if not found:
        print("  ни одной — в Oblako за это окно встреч нет")
    for one in found:
        job = one.get("job") or {}
        print(f"  #{one.get('id')}  {one.get('date')} {one.get('start_time') or '--:--'}  "
              f"«{one.get('title')}»  организатор: {(one.get('organizer') or {}).get('name', '?')}"
              f"  отдел: {(one.get('team') or {}).get('name') or '—'}"
              f"  автомат: {job.get('status') or 'не было'}"
              f"{'  запись Zoom: ' + job['zoom_uuid'] if job.get('zoom_uuid') else ''}"
              f"{'  ОТМЕНЕНА' if one.get('status') == 'cancelled' else ''}")
    print("Дальше: meeting.py meetings --pick <номер> — карточка нужной встречи в папку разбора")
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
        # Имена есть почти всегда — их прячет не отсутствие, а место. Пока
        # подсказка звала только в облачные записи, локальная планёрка (обычный
        # режим) выглядела «без источника», и агент восстанавливал восьмерых
        # говорящих по обращениям в тексте — полчаса ручной работы (#278).
        print(f"  Имена есть у САМОЙ ВСТРЕЧИ Zoom, даже когда записи в облаке нет: спроси "
              f"коннектор `search_meetings` за эту дату, возьми UUID нужной встречи, вызови "
              f"`get_meeting_assets` и сохрани ответ целиком в {review / CLOUD_NAMES}.")
        print("  Второй источник — transcript.txt/.vtt рядом с записью, если Zoom его положил.")
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
    # Готовый текст в Библиотеке — тот же сделанный шаг: Deepgram за него не
    # платим. `--force` — осознанное «расшифруй заново, не глядя на Библиотеку».
    if not args.force and not args.out:
        card = meeting_card(review)
        ready, seen = library_transcripts(when, env, card)
        if ready is not None:
            print(f"[Пропуск] расшифровка уже в Библиотеке: {ready}")
            print("  читай её — Deepgram не нужен; заново с записи — только с --force")
            return client.EXIT_OK
        # Отказ — только когда выбирать И ПРАВДА НЕ ИЗ ЧЕГО: встреча не названа.
        # С карточкой чужие тексты дня не мешают — они про другие встречи, и
        # расшифровка этой идёт своим ходом, без `--force`.
        # Карточка есть, а текста под её названием нет — расшифровка пойдёт, и
        # это правильно: файлы дня обычно про ДРУГИЕ встречи. Но молчать нельзя:
        # тот же вид у переименованной встречи, чей текст уже оплачен и лежит
        # рядом под прежним именем. Отказом здесь ответить нельзя (он запер бы
        # штатный путь), а показать — обязаны.
        if seen and card and not library_choice(seen, card):
            print(f"[Внимание] в Библиотеке за {when.strftime(DATE_FMT)} уже лежат "
                  f"расшифровки, но ни одна не названа как эта встреча "
                  f"(«{avtomat.title_of(card)}»):")
            for item in seen:
                print(f"  · {item}")
            print("  Так бывает, когда встречу переименовали после расшифровки. Если нужный "
                  "текст среди них — останови расшифровку (Deepgram платный) и положи файл "
                  f"в {review / TRANSCRIPT}.")
        if library_choice(seen, card):
            raise client.Usage(
                f"В Библиотеке за {when.strftime(DATE_FMT)} лежат расшифровки, а про эту "
                "ли они встречу — скрипт не решает",
                [str(item) for item in seen] +
                ["назови встречу: meeting.py meetings --pick <номер> — и повтори",
                 # Второй выход называется ТЕМ ЖЕ СЛОВОМ, что и в подсказке шага
                 # `choose`: без карточки повтор этой же команды даёт тот же
                 # отказ, и «она расшифрует сама» здесь буквально неверно. Кому
                 # выход нужен — разовому созвону, которого в Oblako нет вовсе:
                 # карточку ему взять неоткуда, `meetings --pick` не поможет.
                 "нужной среди них нет (разового созвона в Oblako нет вовсе) — "
                 "расшифруй запись сам: meeting.py transcribe --force"])

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
    """id → человек СОСТАВА отдела (с задачами). Круг close/edit и только он."""
    return {person.get("id"): person for person in (snapshot.get("people") or [])}


def _recipients_index(snapshot: dict) -> dict:
    """id → человек из справочника получателей: вся компания, задач нет (#467).

    Второй круг рядом с первым, потому что кругов у разбора ДВА и они разные:
    новую задачу он ставит любому активному сотруднику, а закрывает и правит —
    только у состава своего отдела. Держать один индекс на оба вопроса нельзя:
    слитый круг либо разрешил бы закрыть чужую задачу, либо не дал бы поставить
    задачу коллеге из другого отдела.
    """
    return {person.get("id"): person for person in (snapshot.get("recipients") or [])}


def _person_label(person: dict, outsider: bool, ambiguous: bool = False) -> str:
    """Имя человека для превью; у коллеги со стороны — с его отделом.

    «Ольга — HR» показывает руководителю, кому именно уедет задача: двух Ольг в
    компании он различает отделом, а не наугад. Своим отдел не приписывается —
    он и так один и назван в шапке разбора.

    ``ambiguous`` — это имя в компании носят двое: тогда к нему приписывается
    `id`, потому что отдел различает не всех (тёзки бывают и в одном), а своим
    отдела не пишут вовсе. Номер некрасив и потому ставится ТОЛЬКО тёзкам:
    руководителю он нужен там, где имени не хватает, и мешал бы везде, где
    хватает.
    """
    name = person.get("name") or f"id={person.get('id')}"
    if ambiguous:
        name = f"{name} (id={person.get('id')})"
    if not outsider:
        return name
    teams = ", ".join(team.get("name", "") for team in (person.get("teams") or [])
                      if team.get("name"))
    return f"{name} — {teams}" if teams else f"{name} — без отдела"


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

    Сверяется то, на что есть местный ответ: тот ли человек, из своего ли он
    отдела и та ли задача. Чему местного ответа нет — здесь не судится (шапка
    файла, «Судья пакета — сервер»).

    КРУГА ДВА, И ОНИ РАЗНЫЕ (#467): новую задачу разбор ставит любому активному
    сотруднику компании (справочник получателей), а закрывает и правит только у
    состава своего отдела (снимок с задачами). Сверка повторяет здесь ровно эту
    развилку — и повторяет намеренно, теми же словами, что скажет сервер: узнать
    об отказе на превью можно до слова «запиши», а на отправке — уже после того,
    как руководитель поверил, что разбор сдан.

    ТЁЗКИ РАЗЛИЧАЮТСЯ НОМЕРОМ (#467, решение 4). Разбор опознаёт людей по имени,
    сказанному вслух, и двух Ольг в компании отличить на слух нечем: отдел
    спасает не всегда — тёзки бывают и в одном. Имя, которое носят двое, здесь
    печатается с `id`, потому что превью — единственное место, где руководитель
    видит выбор ДО слова «запиши». Заодно это чинит и группировку: блоки
    складываются по показанному имени, и голые тёзки слились бы в один блок,
    показав задачи двух людей как задачи одного.
    """
    people = _people_index(snapshot)
    listed = _recipients_index(snapshot)
    # Снимок, снятый до #467, справочника не несёт вовсе. Молчаливое «человека
    # нет» увело бы руководителя чинить черновик вместо того, чтобы обновить
    # снимок, — поэтому причина называется своей фразой.
    stale = "recipients" not in snapshot
    # Тёзки — по ОБОИМ кругам разом и по людям, а не по строкам: состав отдела
    # лежит и в справочнике, и совпадение человека с самим собой тёзкой не
    # делает. Считается один раз на весь пакет: имя неоднозначно в компании, а
    # не в пункте.
    known = {**listed, **people}
    namesakes = {name for name, count in Counter(
        person.get("name") for person in known.values()).items() if name and count > 1}
    by_person: dict = {}
    problems: list = []
    for number, item in enumerate(package.get("items") or [], start=1):
        op = str(item.get("op", "?"))
        person_id = item.get("person_id")
        person = people.get(person_id)
        outsider = person is None
        if outsider:
            person = listed.get(person_id)
        if person is None:
            problems.append(
                f"пункт {number}: человека id={person_id} нет в снимке"
                + (" — снимок снят без справочника получателей (старый сервер "
                   "или старая выгрузка): сделай выгрузку заново"
                   if stale else
                   " и нет в справочнике компании — пакет будет отвергнут целиком"))
        elif outsider and op != "add":
            problems.append(f"пункт {number}: «{person.get('name')}» не из отдела разбора — "
                            f"закрыть или изменить его задачу можно только на его планёрке")
        # Сравнение с None, а не на истинность: сервер судит `due` тем же
        # `is not None`, и пустая строка обязана отвергнуться ЗДЕСЬ, а не после
        # слова «запиши».
        elif outsider and item.get("due") is not None:
            problems.append(f"пункт {number}: «{person.get('name')}» не из отдела разбора — "
                            f"поставить ему можно дедлайн (deadline), а рабочим днём "
                            f"(due) распоряжается он сам")
        elif not outsider and op in ("close", "edit"):
            task = _task_index(person).get(item.get("task_id"))
            if task is None:
                problems.append(f"пункт {number}: у «{person.get('name')}» нет открытой "
                                f"задачи id={item.get('task_id')}")
            elif (task.get("text") or "").strip() != (item.get("task_text") or "").strip():
                problems.append(f"пункт {number}: текст задачи id={item.get('task_id')} "
                                f"разошёлся со снимком — в снимке «{task.get('text')}»")
        name = (_person_label(person, outsider, person.get("name") in namesakes)
                if person is not None else f"id={person_id}")
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


def cmd_confirm(args, env: dict) -> int:
    review = folder_for(args)
    draft, package = review / DRAFT, review / PACKAGE
    client.confirmed_by(args.word)
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
        if code == client.EXIT_NO_PUBLISH:
            print("Итог в группу не публиковали — доделывать нечего.")
        return code

    # Та же сверка, что на превью, — вторым разом перед самой отправкой (#467).
    # Превью показывают руководителю, а отправку зовут потом, и между ними
    # черновик успевают переписать: пункт чужому с рабочим днём, закрытие чужой
    # задачи или человек, которого в компании нет, уехали бы на сервер и вернулись
    # отказом всего пакета. Причины называются здесь теми же словами, что скажет
    # сервер. Снимка нет — сверять нечем, и это не повод не отправлять: судит
    # всё равно сервер.
    snapshot = read_json(review / TASKS)
    if snapshot is not None:
        _, problems = preview_lines(read_json(package) or {}, snapshot)
        if problems:
            raise client.Usage(
                "Пакет разошёлся со снимком — сервер отвергнет его целиком:\n  · "
                + "\n  · ".join(problems),
                ["поправь черновик, покажи превью и подтверди заново",
                 "устарел снимок — сделай выгрузку: meeting.py tasks"])

    argv = ["--package", str(package), "--team", team]
    if args.dry_run:
        argv.append("--dry-run")
    # Просьба «не публиковать» едет клиенту дословно: у отдела может не быть
    # группы по решению руководителя, и догадаться об этом ни один из двух
    # клиентов не вправе (тикет #280).
    if args.no_publish:
        argv.append("--no-publish")
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
    "status": cmd_status, "meetings": cmd_meetings, "find": cmd_find,
    "transcribe": cmd_transcribe, "tasks": cmd_tasks, "preview": cmd_preview,
    "confirm": cmd_confirm, "send": cmd_send, "publish": cmd_publish,
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

    meetings = common("meetings", "встречи дня с сервера; --pick кладёт карточку выбранной")
    meetings.add_argument("--to", help="конец окна ДД.ММ.ГГ (без него — один день --date)")
    meetings.add_argument("--pick", type=int, metavar="НОМЕР",
                          help=f"записать карточку этой встречи в {MEETING} папки разбора")
    meetings.add_argument("--json", action="store_true", help="машинный вид для агента")

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
    send.add_argument("--no-publish", action="store_true", dest="no_publish",
                      help="не публиковать итог в группу (у отдела нет группового чата)")

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

# -*- coding: utf-8 -*-
"""avtomat.py — весь путь автомата одним скриптом (#455).

ЗАЧЕМ ОН ЕСТЬ. Расшифровку записанной планёрки делает не сервер, а личная рутина
человека — Claude Code в облаке, на его подписке и с его ключами (инвариант
«Автоматы»). Рутина — это модель, читающая инструкцию, и если расписать ей
порядок шагов словами, каждый запуск пройдёт чуть по-своему: сегодня склейка с
именами, завтра без; сегодня транскрипт в папку отдела, завтра в корень совета.
Здесь порядок задан КОДОМ, ровно как порядок разбора планёрки задан
`meeting.py`. За рутиной остаётся ОДНО ДЕЙСТВИЕ — запустить эту команду:

    python avtomat.py run --job <номер задания>

Отказ скрипта одинаков всегда, а инструкцию модель однажды прочитает иначе.

ЧТО ДЕЛАЕТ `run`, по шагам:

    1. спрашивает сервер, что за задание (`GET /api/pc/meetings?awaiting=1`):
       какая встреча, какой экземпляр записи в Zoom, чей отдел, ждать ли имена;
    2. забирает из облака Zoom звук и транскрипт Zoom рядом с ним
       (`zoom_pull.py --meeting <uuid>`); uuid нет — ищет по номеру комнаты и
       сверяет, ТА ЛИ ЭТО ЗАПИСЬ (`same_meeting`): по номеру Zoom отдаёт
       последнюю запись комнаты, а у серии номер один на все дни;
    3. расшифровывает Deepgram и сшивает имена (`zoom_deepgram_merge.py`);
       транскрипта Zoom не оказалось — расшифровка идёт БЕЗ имён и уезжает с
       пометкой «имена не сшиты», а не откладывается;
    4. кладёт текст в Библиотеку и отправляет его
       (`library.py put --kind transcript --as-automaton "<Имя>"`, затем `push`);
    5. ОТЧИТЫВАЕТСЯ СЕРВЕРУ ПРИ ЛЮБОМ ИСХОДЕ (`POST /api/pc/transcripts/<id>`).

ОТЧЁТ УХОДИТ ВСЕГДА — И ЭТО ГЛАВНОЕ СВОЙСТВО СКРИПТА. Задание, о котором никто
не отчитался, висит у сервера в полёте, человек два часа ждёт письма «готово», а
потом получает «расшифровка не пришла» — и не знает, чинить ли ему что-нибудь.
Поэтому любая беда — своя, чужая или поломка самого скрипта — превращается в
отчёт «не вышло» с короткой причиной, а «записи ещё нет» отчитывается отдельным
исходом: по нему сервер вернёт задание в очередь и попробует позже.

ТЕКСТ ВСТРЕЧИ НА СЕРВЕР НЕ ЕДЕТ (инвариант 22). В отчёте только путь в
Библиотеке, отпечаток, минуты, число говорящих и КОРОТКОЕ СЛОВО причины
(`REPORT_CODES`) — ни расшифровки, ни местных путей, ни трассировок. Подробность
беды человек читает в журнале запуска рутины, а не в базе сервера. Последний
рубеж от длинной строки — `oblako_client.transcripts`.

`awaiting` — вечерний добор: список встреч, у которых задание ещё живо. Сигнал в
облако мог не дойти, запуск мог упасть на середине, запись могла дописываться
дольше двух часов — и вечерний проход рутины подбирает всё это одной командой.

ОТКУДА КЛЮЧИ. Из `.env` рядом со скриптами, а поверх него — из переменных
окружения: в облачной машине рутины файла нет вовсе, и ключи задаёт ей человек
один раз (см. `settings`). То же правило, что у сервера и у забора записи.

СЕКРЕТЫ НЕ ПОКАЗЫВАЮТСЯ. Через скрипт проходят четыре чужих ключа (Oblako, Zoom,
Deepgram, токен адреса Библиотеки), и вывод соседних скриптов он печатает не
как есть, а через `clean`: журнал запуска рутины живёт в облаке claude.ai и
читается не только владельцем. На сервер чужой текст не уезжает вовсе: в поле
`error` едет короткое слово из закрытого списка, а не строка беды.

КОДЫ ВЫХОДА — те же, что у всего контура ПК (`oblako_client`):

    0  расшифровка в Библиотеке, отчёт принят
    1  расшифровки не вышло (или записи ещё нет) — ОТЧЁТ СЕРВЕРУ УЖЕ УШЁЛ,
       человеку про это скажет сам сервер; повторять запуск бессмысленно
    2  сервер отказал: ключ не принят, чужая встреча, кривой отчёт
    3  до сервера не достучались: сеть, DNS, TLS, таймаут

Команды:

    python avtomat.py run --job 12 [--repo sovet]
    python avtomat.py awaiting [--json]

Зависимостей нет — только стандартная библиотека. Windows, macOS и облако —
один и тот же путь.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from argparse import Namespace
from datetime import datetime
from pathlib import Path

import library
import oblako_client as client
import zoom_deepgram_merge
import zoom_pull

SCRIPT = Path(__file__).resolve()

# --- рабочие файлы ----------------------------------------------------------
# Папка на ЗАДАНИЕ, а не на дату: у серии номер один на все дни, а за день
# бывает несколько встреч, и общая папка `Разборы/<дата>` подсунула бы второму
# заданию готовый «Транскрипт.md» первого — молча и правдоподобно. Номер задания
# различает их всегда, а дата в имени оставлена человеку: он открывает эту папку
# глазами, когда разбирается, что автомат натворил.
REVIEWS_DIR = "Разборы"
TRANSCRIPT = "Транскрипт.md"
DEEPGRAM_RAW = "Deepgram raw.json"      # то же имя, что у разбора: цена ответа одна
DATE_FMT = "%d.%m.%y"
ISO_DATE = "%Y-%m-%d"

# Ключи, которых не должно быть в выводе и в отчёте. Ключ доступа и токены
# адресов Библиотеки знает `library.secrets`; здесь — те, что проходят через
# соседние скрипты.
SECRET_ENVS = ("DEEPGRAM_API_KEY", "ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID",
               "ZOOM_CLIENT_SECRET", "ZOOM_SECRET_TOKEN")

NOT_STITCHED = ("Транскрипта Zoom у записи не было — имена говорящих не сшиты "
                "(в расшифровке «Спикер N»).")

# --- слова причины для отчёта -----------------------------------------------
# ПОЛЕ `error` — КОРОТКОЕ СЛОВО, А НЕ СТРОКА ТЕКСТА, и это правило Библиотеки, а
# не аккуратность: «Даже отчёт автомата (`report`) — JSON БЕЗ ТЕКСТА»
# (`bot/schema.sql`, инвариант 22). Свободная строка несла бы на сервер то, чего
# `clean` не вырезает и вырезать не может: местные пути `C:\Users\<Имя>\…`,
# трассировки Python и куски чужого вывода. База уезжает ежедневным дампом в
# отдельный репозиторий, а читателя у этого поля нет ни одного — ни в боте, ни в
# Mini App. Человеку причину рассказывает сам сервер («расшифруйте на
# компьютере»), а подробности живут в журнале запуска рутины, куда их печатает
# `say`. Образец слова — `bot/automaton.py`, `AutomatonError.code`.
#
# Список ЗАКРЫТЫЙ: незнакомое слово сервер сегодня стерпит, но разбирать причины
# по неповторяющимся строкам нельзя — их некому будет сосчитать.
NO_RECORDING = "zoom_not_yet"        # записи ещё нет: Zoom ответил 404
OTHER_INSTANCE = "zoom_other_uuid"   # облако отдало не тот экземпляр записи
OTHER_DAY = "zoom_other_day"         # запись другого дня (искали по номеру комнаты)
ZOOM_REFUSED = "zoom_refused"        # ключ, права, 429 — чинит человек
ZOOM_SILENT = "zoom_silent"          # облако не ответило
ZOOM_BROKEN = "zoom_broken"          # своя беда забора: нет ключа, кривой ответ
NO_ZOOM_REF = "no_zoom_ref"          # у задания нет ни uuid, ни номера комнаты
BAD_DATE = "bad_meeting_date"        # сервер назвал дату, которую не разобрать
DEEPGRAM = "deepgram"                # расшифровка не вышла
NO_REPO = "library_no_repo"          # не выбрать репозиторий Библиотеки
LIBRARY_PUT = "library_refused"      # Библиотека не приняла запись
LIBRARY_PUSH = "library_not_pushed"  # записано, но не отправлено
CRASH = "crash"                      # поломка самого скрипта

REPORT_CODES = (NO_RECORDING, OTHER_INSTANCE, OTHER_DAY, ZOOM_REFUSED, ZOOM_SILENT,
                ZOOM_BROKEN, NO_ZOOM_REF, BAD_DATE, DEEPGRAM, NO_REPO, LIBRARY_PUT,
                LIBRARY_PUSH, CRASH,
                # своя беда соседнего скрипта — именем беды клиента:
                "usage", "refused", "unreachable")


class Stop(Exception):
    """Работа не вышла, и об этом надо ОТЧИТАТЬСЯ, а не промолчать.

    Исход несётся вместе с причиной: «записи ещё нет» сервер вернёт в очередь и
    попробует снова, «не вышло» — закроет задание и позовёт человека. Разница
    между ними стоит человеку либо лишнего часа ожидания, либо потерянной
    расшифровки, поэтому она названа в каждом месте, где работа обрывается.

    Причин у беды ДВЕ, и они для разных читателей: `message` — человеку в журнал
    запуска рутины, целиком и по-русски; `code` — серверу в поле `error`, одним
    коротким словом из `REPORT_CODES`. Текста встречи, местных путей и трассировок
    на сервер не уезжает (инвариант 22).
    """

    def __init__(self, outcome: str, message: str, code: str):
        super().__init__(message)
        self.outcome = outcome
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# Печать: ни одного ключа
# ---------------------------------------------------------------------------
def secrets(env: dict) -> list:
    """Всё, чего не должно быть ни в выводе, ни в отчёте серверу."""
    found = list(library.secrets(env))          # ключ доступа и токены адресов
    for name in SECRET_ENVS:
        value = (env.get(name) or "").strip()
        if value:
            found.append(value)
    return found


def clean(text, env: dict) -> str:
    """Последний рубеж: вырезать ключи и логин с паролем из адресов.

    Соседние скрипты печатают своё сами и чистят каждый своё; сюда их вывод
    приходит перехваченным, и правило у него одно — это.
    """
    return library.URL_CREDENTIALS.sub("<токен скрыт>",
                                       client.redact(str(text), secrets(env)))


def say(text, env: dict, stream=None) -> None:
    print(clean(text, env), file=stream or sys.stdout)


def settings() -> dict:
    """Настройки автомата — общим чтением пакета (`oblako_client.settings`).

    Правило («`.env` рядом со скриптами, а поверх него окружение») там и живёт,
    и оно здесь не удобство, а условие работы: в облачной машине рутины `.env`
    НЕТ ВОВСЕ — ключи Zoom, Deepgram, доступа к серверу и адреса Библиотеки
    приезжают туда переменными окружения, которые человек задал рутине один раз.
    На компьютере человека файл на месте и работает как прежде. Соседним
    скриптам эти настройки не передаются: каждый читает то же самое сам.
    """
    return client.settings(SCRIPT)


def run_script(module, argv: list, env: dict) -> tuple:
    """Позвать соседний скрипт и напечатать его вывод ОЧИЩЕННЫМ.

    Перехват нужен не ради красоты: `zoom_pull.py` отдаёт машинный ответ в
    stdout (иначе его не прочитать), а вывод любого из соседей может нести чужой
    текст — ответ Zoom, сообщение git. В облаке этот вывод оседает в журнале
    запуска рутины, поэтому через `clean` проходит ВЕСЬ, а не выборочно.

    Настройки соседу не передаются: он читает их сам тем же общим чтением
    (`oblako_client.settings`), и в облаке без `.env` получает ровно то же
    окружение. `env` здесь нужен только для чистки вывода от ключей.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(list(argv))
    if out.getvalue().strip():
        say(out.getvalue().rstrip(), env)
    if err.getvalue().strip():
        say(err.getvalue().rstrip(), env, stream=sys.stderr)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Задание: что сказал сервер
# ---------------------------------------------------------------------------
def awaiting_jobs(url: str, key: str) -> tuple:
    """Хозяин ключа и встречи с живым заданием — парами «встреча, задание».

    Хозяин приезжает шапкой ответа, а не настройками машины: его именем
    подписывается коммит автомата, и спрашивать «а чей я?» у чужого компьютера
    для этого нельзя.
    """
    answer = client.meetings(url=url, key=key, awaiting=True)
    client.check_meetings(answer)
    found = []
    for one in answer.get("meetings") or []:
        job = one.get("job")
        if job:
            found.append((one, job))
    return answer.get("actor") or {}, found


def job_of(found: list, job_id: int) -> tuple:
    """Пара «встреча, задание» по номеру задания — или отказ с объяснением.

    Задания нет среди живых по трём причинам, и все три означают одно: делать
    нечего. Оно уже закрыто (отчёт дошёл, а ответ потерялся), оно чужое, или
    номер назван неверно. Отчитываться в этом случае НЕ О ЧЕМ и некуда: чужое
    задание сервер и не примет.
    """
    for one, job in found:
        if job.get("id") == job_id:
            return one, job
    raise client.Usage(
        f"Задания {job_id} среди ждущих расшифровки нет — делать нечего.",
        ["оно уже закрыто (отчёт дошёл), не твоё или номер назван неверно",
         "что осталось, показывает: python avtomat.py awaiting"])


def title_of(one: dict) -> str:
    """Название встречи, годное для имени файла. Правило — `library.clean_name`.

    Своей чистки здесь нет намеренно: под этим именем файл ЛОЖИТСЯ в Библиотеку
    (`library.py put --title`), под ним же его ИЩЕТ разбор (`meeting.py`), и три
    копии одного правила разъехались бы молча — на скобке, на двоеточии или на
    двух пробелах подряд. Цена расхождения — оплаченный второй раз Deepgram.
    """
    return library.clean_name(one.get("title"))


def day_of(one: dict):
    """Дата встречи из ответа сервера (ISO) — ею подписан файл в Библиотеке."""
    try:
        return datetime.strptime(str(one.get("date") or ""), ISO_DATE).date()
    except ValueError:
        raise Stop(client.TRANSCRIPT_FAILED,
                   f"Сервер назвал дату встречи, которую не разобрать: "
                   f"{one.get('date')!r}", BAD_DATE) from None


def work_folder(job: dict, one: dict) -> Path:
    """Папка задания: `Разборы/<ДД.ММ.ГГ> задание <номер>/` в корне работы."""
    when = day_of(one).strftime(DATE_FMT)
    folder = client.work_root(SCRIPT) / REVIEWS_DIR / f"{when} задание {job['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Шаг 1: запись из облака Zoom
# ---------------------------------------------------------------------------
def same_meeting(got: dict, job: dict, one: dict) -> None:
    """Та ли это запись. Чужую в Библиотеку класть НЕЛЬЗЯ, лучше вернуться позже.

    ЗАЧЕМ ПРОВЕРКА. У задания, поставленного расписанием (а не событием Zoom),
    uuid экземпляра нет, и запись ищется по НОМЕРУ КОМНАТЫ. У серии номер один
    на все дни, и Zoom по нему отдаёт то, что считает последней записью этой
    комнаты, — то есть ПРОШЛУЮ планёрку, пока сегодняшняя ещё дописывается.
    Без сверки её текст лёг бы в Библиотеку под сегодняшней датой и названием,
    организатор получил бы «расшифровка готова», а разбор («сначала Библиотека»)
    принял бы прошлую неделю за сегодняшний разговор — молча и правдоподобно.

    ЧТО СУДИТСЯ. Есть uuid — судит он: экземпляр назван точно, и сверять сверх
    него дату не только лишнее, но и вредно (встречу, начатую после полуночи,
    сверка по дню отвергла бы вместе с её настоящей записью). Uuid нет — судит
    дата: другого признака у номера комнаты не остаётся.

    ЧЕМ ОТЧИТЫВАЕМСЯ. `no_recording`, а не `failed`: сегодняшней записи в облаке
    и правда ещё нет — Zoom дописывает её не сразу. Сервер вернёт задание в
    очередь и попробует снова, и это ровно то, что нужно.
    """
    said = got.get("meeting") if isinstance(got.get("meeting"), dict) else {}
    wanted = (job.get("zoom_uuid") or "").strip()
    theirs = str(said.get("uuid") or "").strip()
    if wanted and theirs:
        if theirs == wanted:
            return
        raise Stop(client.TRANSCRIPT_NO_RECORDING,
                   "Zoom отдал не тот экземпляр записи, который назвало задание — "
                   "записи этой встречи в облаке ещё нет.", OTHER_INSTANCE)
    when = day_of(one)
    stamp = str(said.get("date") or "").strip()
    try:
        theirs_day = datetime.strptime(stamp, DATE_FMT).date()
    except ValueError:
        theirs_day = None
    if theirs_day != when:
        raise Stop(client.TRANSCRIPT_NO_RECORDING,
                   f"В облаке лежит запись за {stamp or 'неназванный день'}, а встреча "
                   f"была {when.strftime(DATE_FMT)}: записи этого дня ещё нет. Искали по "
                   f"номеру комнаты — у серии он один на все дни, и Zoom отдаёт по нему "
                   f"последнюю запись комнаты.", OTHER_DAY)


def recording(job: dict, one: dict, env: dict) -> dict:
    """Звук и транскрипт Zoom этого экземпляра встречи.

    По uuid — тот самый день серии; uuid нет (задание поставлено по расписанию, а
    не по событию Zoom) — по номеру комнаты, и Zoom отдаёт последнюю запись этой
    встречи.

    КОДЫ `zoom_pull` РАЗЛОЖЕНЫ ПО ИСХОДАМ ОТЧЁТА, И ГЛАВНАЯ РАЗВИЛКА ЗДЕСЬ ОДНА:
    «записи ещё нет» (6) — это `no_recording`, то есть «вернись позже»; ЛЮБОЙ
    другой отказ Zoom (2 — мёртвый ключ, отозванные права, 429, переброс за
    пределы Zoom), молчание сети (3) и своя беда скрипта (1) — `failed`. Пока
    сюда приходил один код 2 на все отказы, сервер по нему возвращал задание в
    очередь до одиннадцати раз подряд, а человеку в конце говорил «записи встречи
    не было» — про встречу, запись которой лежала в облаке целой и не забиралась
    из-за ключа. Ожидание не лечит ни один из этих отказов; лечит человек, и
    позвать его надо сразу.
    """
    ref = job.get("zoom_uuid") or job.get("zoom_call_id")
    if not ref:
        raise Stop(client.TRANSCRIPT_FAILED,
                   "У задания нет ни uuid записи, ни номера комнаты Zoom — "
                   "искать запись нечем.", NO_ZOOM_REF)
    code, out, err = run_script(zoom_pull, ["--meeting", str(ref), "--json"], env)
    if code == zoom_pull.OK:
        try:
            got = json.loads(out)
        except ValueError:
            raise Stop(client.TRANSCRIPT_FAILED,
                       "Zoom-скрипт ответил не машинным видом — разобрать нечего.",
                       ZOOM_BROKEN) from None
        # Сверка стоит ДО расшифровки: скачанный не тот файл стоит трафика, а
        # расшифрованный — денег Deepgram и чужого текста в Библиотеке.
        same_meeting(got, job, one)
        return got
    # ПЕРВАЯ строка вывода, а не последняя: беду скрипты называют сразу, а
    # дальше идёт лечение на три строки — в отчёт из него уехал бы хвост совета.
    lines = [line for line in (out + err).splitlines() if line.strip()]
    said = clean(lines[0] if lines else "причина не названа", env)
    if code == zoom_pull.NO_RECORDING:
        raise Stop(client.TRANSCRIPT_NO_RECORDING,
                   f"Записи в облаке Zoom ещё нет: {said}", NO_RECORDING)
    if code == zoom_pull.REFUSED:
        raise Stop(client.TRANSCRIPT_FAILED, f"Zoom отказал: {said}", ZOOM_REFUSED)
    if code == zoom_pull.SILENT:
        raise Stop(client.TRANSCRIPT_FAILED, f"Zoom не ответил: {said}", ZOOM_SILENT)
    raise Stop(client.TRANSCRIPT_FAILED, f"Запись не забрать: {said}", ZOOM_BROKEN)


# ---------------------------------------------------------------------------
# Шаг 2: расшифровка и склейка имён
# ---------------------------------------------------------------------------
def transcribe(got: dict, folder: Path, env: dict) -> Path:
    """Расшифровка Deepgram со сшитыми именами — или без них, но с пометкой.

    Транскрипта Zoom не оказалось — ЭТО НЕ ПОВОД ОТЛОЖИТЬ РАБОТУ: тик автомата
    уже прождал своё, а запись живёт в облаке Zoom около месяца. Текст без имён
    полезнее ненаписанного, и «имена не сшиты» уезжает в отчёт отдельным полем,
    чтобы человек знал, что читает.
    """
    out = folder / TRANSCRIPT
    argv = ["--audio", str(got["audio"]), "--out", str(out),
            "--dg-json", str(folder / DEEPGRAM_RAW)]
    if got.get("transcript"):
        argv += ["--zoom", str(got["transcript"])]
    else:
        say(NOT_STITCHED, env)
    code, _, _ = run_script(zoom_deepgram_merge, argv, env)
    if code != 0 or not out.is_file():
        raise Stop(client.TRANSCRIPT_FAILED,
                   "Расшифровка не вышла — Deepgram не ответил или текст оказался пуст.",
                   DEEPGRAM)
    return out


def measure(folder: Path) -> dict:
    """Минуты и число говорящих — из сохранённого ответа Deepgram.

    Считается по нему, а не по готовому тексту: длительность там названа
    записью, а не пересчитана из таймкодов. Ответа нет (расшифровку взяли
    готовой) — полей в отчёте просто не будет: сервер их не требует, а
    выдуманное число хуже отсутствующего.
    """
    try:
        dg = json.loads((folder / DEEPGRAM_RAW).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    spoken = zoom_deepgram_merge.utts_of(dg)
    duration = float((dg.get("metadata") or {}).get("duration") or 0)
    return {"minutes": int(round(duration / 60)),
            "speakers": len({one[2] for one in spoken})}


# ---------------------------------------------------------------------------
# Шаг 3: Библиотека
# ---------------------------------------------------------------------------
def repo_for(team, env: dict, named=None) -> "library.Repo":
    """Куда писать: репозиторий совета (у задания нет отдела) или отделов.

    Выбор МЕХАНИЧЕСКИЙ и объяснимый: отдел у задания назван — файл лежит внутри
    `Отделы/<Отдел>/` и годится репозиторий отделов; отдела нет — это совет, а
    его документы лежат от корня (`library.ROOT_REPOS`). Подходящих несколько —
    отказ, а не выбор наугад: транскрипт, легший в чужой репозиторий, читается
    как настоящий. Разовое отступление — `--repo`.
    """
    found = library.repos(env)
    if named:
        return library.pick(named, found)
    want_root = not team
    fit = [one for one in found if one.root_level == want_root]
    if len(fit) == 1:
        return fit[0]
    where = "от корня (совет)" if want_root else f"внутри Отделы/{team}"
    raise Stop(client.TRANSCRIPT_FAILED,
               f"Не выбрать репозиторий Библиотеки для записи {where}: подошло "
               f"{len(fit)} из {len(found)}. Назови его: avtomat.py run --repo <имя>.",
               NO_REPO)


def to_library(text: Path, one: dict, job: dict, sign: str, env: dict,
               named=None) -> dict:
    """Записать транскрипт в Библиотеку и отправить его. Путь считает `library.py`.

    ПАПКУ НАЗЫВАЕТ ЗАДАНИЕ, а не отдел серии: её мог выбрать сам человек кнопкой
    в Telegram, и это его решение старше умолчания.

    Отправка обязательна и входит в успех. Коммит без `push` живёт в машине
    рутины, которую облако выключит через минуту, — а отчёт «готово» сказал бы
    человеку, что текст в Библиотеке, и он пошёл бы читать пустое место.
    """
    team = job.get("team")
    repo = repo_for(team, env, named)
    when = day_of(one)
    where = Namespace(team=team, title=title_of(one))
    target, _ = library.place(repo, "transcript", when, where)

    argv = ["put", "--repo", repo.name, "--kind", "transcript",
            "--date", when.strftime(DATE_FMT), "--title", where.title,
            "--file", str(text), "--as-automaton", sign]
    if team:
        argv += ["--team", str(team)]
    code, _, _ = run_script(library, argv, env)
    if code != client.EXIT_OK:
        raise Stop(client.TRANSCRIPT_FAILED,
                   f"Библиотека не приняла транскрипт (код {code}) — см. вывод выше.",
                   LIBRARY_PUT)
    code, _, _ = run_script(library, ["push", "--repo", repo.name], env)
    if code != client.EXIT_OK:
        raise Stop(client.TRANSCRIPT_FAILED,
                   f"Транскрипт записан, но не отправлен в Библиотеку (код {code}): "
                   f"в облаке эта копия не переживёт запуск.", LIBRARY_PUSH)
    return {"repo": repo.name, "path": target, "sha256": client.digest(text)}


# ---------------------------------------------------------------------------
# Команда `run`: весь путь и отчёт при любом исходе
# ---------------------------------------------------------------------------
def do_job(actor: dict, one: dict, job: dict, env: dict, args) -> dict:
    """Работа целиком. Всё, что здесь падает, становится отчётом «не вышло»."""
    folder = work_folder(job, one)
    got = recording(job, one, env)
    text = transcribe(got, folder, env)
    done = to_library(text, one, job, signature(actor, one), env,
                      getattr(args, "repo", None))
    done.update(measure(folder))
    done["outcome"] = client.TRANSCRIPT_DONE
    done["names_stitched"] = bool(got.get("transcript"))
    return done


def signature(actor: dict, one: dict) -> str:
    """Чьим именем подписан коммит: «Автомат: <Имя>» — хозяина ключа.

    Имя приезжает из шапки ответа сервера, а не из настроек машины: в истории
    Библиотеки видно, ЧЕЙ автомат писал, а ключ у автомата личный. Хозяин не
    назвался — подписываемся организатором встречи: пустая подпись превратила бы
    коммит автомата в коммит человека (инвариант 23).
    """
    organizer = one.get("organizer") or {}
    return (str((actor or {}).get("name") or organizer.get("name") or "").strip()
            or "Автомат")


def cmd_run(args, env: dict) -> int:
    """Один запуск автомата: работа и отчёт при ЛЮБОМ её исходе."""
    key = client.access_key(env)
    url = client.base_url(env)
    actor, found = awaiting_jobs(url, key)
    one, job = job_of(found, args.job)
    say(f"Задание {job['id']}: «{title_of(one)}» {one.get('date')} "
        f"{one.get('start_time') or ''}".rstrip(), env)

    # ЧЕЛОВЕКУ — ЦЕЛИКОМ, СЕРВЕРУ — СЛОВО. Подробность беды печатается в журнал
    # запуска рутины (`say`), а в отчёт уходит короткий код из `REPORT_CODES`:
    # свободная строка увезла бы на сервер местные пути и трассировки, а
    # обещано «JSON без текста» (инвариант 22).
    try:
        report = do_job(actor, one, job, env, args)
    except Stop as beda:
        report = {"outcome": beda.outcome, "error": beda.code}
        say(beda.message, env, stream=sys.stderr)
    except client.ClientError as beda:
        # Своя беда соседнего скрипта (нет ключа Zoom, не настроена Библиотека)
        # — это тоже «не вышло»: сервер обязан узнать причину, а не тишину.
        # Слово причины — имя самой беды клиента: `usage`, `refused`, `unreachable`.
        report = {"outcome": client.TRANSCRIPT_FAILED,
                  "error": type(beda).__name__.lower()}
        say(beda.message, env, stream=sys.stderr)
    except Exception as beda:                 # поломка самого скрипта — тоже отчёт
        report = {"outcome": client.TRANSCRIPT_FAILED, "error": CRASH}
        say(f"Поломка скрипта: {type(beda).__name__}: {beda}", env, stream=sys.stderr)

    report["job_id"] = job["id"]
    answer = client.transcripts(one["id"], report, url=url, key=key)
    if report["outcome"] == client.TRANSCRIPT_DONE:
        say(f"Готово: {report['repo']}/{report['path']}", env)
        say(f"Сервер принял отчёт: {answer.get('outcome')}, задание "
            f"{answer.get('status')}.", env)
        return client.EXIT_OK
    say(f"Сервер принял отчёт «{report['outcome']}»: {answer.get('outcome')}, задание "
        f"{answer.get('status')}. Человеку скажет сам сервер.", env)
    return client.EXIT_USAGE


# ---------------------------------------------------------------------------
# Команда `awaiting`: вечерний добор
# ---------------------------------------------------------------------------
def cmd_awaiting(args, env: dict) -> int:
    """Что ещё ждёт расшифровки. Ничего не делает — только называет задания."""
    key = client.access_key(env)
    url = client.base_url(env)
    _, found = awaiting_jobs(url, key)
    rows = [{"job_id": job.get("id"), "meeting_id": one.get("id"),
             "title": one.get("title"), "date": one.get("date"),
             "start_time": one.get("start_time"), "team": job.get("team"),
             "status": job.get("status"), "names_expected": job.get("names_expected")}
            for one, job in found]
    if getattr(args, "as_json", False):
        print(clean(json.dumps({"jobs": rows}, ensure_ascii=False, indent=2), env))
        return client.EXIT_OK
    if not rows:
        say("Расшифровки никто не ждёт — делать нечего.", env)
        return client.EXIT_OK
    say(f"Ждут расшифровки: {len(rows)}", env)
    for row in rows:
        where = f" · {row['team']}" if row["team"] else " · совет"
        say(f"  · задание {row['job_id']} — «{row['title']}» {row['date']} "
            f"{row['start_time'] or ''}{where} ({row['status']})", env)
    say("Каждое: python avtomat.py run --job <номер>", env)
    return client.EXIT_OK


COMMANDS = {"run": cmd_run, "awaiting": cmd_awaiting}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Автомат Oblako: расшифровка записанной встречи в Библиотеку")
    subs = parser.add_subparsers(dest="command", required=True)

    run = subs.add_parser("run", help="весь путь одного задания и отчёт серверу")
    run.add_argument("--job", type=int, required=True, help="номер задания из сигнала")
    run.add_argument("--repo", help="репозиторий Библиотеки, если своего не выбрать")

    waiting = subs.add_parser("awaiting", help="что ещё ждёт расшифровки")
    waiting.add_argument("--json", action="store_true", dest="as_json",
                         help="машинный вид для агента")
    return parser


def main(argv=None) -> int:
    client.setup_console()
    args = _parser().parse_args(argv)
    env = settings()
    try:
        return COMMANDS[args.command](args, env)
    except client.ClientError as error:
        return client.fail(error, secrets(env))
    except Exception:                         # трассировка — только очищенная от ключей
        return client.crash(secrets(env))


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""oblako_client.py — общая половина двух клиентов контура ПК (блок 4.3).

Компьютер руководителя ходит на сервер Oblako по HTTP личным ключом доступа и
больше никак. Прежние `fetch_tasks.ps1` и `send_package.ps1` ходили по `ssh`/
`scp`: это Windows-only и полный доступ к машине сервера ради двух операций.
Здесь их место занимают `fetch_tasks.py` и `send_package.py` — один и тот же
путь на Windows и на macOS.

ЧТО ЛЕЖИТ ЗДЕСЬ. Всё, что у двух скриптов обязано быть ОДИНАКОВЫМ: чтение
`.env`, адрес сервера, заголовок с ключом, таймауты, проверка TLS, разбор
отказов сервера и коды выхода. Разъехавшись, скрипты дали бы два разных способа
предъявить ключ и два разных смысла у одного кода возврата.

КЛЮЧ НЕ ПОКАЗЫВАЕТСЯ НИГДЕ. Он приезжает только из `.env`, едет только
заголовком `X-Oblako-Key` и не попадает ни в вывод, ни в текст ошибки: адрес и
строка запроса пишутся в журнал доступа любого сервера, а флаг командной строки
осел бы в истории команд. На случай, если ключ всё же окажется внутри чужого
текста (например, сервер вернул его эхом), весь печатаемый текст проходит через
`redact` — это страховка, а не разрешение так делать.

КОДЫ ВЫХОДА — контракт для команды-скилла (блок 5), который решает по ним, что
делать дальше. Менять смысл кодов нельзя, не поправив её:

    0  сделано
    1  работа не сделана и повторять её бессмысленно: аргументы, `.env`, файла
       нет, локальный режим вне репозитория, поломка самого скрипта
    2  сервер отказал: ключ не принят, чужой отдел, пакет не прошёл проверку
    3  до сервера не достучались: сеть, DNS, TLS, таймаут, поломка сервера
    4  пакет применён, но итог опубликован НЕ ПОЛНОСТЬЮ — досдать
       `send_package.py --publish-only --team <отдел>`
    5  пакет применён, а публиковать итог НЕКУДА И НЕ НАДО: разбор сдавали с
       `--no-publish` (у отдела нет группового чата). Доделывать нечего

Четвёртый код отдельный намеренно: применение и публикация — разные события, и
«задачи легли, а пост в группу ушёл наполовину» нельзя ни считать успехом, ни
трактовать как повод повторить применение.

Пятый отделён от четвёртого по тому же вопросу «что делать человеку»: у
четвёртого есть досдача, у пятого её нет и быть не может — публиковать некуда, а
не не удалось. Слепив их, команда-скилл гоняла бы человека за досдачей, которая
ответит тем же отказом (тикет #280).

ТАБЛИЦА ДЕЙСТВУЕТ В БОЕВОМ РЕЖИМЕ. `--local` отдаёт код серверной команды как
есть (0 или 1): это отладочный режим внутри репозитория проекта, и различать в
нём отказ от недоступности нечем — сети там нет вовсе.

`.env` ищется ОТ ПАПКИ СКРИПТА ВВЕРХ до первого найденного. В установочном
пакете он лежит рядом со скриптами, в репозитории проекта — на уровень выше;
одно правило покрывает оба случая и не зависит от того, из какой папки запущено.

ЗАВИСИМОСТЕЙ НЕТ. Только стандартная библиотека: пакет разворачивают на чужой
машине мастером установки, и `pip install` там — лишний шаг, который умеет
ломаться.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import re
import ssl
import subprocess
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# --- коды выхода (см. шапку) ------------------------------------------------
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_NO_SERVER = 3
EXIT_PUBLISH_INCOMPLETE = 4
EXIT_NO_PUBLISH = 5

ACCESS_KEY_HEADER = "X-Oblako-Key"      # то же имя, что у сервера (bot/web.py)
KEY_ENV = "OBLAKO_ACCESS_KEY"
URL_ENV = "OBLAKO_BASE_URL"
ACTOR_ENV = "OBLAKO_ACTOR_ID"           # только локальный режим — по ключу личность приезжает сама
LIBRARY_URLS_ENV = "OBLAKO_LIBRARY_URLS"    # адреса репозиториев Библиотеки через `;`
LIBRARY_DIR_ENV = "OBLAKO_LIBRARY_DIR"      # где держать клоны, если не рядом с командами
LIBRARY_DIR = "Библиотека"                  # умолчание: папка клонов в корне работы
ROUTINE_ENV = "OBLAKO_ROUTINE_ID"           # идентификатор рутины-автомата (адрес, не секрет)

# Таймауты заданы ЯВНО и разные: у выгрузки это чистое чтение, а сдача разбора
# на той стороне ещё рассылает уведомления и публикует пост в группу. Общий
# короткий таймаут рвал бы связь ровно тогда, когда сервер занят полезной
# работой, — и клиент не узнал бы, применён пакет или нет.
TIMEOUT_READ_SEC = 30
TIMEOUT_PACKAGE_SEC = 120
TIMEOUT_PUBLISH_SEC = 60

# Потолок тела пакета. ИСТОЧНИК ПРАВДЫ — СЕРВЕР, здесь копия ради понятного
# отказа до отправки: 413 без единого слова о причине читается хуже, чем «пакет
# больше предела — раздели планёрку». Копия может отстать (пакет живёт своим
# репозиторием), поэтому расхождение не молчит: ответ 413 объясняется словами и
# называет актуальный предел сервером, а не этой константой.
MAX_PACKAGE_BYTES = 512 * 1024

# --- версия формата разбора -------------------------------------------------
# То же число, что `PACKAGE_VERSION` в `bot/core.py` на сервере, и оно одно на
# обе половины круга «выгрузка → пакет». Копия здесь не оплошность: с блока 6
# пакет живёт СВОИМ репозиторием и обновляется отдельно от сервера, поэтому
# «версии разошлись» — рядовое состояние, а не авария. Задача этих строк одна:
# заметить расхождение и назвать отставшего.
PACKAGE_FORMAT_VERSION = 2
EXPORT_FORMAT = "oblako-tasks-export"

# --- версия формата ручек автомата (#454) -----------------------------------
# ПАРА СВОЯ, А НЕ ФОРМАТ ВЫГРУЗКИ ЗАДАЧ. У ручек автомата свой договор с
# сервером, и версии у них обязаны жить врозь: одна пара на два формата
# означала бы, что правка разбора планёрки двигает номер расшифровки и наоборот.
# То же, что `MEETINGS_FORMAT` и `MEETINGS_VERSION` в `bot/core.py`; копия здесь
# по той же причине, что и у разбора, — пакет обновляется отдельно от сервера.
MEETINGS_FORMAT = "oblako-meetings"
MEETINGS_VERSION = 1

# --- отчёт автомата о расшифровке (#454) ------------------------------------
# Потолок строки — копия серверного (`core.TRANSCRIPT_REPORT_LINE_MAX`), и
# держится он ЗДЕСЬ, а не в `avtomat.py`. Причина сбоя приезжает из чужих
# текстов (ответ Zoom, вывод git, трассировка Python), и без обрезки на сервер
# уехала бы полем `error` сама расшифровка: инвариант 22 («сервер текстов встреч
# не хранит») держится в том числе аккуратностью этого клиента.
TRANSCRIPT_REPORT_LINE_MAX = 500
TRANSCRIPT_DONE = "done"
TRANSCRIPT_FAILED = "failed"
TRANSCRIPT_NO_RECORDING = "no_recording"
TRANSCRIPT_OUTCOMES = (TRANSCRIPT_DONE, TRANSCRIPT_FAILED, TRANSCRIPT_NO_RECORDING)

# СЛОВО О ГОТОВНОСТИ «МОИХ ВСТРЕЧ» (#475, #480) — одно имя на две двери: поле в
# отчёте о задании и всё тело самоотчёта без задания. Имя серверное
# (`core.MY_MEETINGS_READY_FIELD`), и второй копии у пакета нет: разойдись они,
# сервер отверг бы отчёт незнакомым полем после часа работы автомата.
MY_MEETINGS_FIELD = "my_meetings_ready"

# СЛОВО ОБ УМЕНИИ «РАЗБОР» (#509, #514) — рядом со словом о готовности и по той
# же причине: способность сообщает сам пакет, при любом исходе отчёта, и тем же
# именем, что у сервера (`core.REVIEWS_FIELD`). Этот пакет разбор умеет — слово
# всегда «да».
REVIEWS_FIELD = "reviews"

# Слова пакета о себе — ЕДИНСТВЕННЫЕ поля отчёта, которые можно снять и
# повторить без них (см. `transcripts`): сервер, ещё не знающий слова, отверг бы
# весь отчёт, а сам отчёт важнее любого слова о себе.
SELF_WORDS = (MY_MEETINGS_FIELD, REVIEWS_FIELD)

# Имена файлов папки разбора, которые нужны ОБОИМ клиентам. Остальные знает одна
# механика разбора (`meeting.py`); эти два вынесены сюда потому, что гейт
# «запиши» обязан держать и у прямого клиента: имя файла подтверждения —
# половина этого гейта.
CONFIRMED = "Подтверждение.json"
PACKAGE = "package.json"

# Локальный режим зовёт серверный CLI ЭТИМ ЖЕ интерпретатором: угадывание
# `.venv\Scripts\python.exe` против `.venv/bin/python` — первое, что ломается
# при переходе на macOS, а `sys.executable` верен на обеих ОС по построению.
LOCAL_CLI = "bot.cli"


class ClientError(Exception):
    """Отказ клиента, у которого есть код выхода и человеческое объяснение."""

    exit_code = EXIT_USAGE

    def __init__(self, message: str, details: Optional[list] = None):
        super().__init__(message)
        self.message = message
        self.details = list(details or [])


class Usage(ClientError):
    """Не с чем работать: аргументы, настройки, файл. Сервер не тронут."""

    exit_code = EXIT_USAGE


class Refused(ClientError):
    """Сервер ответил отказом: ключ, права, отдел, непрошедший проверку пакет.

    ИМЯ ПОЛЯ ДОЕЗЖАЕТ ОТДЕЛЬНЫМ ПРИЗНАКОМ, а не только внутри сообщения: по нему
    отчёт автомата узнаёт отказ «такого поля у меня нет» от сервера, который
    ещё не выкачен, и повторяет себя без этого поля. Разбирать формулировку
    значило бы завести второго судью причины — тот же довод, что у
    `team_without_chat` ниже.
    """

    exit_code = EXIT_REFUSED

    def __init__(self, message: str, details: Optional[list] = None,
                 status: Optional[int] = None, field: Optional[str] = None):
        super().__init__(message, details)
        self.status = status
        self.field = field


class Unreachable(ClientError):
    """До сервера не достучались или он сломался — повторить можно и нужно."""

    exit_code = EXIT_NO_SERVER


# ---------------------------------------------------------------------------
# Консоль и вывод
# ---------------------------------------------------------------------------
def setup_console() -> None:
    """Кириллица и « » в консоли Windows — заменой, а не падением.

    На macOS вывод и так UTF-8; на Windows кодовая страница консоли бывает
    любой, и единственная «ё» в отчёте роняла бы скрипт после успешной работы.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):        # перенаправленный поток — не беда
            pass


def redact(text: str, key) -> str:
    """Вырезать ключ из текста. Последний рубеж перед печатью, не разрешение.

    Сам клиент ключ никуда не кладёт, кроме заголовка. Но текст ошибки приходит
    и снаружи — от сервера, от urllib, из чужой библиотеки, — и одна утечка в
    консоль переживает сессию в истории терминала.

    КЛЮЧ БЫВАЕТ НЕ ОДИН, поэтому принимается и список. У клиентов сервера он
    один — личный ключ доступа; у Библиотеки (`library.py`) к нему добавляются
    токены из адресов репозиториев. Заводить рядом вторую такую же функцию
    нельзя: последний рубеж перед печатью обязан быть один — иначе однажды
    печатать станут мимо него.
    """
    keys = [key] if isinstance(key, str) else list(key or [])
    for one in keys:
        # Порог в четыре символа держит одно: короткая строка вроде «1» или «ok»,
        # попавшая в KEY_ENV по ошибке, не должна превращать весь текст в решето.
        # Живой ключ длиннее сорока символов, под порог он не попадает никогда.
        if one and len(one) >= 4:
            text = text.replace(one, "<ключ скрыт>")
    return text


def fail(error: ClientError, key: Optional[str] = None) -> int:
    """Напечатать отказ в stderr и вернуть его код выхода."""
    print(redact(error.message, key), file=sys.stderr)
    for line in error.details:
        print(f"  · {redact(str(line), key)}", file=sys.stderr)
    return error.exit_code


def crash(key: Optional[str] = None) -> int:
    """Неожиданная ошибка: трассировка печатается ОЧИЩЕННОЙ от ключа.

    Голая трассировка Python выносит в консоль значения аргументов, а среди них
    бывает заголовок с ключом. Глотать её целиком тоже нельзя — без неё ошибку
    скрипта нечем чинить. Код возврата тот же, что у негодного вызова: работа не
    сделана, и повторять её бессмысленно.
    """
    print(redact(traceback.format_exc(), key), file=sys.stderr)
    print("Это ошибка самого скрипта — покажи трассировку разработчику.",
          file=sys.stderr)
    return EXIT_USAGE


# ---------------------------------------------------------------------------
# Настройки: .env рядом со скриптом или выше
# ---------------------------------------------------------------------------
def read_dotenv(path: Path) -> dict:
    """`KEY=value` построчно; `#` — комментарий, кавычки вокруг значения снимаются.

    Свой разбор, а не библиотека: зависимостей у пакета нет намеренно. Формат
    тот же, что читает сервер (`bot.load_env`), — иначе один и тот же файл
    понимался бы на ПК и на сервере по-разному.
    """
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def find_dotenv(start: Path, stop: Optional[Path] = None) -> Optional[Path]:
    """Первый `.env` от папки скрипта вверх, НЕ ВЫШЕ ``stop``, — или None.

    Потолок обязателен. В установочном пакете скрипты лежат в его корне, и без
    потолка поиск уходил бы в родительскую папку клона: чужой `.env` с другим
    адресом сервера и чужим ключом подхватился бы молча — выгрузка ушла бы не на
    тот сервер и не от того человека, а проверка установки отрапортовала бы
    «настройки на месте».
    """
    for folder in [start, *start.parents]:
        candidate = folder / ".env"
        if candidate.is_file():
            return candidate
        if stop is not None and folder == stop:
            return None
    return None


def settings(script: Path) -> dict:
    """Настройки этого скрипта: `.env` рядом со скриптами, а ПОВЕРХ — окружение.

    Потолок поиска `.env` — корень рабочей копии: в установочном пакете это
    папка самих скриптов, в репозитории проекта — его корень, где `.env` и лежит.

    ОКРУЖЕНИЕ ВАЖНЕЕ ФАЙЛА, И ЭТО ОДНО ПРАВИЛО НА ВЕСЬ ПРОЕКТ — то же, что у
    сервера (`bot.load_env`). Здесь оно не удобство, а условие работы автомата: в
    облачной машине рутины `.env` НЕТ ВОВСЕ, и ключи Zoom, Deepgram, доступа к
    серверу и адреса Библиотеки приезжают туда переменными окружения, которые
    человек задал рутине один раз. Пока правило жило в одном скрипте
    (`zoom_pull.load_env`), соседи латали себя поодиночке — параметром `env` у
    `library.main`, флагом у `avtomat.run_script`, своим обходом в `transcribe`, —
    и в пакете завелось три способа прочитать одно окружение. Способ один, и он
    здесь: чтение настроек в пакете единственное.
    """
    here = Path(script).resolve().parent
    found = find_dotenv(here, stop=work_root(script))
    values = read_dotenv(found) if found is not None else {}
    for name, value in os.environ.items():
        if value:
            values[name] = value
    return values


def access_key(env: dict) -> str:
    """Личный ключ доступа или отказ с объяснением, где его взять.

    Испорченный ключ ловится ЗДЕСЬ, а не в HTTP: заголовки едут latin-1, и
    кириллическая «с» вместо латинской (обычная цена копирования) роняла бы
    urllib с трассировкой — а в трассировку попадает значение. Сам ключ в
    сообщении не показывается ни при каком исходе.
    """
    key = (env.get(KEY_ENV) or "").strip()
    if not key:
        raise Usage(
            f"Нет ключа доступа: добавь {KEY_ENV}=<ключ> в .env. Ключ выдаёт "
            f"кнопка «Ключ доступа» в настройках Mini App; показывается он один раз."
        )
    if not (key.isascii() and key.isprintable()):
        raise Usage(
            f"Ключ доступа испорчен: в нём есть символы, которых в ключе не бывает "
            f"(похоже на кириллицу или перенос строки). Выпусти новый кнопкой в "
            f"настройках Mini App и вставь его в {KEY_ENV} целиком."
        )
    return key


def check_format(answer: dict, *, fmt: str, ours: int, what: str,
                 tail_stale: str = "", tail_ahead: str = "") -> None:
    """Ответ сервера — того ли формата и той ли версии, что понимает пакет.

    ОДНО МЕСТО НА ВСЕ ДВЕРИ. Правило сверки одинаково у выгрузки задач и у ручек
    автомата вплоть до тонкости с `bool`, и написанное дважды оно однажды
    разъедется: поправят одну копию, а вторая продолжит считать `True` версией 1.

    Расходятся у дверей только ХВОСТЫ СОВЕТА, и они здесь параметрами: разбор,
    узнавший о расхождении на выгрузке, придётся собирать заново, а автомату
    пересобирать нечего — общий текст врал бы одной из сторон.

    СВЕРКА СТОИТ ДО РАБОТЫ, А НЕ ПОСЛЕ. Выгрузка — первый шаг разбора; узнать
    «пакет устарел» после часа работы над встречей значит узнать слишком поздно.
    У автомата цена прямее: за расшифровку платят Deepgram. Второй рубеж всё
    равно остаётся, и он же последний: версию пакета судит сервер при приёме
    (`core.package_version_error`) — судья формата один, и это он.

    Отставшего называем поимённо: меньше нашей — отстал сервер (обновляет его
    владелец), больше — отстал этот компьютер (обновляется командой агенту
    «обнови пакет»). Совет не по адресу водил бы человека по кругу.

    Код выхода — 1, а не 2 и не 3: сервер ответил и не отказывал, сеть исправна,
    повтор бессмыслен. Помогает ровно одно действие, и оно названо.
    """
    if answer.get("format") != fmt:
        raise Usage(
            f"Это не {what}: формат {answer.get('format')!r} вместо {fmt!r}. "
            f"Проверь {URL_ENV} — адрес ведёт не на тот сервер."
        )
    theirs = answer.get("version")
    # `bool` — подкласс `int`, и отсев стоит ДО сравнения: `True == 1` — правда,
    # поэтому у двери с версией 1 (ручки автомата) `True` проходил бы за свою
    # версию молча. Версия — целое число и ничто другое.
    number = isinstance(theirs, int) and not isinstance(theirs, bool)
    if number and theirs == ours:
        return
    if number and theirs < ours:
        raise Usage(
            f"Сервер старее этого пакета (v{theirs} против v{ours}): отстал сервер, "
            f"а не этот компьютер — скажи владельцу системы.{tail_stale}"
        )
    seen = f"v{theirs}" if number else repr(theirs)
    raise Usage(
        f"Сервер ушёл вперёд ({seen}, этот пакет говорит на v{ours}): обнови пакет на "
        f"своём компьютере — командой агенту «обнови пакет».{tail_ahead}"
    )


def check_export(snapshot: dict) -> None:
    """Выгрузка задач — того ли формата и версии. Правило — `check_format`."""
    check_format(snapshot, fmt=EXPORT_FORMAT, ours=PACKAGE_FORMAT_VERSION,
                 what="выгрузка Oblako",
                 tail_stale=" Разбор пока не собрать.",
                 tail_ahead=" Потом начинай разбор заново.")


def base_url(env: dict) -> str:
    """Адрес сервера из `.env`, с явным требованием https.

    Открытый http допускается только на своей машине (разработка): ключ едет
    заголовком, и по незашифрованному каналу его увидит любой посредник.
    """
    url = (env.get(URL_ENV) or "").strip().rstrip("/")
    if not url:
        raise Usage(f"Не задан адрес сервера: добавь {URL_ENV}=https://<домен> в .env")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        return url
    if parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1"):
        return url
    raise Usage(f"{URL_ENV} должен начинаться с https:// — ключ по открытому каналу не ходит")


def library_urls(env: dict) -> list:
    """Адреса репозиториев Библиотеки из `.env` — список, возможно пустой.

    Библиотека НЕОБЯЗАТЕЛЬНА: пакет без неё разбирает планёрки ровно как
    прежде, поэтому пустой ответ здесь — не отказ, а «не настроена». Отказом
    отвечает только то, без чего работа не идёт (`base_url`, `access_key`).

    Адреса через `;`, как папки записи в `OBLAKO_AUDIO_DIRS`: разделитель у
    списков в этом `.env` один, иначе человек угадывал бы его для каждой строки.
    Токенов в адресе не бывает — доступ к GitHub даёт `gh auth login`, и
    хранится он в хранилище системы, а не здесь.
    """
    raw = (env.get(LIBRARY_URLS_ENV) or "").strip()
    return [part.strip() for part in raw.split(";") if part.strip()]


def library_dir(home: Path, env: dict) -> Path:
    """Папка с клонами Библиотеки: `OBLAKO_LIBRARY_DIR` или `Библиотека` в корне.

    Корень спрашивается у вызывающего (`work_root`), а не считается заново: у
    клонов и у `Разборы` он обязан быть один, иначе установка положила бы
    Библиотеку не туда, где её потом ищет работа, — и промах вышел бы молчаливым.

    ОТНОСИТЕЛЬНЫЙ ПУТЬ СЧИТАЕТСЯ ОТ КОРНЯ РАБОТЫ, а не от папки, из которой
    запустили команду. Иначе `OBLAKO_LIBRARY_DIR=Документы/Библиотека` означал
    бы разные места у механики Библиотеки (`library.py`) и у проверки установки:
    первая написала бы файл, вторая сказала бы «клона нет».
    """
    stated = (env.get(LIBRARY_DIR_ENV) or "").strip()
    if not stated:
        return Path(home) / LIBRARY_DIR
    folder = Path(stated).expanduser()
    return folder if folder.is_absolute() else Path(home) / folder


def _library_parts(url: str) -> list:
    """«владелец» и «имя» из адреса репозитория, какой бы формы он ни был.

    Форм три, и различать их приходится: `https://github.com/владелец/имя.git`,
    `git@github.com:владелец/имя.git` и путь на диске (так удобно проверять без
    сети). Хвост `.git` и косая черта на конце снимаются — один и тот же
    репозиторий записывают и с ними, и без.
    """
    clean = (url or "").strip().rstrip("/")
    if clean.endswith(".git"):
        clean = clean[:-4]
    # `//` есть только у адреса со схемой (https://, file://); всё остальное —
    # либо ssh-форма с двоеточием перед путём, либо путь на диске.
    tail = urllib.parse.urlsplit(clean).path if "//" in clean else clean.rsplit(":", 1)[-1]
    return [part for part in tail.replace("\\", "/").split("/") if part]


def library_name(url: str) -> str:
    """Имя репозитория — оно же имя папки клона внутри `Библиотека/`."""
    parts = _library_parts(url)
    return parts[-1] if parts else ""


def library_slug(url: str) -> str:
    """«владелец/имя» без схемы и `.git` — по нему сверяется `origin` клона.

    Сверять адреса посимвольно нельзя: один и тот же репозиторий клонируют и по
    https, и по ssh, и проверка ругалась бы на исправный клон. Сверяется то, что
    у обеих форм общее и что как раз и отличает чужой репозиторий от своего.
    """
    return "/".join(_library_parts(url)[-2:]).lower()


def team(stated: Optional[str]) -> str:
    """Отдел операции, названный явно. Умолчания «у него отдел один» нет.

    Сегодня один, завтра два — молчаливое угадывание отправило бы разбор в чужой
    чат (решение 3.5.21). Правило живёт ЗДЕСЬ, а не в каждом скрипте: у сдачи
    разбора и у механики шагов оно одно, и разъехавшись, они дали бы два разных
    ответа на один забытый флаг.
    """
    name = (stated or "").strip()
    if not name:
        raise Usage("Не назван отдел: --team <номер или имя>. Угадывать отдел "
                    "система не вправе — их у тебя может быть несколько")
    return name


def same_team(selector: str, team_of_work: Optional[dict]) -> Optional[bool]:
    """Тот ли отдел назвали. ``None`` — сверять не с чем (отдел неизвестен).

    Правило совпадает с серверным (``core.team_by_selector``) намеренно: целиком
    числовой селектор ВСЕГДА читается как номер, имя — без учёта регистра и
    краевых пробелов. Разойдись они — клиент пропускал бы то, что сервер понял
    иначе, и наоборот.

    Права здесь не судятся и судиться не могут: это сверка «то же ли, что просили
    минуту назад», а судья на сервере. Нужна она потому, что отдел называется
    заново на КАЖДОМ шаге разбора, а работа между шагами копится в папке: без
    сверки опечатка в одном флаге уводит готовый разбор в чужой отдел молча.
    """
    if not isinstance(team_of_work, dict):
        return None
    clean = (selector or "").strip()
    if clean.isdigit():
        return team_of_work.get("id") == int(clean)
    name = team_of_work.get("name")
    if not isinstance(name, str):
        return None
    return name.strip().lower() == clean.lower()


def digest(path: Path) -> str:
    """Отпечаток файла пакета. По нему подтверждение и расписка узнают СВОЙ пакет."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path: Path) -> Optional[dict]:
    """Разобранный JSON или None. Битый файл — не «нет файла», а отказ."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as error:
        raise Usage(f"{path.name} не разобрать: {error}") from None


# Слово-команда человека. Формы ТОЛЬКО ПОВЕЛИТЕЛЬНЫЕ, а не общий стебель «запиш»:
# «я сам запишу» и «запишем потом» — не поручение агенту, а разговор о себе, и
# по стеблю они прошли бы за команду. Одно и то же решение, сказанное по-разному
# («запиши», «запишите», «записывай»), при этом принимается.
COMMAND = r"(запиши(те)?|записывай(те)?)"
CONFIRM_WORD = re.compile(rf"\b{COMMAND}\b", re.IGNORECASE)
# Отрицание считается ТОЛЬКО непосредственно перед словом-командой: «не
# записывай» — отказ, а «запиши, но не Борису» — законная команда с оговоркой.
CONFIRM_DENIED = re.compile(rf"\bне\s+{COMMAND}\b", re.IGNORECASE)


def confirmed_by(word: str) -> None:
    """Гейт «запиши»: пропускает только явную команду человека.

    Слово приезжает СЛОВАМИ ЧЕЛОВЕКА, а не признаком «агент решил, что можно».
    Пересказ можно сделать любым, а «ок» вместо «запиши» отсюда не проходит —
    это и есть первый пояс от инцидента 14.07 на дороге разбора планёрки.

    ЖИВЁТ ЗДЕСЬ, А НЕ В МЕХАНИКЕ РАЗБОРА, по той же причине, что и
    `require_confirmation` ниже: дверей стало больше одной. Слово судят разбор
    планёрки (`meeting.py confirm`) и запись в Библиотеку (`library.py put`), и
    двум судьям однажды хватило бы одной правки, чтобы разойтись, — тогда одно и
    то же сказанное слово значило бы в двух местах разное.
    """
    said = (word or "").strip()
    if not said:
        raise Usage('Гейт «запиши»: не сказано ничего. Передай слова человека: '
                    '--word "запиши"')
    if CONFIRM_DENIED.search(said):
        raise Usage(f'Это отказ, а не команда: «{said}». В чужой список ничего не уходит.')
    if not CONFIRM_WORD.search(said):
        raise Usage(
            f'«{said}» командой не считается — нужно слово «запиши».',
            ['«ок», «понял», «хорошо», «согласен» — это не команда записи',
             "пока человек не сказал «запиши», ни одна задача не уезжает в чужой "
             "список и ни один документ — в Библиотеку"])


def require_confirmation(package: Path, selector: str) -> dict:
    """Гейт «запиши» перед отправкой пакета — или отказ. Один на ОБА клиента.

    ЖИВЁТ ЗДЕСЬ, А НЕ В МЕХАНИКЕ РАЗБОРА, потому что дверей к серверу две:
    `meeting.py send` и `send_package.py --package` (последняя названа в
    CLAUDE.md как равноправная). Гейт, стоящий только у первой, держится одной
    фразой инструкции — а инцидент 14.07 случился ровно тогда, когда фразе
    поверили. Проверяется ОТПЕЧАТОК: пакет, переписанный после «запиши», это
    другой пакет.

    Сверяется и ОТДЕЛ: человек подтверждал разбор конкретного отдела, а `--team`
    называется отдельным флагом уже при отправке. Без сверки подтверждение
    планёрки Продаж пропускало бы `--team Логистика` — и при общем сотруднике
    часть пунктов прошла бы, а итог уехал в чужой чат.

    Возвращает запись подтверждения (слово человека, время, отдел).
    """
    package = Path(package)
    record = read_json(package.parent / CONFIRMED)
    if not record or not package.is_file():
        raise Usage(
            f"Этот пакет человек не подтверждал: {package}",
            ['рядом нет файла подтверждения — разбор ведёт meeting.py: '
             'preview, затем confirm --word "<слова человека>"',
             "пока человек не сказал «запиши», в чужой список не уезжает ни одна задача"])
    if record.get("package") != digest(package):
        raise Usage(
            f"Пакет переписали после «запиши»: {package}",
            ["отпечаток не сходится с подтверждённым — нужно новое слово человека",
             'meeting.py preview, затем confirm --word "<слова человека>"'])
    confirmed_team = record.get("team")
    if same_team(selector, confirmed_team) is False:
        raise Usage(
            f"Подтверждали разбор отдела «{confirmed_team.get('name')}», "
            f"а отправляем в «{selector}»",
            ["слово человека относится к одному отделу, а не к любому",
             "тот отдел — просто назови его в --team; другой — новый разбор и новое «запиши»"])
    return record


def actor_id(env: dict, stated: Optional[int]) -> int:
    """От чьего имени работает ЛОКАЛЬНЫЙ режим. По ключу личность не спрашивают.

    Умолчания «все» нет ни здесь, ни у серверной команды: забытый актор обязан
    кончиться отказом, а не снимком всей компании.
    """
    if stated and stated > 0:
        return stated
    from_env = (env.get(ACTOR_ENV) or "").strip()
    if from_env.isdigit() and int(from_env) > 0:
        return int(from_env)
    raise Usage(
        f"Локальному режиму нужен человек, от чьего имени работать: --actor <id> "
        f"или {ACTOR_ENV} в .env"
    )


# ---------------------------------------------------------------------------
# HTTP: единственное место, где предъявляется ключ
# ---------------------------------------------------------------------------
def _tls_context() -> ssl.SSLContext:
    """Проверка сертификата — ЯВНО включена, а не «по умолчанию».

    Умолчание urllib меняли между версиями Python, и на чужой машине оно может
    оказаться каким угодно. Здесь оно названо: имя хоста и цепочка проверяются
    всегда, выключателя у скрипта нет.
    """
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def keep_alive_request(request: urllib.request.Request, timeout: int, proxy=None):
    """Один HTTPS-запрос БЕЗ `Connection: close` — дорога для больших ответов.

    `urllib.request.urlopen` шлёт `Connection: close` всегда (зашито в
    `AbstractHTTPHandler.do_open`, снаружи не отключается), и сервер закрывает
    соединение сразу за последним байтом ответа. VPN-клиент с TUN-адаптером,
    через который идёт весь трафик машины (у руководителя — Happ,
    `happ-default-tun` как маршрут по умолчанию; «напрямую» на такой машине не
    бывает), на этом закрытии теряет хвост большого ответа. 07.09.2026 так
    висели до таймаута четыре расшифровки подряд (ответ Deepgram 3–6 МБ без
    последних десятков КБ) и рвались две закачки из четырёх у Zoom («последние
    50 КБ», #464). Воспроизводится на чём угодно: 10 МБ с speed.cloudflare.com
    с этим заголовком — 9 961 472 байта и тишина, без него — целиком за 5 с;
    прокси ни при чём, теряется одинаково. Малые ответы (≤ 1 МБ) проходят и
    так — поэтому ручки сервера Oblako ходят через `urlopen`, а сюда идут
    Deepgram и скачивание записей.

    Что повторяет за `urlopen`, чтобы серверы видели тот же запрос: `Content-Type`
    формы у POST без своего типа, `Accept-Encoding: identity` (иначе JSON может
    приехать сжатым), проверка TLS из `_tls_context`, таймаут на каждую
    операцию с сокетом. Дорога: `proxy` задан — CONNECT-тоннель через него; не
    задан — системный прокси, как у `urlopen` (переменные окружения, на Windows
    ещё реестр; `no_proxy` уважается); нет и его — напрямую.

    Возвращает `http.client.HTTPResponse` (`with`, `.read()`, `.status`). 4xx и
    5xx поднимаются как `urllib.error.HTTPError`, как у `urlopen`; 3xx НЕ
    следует — ответ отдаётся как есть, переброс решает вызывающий (у Zoom
    своя ограда `HomeOnly`).
    """
    url = urllib.parse.urlsplit(request.full_url)
    host, port = url.hostname, url.port or 443
    if proxy is None and not urllib.request.proxy_bypass(host):
        proxy = urllib.request.getproxies().get("https")
    if proxy:
        via = urllib.parse.urlsplit(proxy if "://" in proxy else "http://" + proxy)
        conn = http.client.HTTPSConnection(via.hostname, via.port or 8080,
                                           timeout=timeout, context=_tls_context())
        tunnel_headers = {}
        if via.username is not None:
            pair = (urllib.parse.unquote(via.username) + ":"
                    + urllib.parse.unquote(via.password or ""))
            tunnel_headers["Proxy-Authorization"] = (
                "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii"))
        conn.set_tunnel(host, port, tunnel_headers)
    else:
        conn = http.client.HTTPSConnection(host, port, timeout=timeout,
                                           context=_tls_context())
    path = (url.path or "/") + ("?" + url.query if url.query else "")
    headers = {name: value for name, value in request.header_items()
               if name.lower() != "connection"}
    lowered = {name.lower() for name in headers}
    if request.data is not None and "content-type" not in lowered:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if "accept-encoding" not in lowered:
        headers["Accept-Encoding"] = "identity"
    conn.request(request.get_method(), path, body=request.data, headers=headers)
    response = conn.getresponse()
    if response.status >= 400:
        raise urllib.error.HTTPError(request.full_url, response.status, response.reason,
                                     response.headers, response)
    return response


def urlopen(request: urllib.request.Request, timeout: int):
    """Единственная точка urllib — её же подменяют тесты (приём gcal.py).

    Имя публичное намеренно: в неё ходит не только `call`, но и проверка
    установки — она спрашивает кабинет Deepgram, а это чужая машина со своим
    заголовком. Дверь в сеть при этом обязана остаться одна: проверка TLS и
    таймаут заданы здесь и нигде больше.
    """
    return urllib.request.urlopen(request, timeout=timeout, context=_tls_context())


def call(method: str, path: str, *, url: str, key: str, timeout: int,
         query: Optional[dict] = None, body: Optional[bytes] = None) -> dict:
    """Запрос к ручке контура ПК. Возвращает разобранное тело ответа.

    Отказы разложены по трём кучам, и деление проходит по вопросу «что делать
    человеку»: 4xx — чинить запрос или права (`Refused`), 5xx и обрыв связи —
    повторить позже (`Unreachable`). Тело отказа сервера человеку показывается:
    у непрошедшего проверку пакета там список причин, и он и есть ответ.
    """
    address = url + path
    if query:
        address += "?" + urllib.parse.urlencode(query, encoding="utf-8")
    headers = {ACCESS_KEY_HEADER: key, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(address, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as refusal:
        raise _refusal(refusal) from None
    except UnicodeError:
        # Заголовки едут latin-1. Ключ до сюда доходит уже проверенным
        # (`access_key`), но страховка стоит: трассировка urllib вынесла бы
        # значение заголовка в консоль.
        raise Usage(
            f"Запрос не собрать: в {KEY_ENV} или в названии отдела есть символы, "
            f"которых там быть не может."
        ) from None
    except (urllib.error.URLError, ssl.SSLError, OSError) as broken:
        # Сеть, DNS, TLS, таймаут: ответа нет вовсе. Применён ли пакет —
        # неизвестно, и это честнее сказать, чем молча предложить повтор.
        raise Unreachable(
            f"Сервер не ответил ({type(broken).__name__}): {broken}. "
            f"Проверь связь и {URL_ENV}, потом повтори."
        ) from None
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Unreachable("Сервер ответил не JSON — похоже, отвечает не Oblako") from None
    if not isinstance(parsed, dict):
        raise Unreachable("Сервер ответил не тем видом JSON, какой ждёт клиент")
    return parsed


def _refusal(refusal: urllib.error.HTTPError) -> ClientError:
    """HTTP-отказ → человеческое объяснение и код выхода.

    Поломка сервера (5xx) — не отказ, а недоступность: повторить её осмысленно,
    а чинить запрос не в чем.
    """
    try:
        raw = refusal.read()
    except Exception:                 # тела может не быть вовсе
        raw = b""
    body: dict = {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
        body = parsed if isinstance(parsed, dict) else {}
    except (ValueError, UnicodeDecodeError):
        body = {}
    message = str(body.get("message") or "").strip()
    if refusal.code >= 500:
        return Unreachable(f"Сервер сломался (HTTP {refusal.code}). Повтори позже.")
    if refusal.code == 401 or refusal.code == 403:
        message = message or "Доступ запрещён"
        return Refused(
            f"Сервер не принял запрос (HTTP {refusal.code}): {message}. "
            f"Проверь {KEY_ENV} в .env и отдел, который называешь.",
            status=refusal.code,
        )
    if refusal.code == 413:
        # Наш предел мог отстать от серверного: пакет живёт своим репозиторием.
        # Отвечаем делом, а не голым кодом.
        return Refused(
            "Пакет больше того, что принимает сервер, — раздели планёрку на два "
            "пакета (у клиента предел свой и мог устареть).",
            status=refusal.code,
        )
    details = list(body.get("errors") or [])
    if body.get("error") == "team_without_chat":
        # ЕДИНСТВЕННЫЙ отказ, у которого есть выход, — и человек в этот момент
        # видит тупик: разбор готов, а сервер его не берёт. Подсказка ставится по
        # КОДУ отказа, а не по словам сообщения: гадать по формулировке значило
        # бы завести второго судью причины (тикет #280).
        # Формулировка годится ОБЕИМ дверям: у сдачи разбора выход — `--no-publish`,
        # у досдачи итога выхода нет вовсе, и советовать ей флаг сдачи нельзя.
        details.append("у отдела нет группового чата — публиковать некуда: разбор "
                       "такого отдела сдают без публикации (тот же вызов с "
                       "--no-publish), а досдавать в нём нечего")
    return Refused(
        f"Сервер отказал (HTTP {refusal.code}): {message or 'причина не названа'}",
        details=details,
        status=refusal.code,
        field=str(body.get("field") or "") or None,
    )


# ---------------------------------------------------------------------------
# Ручки автомата: встречи и отчёт о расшифровке (#454, зовёт их `avtomat.py`)
#
# Живут ЗДЕСЬ, а не в самом автомате, по тому же правилу, что и остальные две
# двери контура ПК: способ предъявить ключ, таймаут, проверка TLS и смысл кодов
# возврата обязаны быть одни на все обращения к серверу. Второй дороги к нему у
# пакета нет и не заводится.
# ---------------------------------------------------------------------------
def check_meetings(answer: dict) -> None:
    """Ответ ручки автомата — того ли формата и версии. Правило — `check_format`.

    Хвостов совета здесь нет: автомату, в отличие от разбора, пересобирать
    нечего — он просто не начнёт работу и отчитается серверу.
    """
    check_format(answer, fmt=MEETINGS_FORMAT, ours=MEETINGS_VERSION,
                 what="ответ Oblako про встречи")


def meetings(*, url: str, key: str, date_from=None, date_to=None,
             awaiting: bool = False) -> dict:
    """Встречи, которые вправе видеть предъявитель ключа.

    Окно называется ЦЕЛИКОМ или не называется вовсе — половину сервер отвергает;
    `awaiting=True` спрашивает только встречи с живым заданием автомата (очередь
    и полёт) и окна не требует: так вечерний добор узнаёт, что осталось.
    """
    query: dict = {}
    if date_from:
        query["from"] = date_from
    if date_to:
        query["to"] = date_to
    if awaiting:
        query["awaiting"] = "1"
    return call("GET", "/api/pc/meetings", url=url, key=key,
                timeout=TIMEOUT_READ_SEC, query=query or None)


def meeting(meeting_id: int, *, url: str, key: str) -> dict:
    """Подробности одной встречи. Чужая — отказ сервера, а не пустой ответ."""
    return call("GET", f"/api/pc/meetings/{int(meeting_id)}", url=url, key=key,
                timeout=TIMEOUT_READ_SEC)


def transcripts(meeting_id: int, report: dict, *, url: str, key: str) -> dict:
    """Отчёт автомата о расшифровке: «готово», «не вышло» или «записи нет».

    ТЕЛО ЧИСТИТСЯ ЗДЕСЬ, а не у вызывающего: пустые поля выбрасываются (сервер
    отвергает незнакомое и кривое поимённо, и `null` вместо числа минут стоил бы
    всей работы), строки режутся потолком. Исход сверяется со списком — чужое
    слово тут наша собственная опечатка, и стоит она отказа 400 после часа
    работы автомата.
    """
    outcome = report.get("outcome")
    if outcome not in TRANSCRIPT_OUTCOMES:
        raise Usage(f"Исхода «{outcome}» у отчёта не бывает: "
                    f"{', '.join(TRANSCRIPT_OUTCOMES)}")
    body = {}
    for name, value in report.items():
        if value is None:
            continue
        body[name] = value[:TRANSCRIPT_REPORT_LINE_MAX] if isinstance(value, str) else value
    return _without_unknown_self_words(
        body, lambda sent: _post_report(meeting_id, sent, url=url, key=key))


def _without_unknown_self_words(body: dict, send) -> dict:
    """Отправить тело; слово о себе, которого сервер не знает, — снять и повторить.

    СЛОВА ПАКЕТА О СЕБЕ — ЕДИНСТВЕННЫЕ ПОЛЯ, КОТОРЫЕ МОЖНО СНЯТЬ И ПОВТОРИТЬ
    (`SELF_WORDS`: готовность «Моих встреч», умение «разбор»). Пакет и сервер
    живут разными репозиториями, а облачная рутина клонирует пакет заново каждый
    запуск: выкати мы пакет раньше сервера — и сервер, ещё не знающий слова,
    отверг бы ВЕСЬ отчёт, то есть текст уже лежал бы в Библиотеке, а задание
    навсегда осталось бы «в полёте». Правило контура прежнее и остаётся верным:
    порядок выкатки не значим ни в одну сторону.

    Каждое слово снимается РОВНО ОДИН РАЗ и только названное отказом: сервер
    старше обоих слов называет их по одному, и второе снимается своим повтором.
    Остальные отказы 400 остаются отказами — повторяй клиент любую, он молча слал
    бы тело, которое сервер уже назвал неверным.
    """
    while True:
        try:
            return send(body)
        except Refused as refusal:
            if refusal.status != 400 or refusal.field not in SELF_WORDS:
                raise
            if refusal.field not in body:
                raise
            body = {name: value for name, value in body.items() if name != refusal.field}


def _post_report(meeting_id: int, body: dict, *, url: str, key: str) -> dict:
    """Отправить готовое тело отчёта — ШОВ к `call` для каждой попытки."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return call("POST", f"/api/pc/transcripts/{int(meeting_id)}", url=url, key=key,
                timeout=TIMEOUT_READ_SEC, body=raw)


def my_meetings(ready: bool, *, url: str, key: str) -> dict:
    """Самоотчёт автомата о себе — БЕЗ ЗАДАНИЯ (#475, Р13; умение «разбор» — #514).

    Вторая дверь тех же слов, и нужна она потому, что первый раз о себе пакет
    говорит пробным запуском мастера «подключи автомат»: заданий в тот момент нет
    ни одного, и сказать иначе нечем.

    ТЕЛО — ТОЛЬКО СЛОВА О СЕБЕ: готовность «Моих встреч» и умение «разбор». Сервер
    отвергает незнакомый ключ телом целиком и называет его по имени (у сервера
    старее #509 это умение — и оно снимается, как в отчёте), а номер человека сюда
    не пишется вовсе: адресат слова — хозяин ключа, и подставить другого нечем.
    """
    def send(body: dict) -> dict:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return call("POST", "/api/pc/my-meetings", url=url, key=key,
                    timeout=TIMEOUT_READ_SEC, body=raw)

    return _without_unknown_self_words({MY_MEETINGS_FIELD: bool(ready),
                                        REVIEWS_FIELD: True}, send)


# ---------------------------------------------------------------------------
# Черновик разбора (#511, зовут `meeting.py` и `avtomat.py`, #514)
#
# Три двери рядом с отчётом о расшифровке и по тому же правилу: ключ, таймаут и
# смысл кодов возврата — общие. Формат ответа сверяет вызывающий
# (`check_meetings`): шапка у этих ручек та же, что у ручек автомата.
#
# ТЕКСТА ВСТРЕЧИ В ТЕЛАХ НЕТ (инвариант 22): пункты черновика уезжают без цитат,
# уточнения — одним числом, причина «не вышло» — словом. Собирают тела
# вызывающие; судья тела — сервер, он отвергает незнакомое поимённо.
# ---------------------------------------------------------------------------
def review_draft_put(meeting_id: int, body: dict, *, url: str, key: str) -> dict:
    """Положить черновик разбора встречи: первый раз создаёт, дальше обновляет."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return call("PUT", f"/api/pc/reviews/{int(meeting_id)}/draft", url=url, key=key,
                timeout=TIMEOUT_READ_SEC, body=raw)


def review_draft(meeting_id: int, *, url: str, key: str) -> dict:
    """Живой черновик разбора встречи — ключ `draft`, `null` без черновика."""
    return call("GET", f"/api/pc/reviews/{int(meeting_id)}/draft", url=url, key=key,
                timeout=TIMEOUT_READ_SEC)


def review_failed(meeting_id: int, body: dict, *, url: str, key: str) -> dict:
    """Отчёт «разбор не вышел»: номер задания и слово причины."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return call("POST", f"/api/pc/reviews/{int(meeting_id)}/failed", url=url, key=key,
                timeout=TIMEOUT_READ_SEC, body=raw)


# ---------------------------------------------------------------------------
# Локальный режим: тот же серверный CLI, запущенный здесь
# ---------------------------------------------------------------------------
def work_root(script: Path) -> Path:
    """Корень рабочей копии: где заводятся `Разборы` и папки скиллов клиентов.

    РАСКЛАДА ДВА, И РАЗЛИЧАЕТ ИХ КОД ПРОЕКТА РЯДОМ, А НЕ ИМЯ ПАПКИ. В
    установочном пакете скрипты лежат в его корне — корень и есть их папка. В
    репозитории проекта они лежат в `Пакет/`, а корень выше: там и `Разборы`, и
    `.claude/`.

    Считать корнем «папку выше скриптов» нельзя, и это не теория: в клоне пакета
    такой корень оказывается ВЫШЕ клона, туда же ложатся папки скиллов — и
    агент, открытый в клоне, не видит ни одной команды. Промах при этом
    молчаливый: файлы записываются успешно, просто не туда.
    """
    here = Path(script).resolve().parent
    for folder in here.parents:
        if (folder / "bot" / "cli.py").is_file():
            return folder
    return here


def repo_root(script: Path) -> Path:
    """Корень репозитория проекта — или отказ, если скрипт живёт не в нём.

    Локальный режим зовёт `python -m bot.cli`, а этого кода в установочном
    пакете нет и не будет (в нём нет кода проекта вовсе). Сказать об этом прямо
    честнее, чем отдать `ModuleNotFoundError`.
    """
    found = work_root(script)
    if (found / "bot" / "cli.py").is_file():
        return found
    raise Usage(
        "Локальный режим работает только внутри репозитория проекта: рядом нет "
        "кода сервера (bot/cli.py). Убери --local — работа идёт по ключу."
    )


def run_local(script: Path, argv: list) -> int:
    """Выполнить серверный CLI здесь же и вернуть его код возврата.

    Код возврата отдаётся КАК ЕСТЬ: у команд `bot.cli` он свой (0/1), и
    переписывать его в коды клиента значило бы врать про то, чего клиент не
    делал.
    """
    root = repo_root(script)
    return subprocess.call([sys.executable, "-m", LOCAL_CLI, *argv], cwd=str(root))

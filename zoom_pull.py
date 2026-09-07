# -*- coding: utf-8 -*-
"""Забрать звуковую дорожку планёрки из облака Zoom в папку записей (#371).

Часть установочного пакета, но НЕОБЯЗАТЕЛЬНАЯ: работает только у того, кто выдал
своему ключу Zoom два права на чтение записей. Без них разбор идёт прежней
дорогой — агент спрашивает коннектор Zoom и даёт человеку ссылку на файл.
Скрипт ходит в облако ЛИЧНОГО Zoom-аккаунта того, кто записывает планёрку;
кода сервера в нём нет, как и во всём пакете.

    python zoom_pull.py --list --date 11.08.26   что есть в облаке за день
    python zoom_pull.py --date 11.08.26 --at 08:55   забрать эту встречу
    python zoom_pull.py --json --days 7          то же самое для агента
    python zoom_pull.py --meeting <uuid> --json  звук и транскрипт Zoom ЭТОГО
                                                 экземпляра встречи (#450, автомат)

═══ ЗАЧЕМ ═══

Разбор планёрки начинается с записи, а записи у него не было: человек открывал
облако Zoom в браузере, скачивал файл, перекладывал его в папку — и только потом
звал разбор. Скрипт убирает эти три шага. Имя файла при этом остаётся облачным
(«GMT20260807-085446_Recording.m4a»): `meeting._named_dates` его узнаёт, и запись
находится сама, без единой настройки.

═══ ВЫБИРАЕТ НЕ СКРИПТ ═══

Ведёт скрипт агент, а нужную встречу называет человек — датой и временем. Пока
за день запись одна, `--date` её и берёт; но встреч в день бывает несколько
(11.08.2026 их было три), и вот тогда скрипт НЕ ВЫБИРАЕТ САМ. Он показывает, что
нашёл, и ждёт `--at ЧЧ:ММ` — время по Москве, как его называет человек.

Молчаливый выбор здесь дороже отказа: скачанная «не та» запись уходит в
расшифровку, оттуда в разбор — и человек получает задачи с чужой встречи,
уверенный, что они с планёрки. Отказ он видит сразу, ошибку — никогда.

Машинный вид (`--json`) — для агента: список записей дня с временем, темой и
размером, чтобы выбор делался по данным, а не по угадыванию.

═══ КУДА КЛАДЁТСЯ ЗАПИСЬ ═══

В ПЕРВУЮ папку из `OBLAKO_AUDIO_DIRS` — ту, которую человек назвал своим местом
записей (у машины разбора это «D:\\Movavi Screen Recorder», где лежат и локальные
записи Zoom). Одно место на все записи, а не два: иначе половина планёрок
оказывалась бы в одной папке, половина в другой, и человек искал бы запись
глазами по двум деревьям. Разбор при этом не страдает — по папкам из
`OBLAKO_AUDIO_DIRS` он ходит вглубь и находит файл на любой глубине.

Настройки нет — остаётся «Аудио» рабочей копии: её `meeting.audio_dirs` держит в
списке первой и не убирает ничем, так что запасное место работает всегда.
Разовое отступление — `--to <папка>`.

═══ ТОЛЬКО ЗВУК, И ЭТО НЕ ПРИДИРКА ═══

Из записи берётся дорожка `audio_only` (M4A) и никогда видео: расшифровка
принимает шесть звуковых форматов (`transcribe.MIME_BY_EXT`), MP4 среди них нет,
а качать гигабайт картинки, чтобы отдать из него звук, незачем. Дорожки нет в
облаке — скрипт говорит об этом прямо и называет настройку Zoom, которая её
включает: гадать за человека и тащить видео он не станет.

═══ ПО ЭКЗЕМПЛЯРУ ВСТРЕЧИ, А НЕ ПО ДАТЕ (#450) ═══

Автомат (`avtomat.py`, #455) знает не дату, а саму встречу: сервер прислал ему
номер и uuid экземпляра из события Zoom. Дата здесь ненадёжна вдвойне: у серии
номер один на все дни, а за день бывает несколько записей — и правило «не
выбирать самому» оставило бы автомат без записи. Поэтому `--meeting <uuid или
номер>` спрашивает у Zoom файлы ИМЕННО ЭТОГО экземпляра (`GET
/meetings/{id}/recordings`): по uuid — тот самый день серии, по номеру — то,
что Zoom считает последней записью встречи с этим номером.

Кладутся ДВА файла под одним именем: звук `GMT…_Recording.m4a` и транскрипт
Zoom `GMT…_Recording.vtt` рядом. Одно имя — не красота: `meeting.find_names`
ищет имена говорящих в `*.vtt` рядом с записью, и пара с общим корнем имени
находится как одна запись даже в общей папке с десятком прошлых планёрок.
Транскрипта в облаке нет (Zoom его не включил или ещё не дописал — он
появляется ПОЗЖЕ звука) — скрипт говорит об этом прямо и заканчивает кодом 0:
звук есть, разбор пойдёт без имён, и это не отказ.

Что есть транскрипт в списке файлов записи, сверено по документации Zoom, а не
по памяти (Developer Docs, «Cloud recording» и ручка «Get meeting recordings»;
Developer Blog «Meeting API querying tips, part 1»):
  · звук — `recording_type: "audio_only"`, `file_type: "M4A"`;
  · транскрипт — `recording_type: "audio_transcript"`, `file_type:
    "TRANSCRIPT"`, `file_extension: "VTT"`; включается у хозяина настройкой
    «Audio transcript» облачной записи и приходит отдельным файлом;
  · uuid экземпляра кодируется в пути ДВАЖДЫ, если начинается с «/» или
    содержит «//», иначе Zoom отвечает «Meeting does not exist» (`meeting_path`).

`--dry-run` не ходит в сеть вовсе — ни за токеном, ни за списком: печатает,
куда лягут файлы и какой путь спросит у Zoom. Так автомат проверяют на машине
без ключа, и так же `send_package.py --dry-run` живёт без ключа сервера.

═══ КЛЮЧ ═══

Тот же ключ Server-to-Server OAuth, что и у остального контура Zoom, — три
строки `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` в `.env`
(читаются `oblako_client.settings`, окружение важнее файла — как у сервера).
Сверх прав на встречи ключу нужны ДВА права на чтение записей:
`cloud_recording:read:list_user_recordings:admin` (какие записи есть) и
`cloud_recording:read:list_recording_files:admin` (файлы конкретной встречи).
Их выдают по инструкции `Записи Zoom — чтобы помощник забирал их сам.md`. Нет
прав — Zoom отказывает, и скрипт показывает его текст целиком, а не прячет за
«не получилось».

═══ КОДЫ ВОЗВРАТА — КАК У КОНТУРА ПК ═══

0 сделано · 1 не с чем работать · 2 сервер отказал · 3 сервер не ответил ·
6 записи этой встречи в облаке ещё нет.
Первые четыре значения — те же и в том же смысле, что у
`Пакет/oblako_client.py`: разбор встречи ведёт одна и та же рука, и второй
словарь кодов ей пришлось бы держать в голове отдельно. Поэтому своя беда (нет
ключа в `.env`, не разобрана команда, за день несколько записей) — это код 1, а
не 2: код 2 говорит «чини Zoom», и человек с агентом ушли бы чинить исправное.

ШЕСТОЙ КОД — СВОЙ, И ОН НЕ УКРАШЕНИЕ. «Записи ещё нет» (Zoom отвечает 404 на
`/meetings/<экземпляр>/recordings`) и «Zoom отказал» — РАЗНЫЕ беды с разным
лечением: первая проходит сама через несколько минут, вторая сама не пройдёт
никогда (мёртвый ключ, отозванные права, 429, переброс за пределы Zoom). Слитые
в один код 2, они заставляли автомат (`avtomat.py`) звать «записи ещё нет» ЛЮБОЙ
отказ облака: до одиннадцати холостых запусков облачной рутины подряд, а
человеку в конце — ложная причина «записи встречи не было». Номер взят шестой, а
не четвёртый: 4 и 5 в контуре ПК уже заняты исходами пакета встречи
(`oblako_client.EXIT_PUBLISH_INCOMPLETE`, `EXIT_NO_PUBLISH`), и второй смысл у
того же числа сбил бы и человека, и агента.

НО НЕ ВСЯКИЙ 404 — ЭТО КОД 6. Тем же 404 Zoom отвечает и на «Meeting does not
exist» (`code 3001`): опечатка в номере комнаты, uuid чужого аккаунта, встреча,
которой в облаке нет вовсе. Ожиданием это не лечится никогда, а код 6 велит
именно ждать — и разбор встал бы в вечный круг. Тела ответов разводит
`no_such_meeting`: «нет такого экземпляра» уезжает кодом 2 («зовите человека»),
и только «запись ещё дописывается» (`code 3301`) остаётся кодом 6.
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import oblako_client as client

SCRIPT = Path(__file__).resolve()

OK, NOTHING, REFUSED, SILENT = 0, 1, 2, 3
NO_RECORDING = 6             # записи этой встречи в облаке ещё нет (см. шапку)

AUDIO_DIR = "Аудио"          # то же имя, что знает `Пакет/meeting.py`
AUDIO_DIRS_ENV = "OBLAKO_AUDIO_DIRS"   # и та же настройка, тем же разделителем
DATE_FMT = "%d.%m.%y"        # тот же формат даты, что у папок разбора
TIMEOUT = 60                 # секунд на запрос; у скачивания свой, длиннее
WINDOW = 30                  # ширина окна поиска в днях — правило Zoom
MSK = timezone(timedelta(hours=3))

TOKEN_URL = "https://zoom.us/oauth/token"
API = "https://api.zoom.us/v2"

# Один текст на оба режима (по дате и по экземпляру): беда одна, лечение одно.
NO_AUDIO = ("У этой записи нет отдельной звуковой дорожки — облако писало только видео,\n"
            "а расшифровка видео не принимает.\n"
            "Лечится в настройках Zoom: Запись → Облачные записи → «Запись только звука».\n"
            "Уже записанную встречу это не исправит, поможет только следующей.")

# Обрыв связи посреди чтения ответа прилетает четырьмя разными видами, и общего
# предка у них нет: `IncompleteRead` — из `http.client`, `SSLError` — из `ssl`,
# и только два последних наследуют `OSError`. Перечислены поимённо, потому что
# `except Exception` проглотил бы и ошибку в самом скрипте.
BROKEN = (http.client.HTTPException, ssl.SSLError, TimeoutError, OSError)


class Usage(Exception):
    """Своя беда: нет ключа, не разобрана команда, выбор не сделан. Код 1."""


class Refused(Exception):
    """Zoom ответил отказом. Текст ответа несём целиком — в нём причина.

    `status` — код HTTP, которым Zoom отказал (у отказов, придуманных здесь, его
    нет). Он нужен не для журнала: по нему «записи ещё нет» отделяется от
    «мёртвый ключ», а на этой развилке держится вся работа автомата.
    """

    def __init__(self, message, status: int | None = None):
        super().__init__(message)
        self.status = status


class NoRecording(Refused):
    """Записи этого экземпляра встречи в облаке ещё нет — Zoom ответил 404.

    ОТДЕЛЬНАЯ БЕДА, А НЕ ОТТЕНОК ОТКАЗА. Облако дописывает запись через
    несколько минут после конца встречи, и до этого её ручка отвечает «This
    recording does not exist». Лечение здесь одно — подождать и повторить;
    у остальных отказов Zoom (401, 429, отозванные права, переброс за пределы
    Zoom) ожидание не лечит ничего, и путать их нельзя: автомат по первой беде
    возвращается позже сам, а по второй зовёт человека.
    """


class Silent(Exception):
    """Zoom не ответил: сеть, таймаут, обрыв."""


class HomeOnly(urllib.request.HTTPRedirectHandler):
    """Редирект — только внутри Zoom. Ключ за его порог не выходит.

    Ссылка на скачивание перебрасывает с `us06web.zoom.us` на `ssrweb.zoom.us`
    (проверено живым вызовом), и заголовок с токеном обязан ехать следом —
    иначе файл не отдадут. Но `redirect_request` из `urllib`, в отличие от
    иных клиентов, заголовки при смене хоста НЕ срезает: перенаправь Zoom
    однажды на чужой адрес — и ключ уехал бы туда же. Ограда стоит не потому,
    что это случалось, а потому что цена промаха — чужой доступ ко всем
    записям аккаунта. Перебросы ведёт `KeepAlive.open`, а не `urllib`
    (см. там), но новый запрос строит по-прежнему эта родительская функция.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname or ""
        if host != "zoom.us" and not host.endswith(".zoom.us"):
            raise Refused(f"Zoom перебросил скачивание за свои пределы — на {host}. "
                          f"Ключ туда не отправлен, файл не скачан.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class KeepAlive:
    """Дорога в Zoom: постоянное соединение и ограда редиректов.

    Раньше здесь стоял `urllib.request.build_opener(HomeOnly)`. Он шлёт
    `Connection: close` всегда, и на машине, где весь трафик идёт через
    TUN-тоннель VPN-клиента (у руководителя — Happ), запись приходила без
    последних ~50 КБ и оставалась `.part` — 07.09.2026 две закачки из четырёх
    (#464). Причина, опыт и что помощник повторяет за `urlopen` — в пояснении
    `oblako_client.keep_alive_request`. Перебросы Zoom (`us06web.zoom.us` →
    `ssrweb.zoom.us`) помощник не следует, их ведёт этот класс — через ту же
    ограду `HomeOnly`, что и раньше: чужой хост — отказ, ключ не уезжает.
    Единственная точка, которую подменяют тесты автомата (`OPENER.open`).
    """

    LIMIT = 10          # перебросов подряд; Zoom делает один

    def open(self, request: urllib.request.Request, timeout: int = TIMEOUT):
        guard = HomeOnly()
        for _ in range(self.LIMIT):
            response = client.keep_alive_request(request, timeout)
            where = response.getheader("Location") if 300 <= response.status < 400 else None
            if where is None:
                return response
            newurl = urllib.parse.urljoin(request.full_url, where)
            request = guard.redirect_request(request, response, response.status,
                                             response.reason, response.headers, newurl)
            response.read()         # тело переброса не нужно; соединение отпустить
            response.close()
        raise urllib.error.URLError(f"Zoom перебрасывает по кругу, больше {self.LIMIT} раз")


OPENER = KeepAlive()


# ---------------------------------------------------------------------------
# Дорога к Zoom
# ---------------------------------------------------------------------------
def _open(request: urllib.request.Request, timeout: int = TIMEOUT):
    """Один HTTP-заход. Отказ сервера и молчание сети — РАЗНЫЕ беды.

    Разделение не косметическое: отказ означает «поправь ключ или права», а
    молчание — «попробуй ещё раз». Слитые в одно «не получилось», они заставляли
    бы человека перебирать оба лечения вслепую.
    """
    try:
        return OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", "replace")[:500]
        raise Refused(f"Zoom ответил {err.code}: {body}", status=err.code) from None
    except (urllib.error.URLError, *BROKEN) as err:
        raise Silent(f"Zoom не ответил: {err}") from None


def load_env() -> dict:
    """Настройки скрипта. Имя своё, правило общее — `oblako_client.settings`.

    Правило («`.env` рядом со скриптами, а поверх него окружение») живёт в
    клиенте и одно на весь пакет: один и тот же файл обязан пониматься одинаково
    всеми скриптами, иначе ключ, работающий на разборе, «не работает» на
    скачивании. Здесь остаётся только имя — его знают вызывающие и тесты.
    """
    return client.settings(SCRIPT)


def access_token(env: dict) -> str:
    """Токен ключа Server-to-Server OAuth. Живёт час, поэтому не кэшируется."""
    missing = [name for name in ("ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET")
               if not env.get(name)]
    if missing:
        raise Usage("В .env нет ключа Zoom: " + ", ".join(missing) +
                    ".\nКлюч заводится в кабинете Zoom как приложение типа "
                    "Server-to-Server OAuth и отдаёт ровно эти три строки.")
    body = urllib.parse.urlencode({
        "grant_type": "account_credentials",
        "account_id": env["ZOOM_ACCOUNT_ID"],
    }).encode()
    pair = f"{env['ZOOM_CLIENT_ID']}:{env['ZOOM_CLIENT_SECRET']}".encode()
    request = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    request.add_header("Authorization", "Basic " + base64.b64encode(pair).decode())
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with _open(request) as response:
        answer = json.loads(response.read())
    token = answer.get("access_token")
    if not token:
        raise Refused(f"Zoom не дал токен по этому ключу: {str(answer)[:300]}")
    return token


def api_get(path: str, token: str) -> dict:
    request = urllib.request.Request(API + path)
    request.add_header("Authorization", "Bearer " + token)
    with _open(request) as response:
        return json.loads(response.read())


# ---------------------------------------------------------------------------
# Что лежит в облаке
# ---------------------------------------------------------------------------
def window_for(day, days: int) -> tuple:
    """Окно поиска. Названа дата — окно строится ВОКРУГ НЕЁ, а не от сегодня.

    Иначе запись старше месяца была бы недостижима вовсе: Zoom ограничивает
    ШИРИНУ окна месяцем, но двигать его назад не запрещает, а записи в облаке
    живут дольше. Со старым правилом «всегда от сегодня» скрипт на `--date
    15.07.26` в конце августа отвечал «записи нет» — то есть уверенно говорил
    об отсутствии того, чего не искал.

    Ширина считается в днях с запасом в сутки по краям: время в ответе Zoom —
    UTC, и московский день выходит за границы дня UTC с обеих сторон.
    """
    if day:
        return day - timedelta(days=1), day + timedelta(days=1)
    today = date.today()
    return today - timedelta(days=min(days, WINDOW)), today


def recordings(token: str, since: date, upto: date) -> list:
    """Записи за окно, сверху свежие.

    Просить сразу «все за год» нельзя: Zoom режет такой запрос по своему
    правилу, и вместо ошибки вернулся бы неполный список — то есть скрипт молча
    не нашёл бы вчерашнюю планёрку. Поэтому окно называем сами (`window_for`) и
    говорим о нём человеку.

    Страницы дочитываются до конца: `page_size` у ручки не бесконечен, и на
    единственной странице свежая планёрка однажды не поместилась бы — отказ
    вышел бы полностью беззвучным.
    """
    found, token_page, guard = [], "", 0
    while guard < 20:
        guard += 1
        query = {"from": since.isoformat(), "to": upto.isoformat(), "page_size": 300}
        if token_page:
            query["next_page_token"] = token_page
        answer = api_get(f"/users/me/recordings?{urllib.parse.urlencode(query)}", token)
        found.extend(answer.get("meetings") or [])
        token_page = (answer.get("next_page_token") or "").strip()
        if not token_page:
            break
    return sorted(found, key=lambda item: item.get("start_time") or "", reverse=True)


def meeting_path(ref: str) -> str:
    """Экземпляр встречи в пути ручки Zoom: номер как есть, uuid — закодированный.

    Правило Zoom (Developer Blog «Meeting API querying tips, part 1»): uuid,
    который начинается с «/» или содержит «//», кодируется ДВАЖДЫ — то есть
    кодируется результат первого кодирования, а не приписывается второй раз.
    Иначе ответ — «Meeting does not exist», и автомат прочитал бы его как
    «записи нет» у встречи, которая есть.
    """
    ref = ref.strip()
    if ref.isdigit():
        return ref
    once = urllib.parse.quote(ref, safe="")
    if ref.startswith("/") or "//" in ref:
        return urllib.parse.quote(once, safe="")
    return once


def no_such_meeting(refusal: Refused) -> bool:
    """Тот ли это 404: «встречи с таким адресом нет» — или «записи ещё нет».

    Zoom отвечает 404 на ОБЕ беды, и различает их только тело ответа: `code
    3301` («This recording does not exist») — облако ещё дописывает запись,
    ждать имеет смысл; `code 3001` («Meeting does not exist») — названного
    экземпляра нет вовсе, и ожидание не вылечит это НИКОГДА. Опечатка в номере
    комнаты, uuid чужого аккаунта, встреча, которую не писали в облако, — это
    второй случай, и ответ «повтори позже» ставит разбор в вечный круг
    ожидания: автомат по коду 6 возвращается сам, а скилл велит агенту ждать.

    НЕИЗВЕСТНОЕ ТЕЛО СЧИТАЕТСЯ «ЗАПИСИ ЕЩЁ НЕТ» — так вёл себя скрипт до этой
    развилки. Живых тел Zoom здесь не снимали, разделение взято из его
    документации; ошибиться в сторону ожидания дешевле, чем сломать работающий
    путь ради ответа, которого мы не опознали.
    """
    text = str(refusal).lower()
    return "meeting does not exist" in text or re.search(r'"code"\s*:\s*3001', text) is not None


def instance(token: str, ref: str) -> dict:
    """Файлы записи одного экземпляра встречи — той же формы, что элемент списка.

    Zoom отдаёт ту же карточку (`uuid`, `id`, `topic`, `start_time`,
    `recording_files`), что и `recordings`, поэтому дальше её ведут те же
    `audio_track`, `file_name`, `describe` — второго пути по облаку нет.

    404 ЗДЕСЬ БЫВАЕТ ДВУХ СМЫСЛОВ, и путать их нельзя: «облако ещё дописывает
    запись» лечится ожиданием, «такого экземпляра нет» — только человеком,
    который назовёт верный адрес; судит их `no_such_meeting` по телу ответа.
    Отделяется беда ЗДЕСЬ, у единственной ручки, которая спрашивает конкретный
    экземпляр: у списка записей (`recordings`) 404 значил бы совсем другое —
    «нет такого аккаунта».
    """
    try:
        return api_get(f"/meetings/{meeting_path(ref)}/recordings", token)
    except Refused as refusal:
        if refusal.status != 404 or no_such_meeting(refusal):
            raise
        raise NoRecording(
            f"Записи этой встречи в облаке Zoom ещё нет. {refusal}\n"
            f"Облако дописывает запись не сразу — обычно через несколько минут "
            f"после конца встречи. Повтори позже."
        ) from None


def started_msk(meeting: dict):
    """Начало встречи по Москве. Zoom говорит временем UTC с буквой Z."""
    stamp = (meeting.get("start_time") or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(stamp).astimezone(MSK)
    except ValueError:
        return None


def audio_track(meeting: dict):
    """Звуковая дорожка встречи — САМАЯ БОЛЬШАЯ, если их несколько.

    Ведущий остановил и снова запустил запись — Zoom отдаёт несколько дорожек
    `audio_only`, и первая по списку бывает двухминутным обрывком. Тот же довод
    и то же лечение, что у `meeting.find_audio` («первый по алфавиту однажды
    окажется не встречей»): из равных берём самую большую.
    """
    tracks = [item for item in meeting.get("recording_files") or []
              if item.get("recording_type") == "audio_only" and item.get("download_url")]
    return max(tracks, key=lambda item: item.get("file_size") or 0) if tracks else None


def transcript_track(meeting: dict, audio: dict | None):
    """Транскрипт Zoom к звуковой дорожке: `audio_transcript` (VTT) — или ничего.

    Запись ставили на паузу — транскриптов столько же, сколько дорожек звука, и
    парой к выбранной дорожке считается тот, что начался вместе с ней. Пары по
    времени нет — берётся самый большой, по тому же доводу, что у `audio_track`.
    Вид файла — по документации Zoom: `recording_type: "audio_transcript"`,
    `file_type: "TRANSCRIPT"`, расширение VTT.
    """
    found = [item for item in meeting.get("recording_files") or []
             if item.get("recording_type") == "audio_transcript" and item.get("download_url")]
    if not found:
        return None
    start = (audio or {}).get("recording_start")
    paired = [item for item in found if start and item.get("recording_start") == start]
    return max(paired or found, key=lambda item: item.get("file_size") or 0)


def describe(meeting: dict) -> str:
    """Строка про встречу для глаза: когда, о чём, есть ли звук отдельно."""
    when = started_msk(meeting)
    stamp = when.strftime("%d.%m.%y %H:%M") if when else "время неизвестно"
    track = audio_track(meeting)
    size = f"{round((track.get('file_size') or 0) / 1048576)} МБ" if track else "звука нет"
    names = ", транскрипт Zoom есть" if transcript_track(meeting, track) else ""
    return f"{stamp}  «{meeting.get('topic') or 'без темы'}»  {size}{names}"


def as_data(meeting: dict) -> dict:
    """Встреча для агента: то же, что видит глаз, но полями."""
    when = started_msk(meeting)
    track = audio_track(meeting)
    return {
        "id": str(meeting.get("id") or ""),
        "uuid": meeting.get("uuid") or "",
        "topic": meeting.get("topic") or "",
        "date": when.strftime(DATE_FMT) if when else None,
        "at": when.strftime("%H:%M") if when else None,
        "size_mb": round((track.get("file_size") or 0) / 1048576) if track else 0,
        "has_audio": track is not None,
        "has_transcript": transcript_track(meeting, track) is not None,
    }


# ---------------------------------------------------------------------------
# Выбор встречи
# ---------------------------------------------------------------------------
def of_day(found: list, day) -> list:
    """Записи названного дня по московскому времени.

    Встреча без разобранного времени НЕ засчитывается за сегодняшнюю: приписать
    её текущему дню значило бы скачать неизвестно что под видом сегодняшней
    планёрки. Нет времени — нет и дня, такая запись выбирается только руками.
    """
    if not day:
        return found
    return [item for item in found
            if (started_msk(item) is not None and started_msk(item).date() == day)]


def pick(found: list, day, at) -> dict:
    """Одна встреча из списка. НЕСКОЛЬКО ЗА ДЕНЬ — НЕ ПОВОД ВЫБРАТЬ САМОМУ."""
    if at:
        named = [item for item in found
                 if started_msk(item) and started_msk(item).strftime("%H:%M") == at]
        if not named:
            raise Usage(f"Записи, начатой в {at}, нет. Что есть — покажет `--list`.",
                        found)
        found = named
    if len(found) > 1 and day:
        raise Usage(f"За {day.strftime(DATE_FMT)} в облаке несколько записей — "
                    f"назови нужную временем: `--at ЧЧ:ММ`.", found)
    return found[0]


def wanted_day(stated):
    if not stated:
        return None
    try:
        return datetime.strptime(stated.strip(), DATE_FMT).date()
    except ValueError:
        raise Usage(f"Дату не разобрать: {stated!r}. Формат — ДД.ММ.ГГ, "
                    f"как имя папки разбора (например {date.today().strftime(DATE_FMT)}).")


def wanted_time(stated):
    if not stated:
        return None
    try:
        return datetime.strptime(stated.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise Usage(f"Время не разобрать: {stated!r}. Формат — ЧЧ:ММ по Москве, "
                    f"как его называет человек (например 08:55).")


# ---------------------------------------------------------------------------
# Имя файла и место
# ---------------------------------------------------------------------------
def file_name(meeting: dict, track: dict) -> str:
    """Имя как у скачанного руками файла: «GMT20260807-085446_Recording.m4a».

    Придумывать своё имя нельзя: под этим Zoom отдаёт запись из облака, разбор
    его узнаёт (`meeting.PACKED_DATE`), и файл, скачанный скриптом, обязан быть
    неотличим от скачанного руками — иначе у разбора появилось бы два случая
    вместо одного.

    Дата в имени — UTC, как и говорит приставка GMT. Для планёрки в рабочее
    время она совпадает с московской, но ночная встреча (до 3:00 МСК) уехала бы
    в имени на день назад, и разбор искал бы её не за тот день. Поэтому в таком
    случае к имени приписывается московская дата: `meeting._named_dates` собирает
    ВСЕ даты пути, и встреча находится по любой из них.
    """
    stamp = (track.get("recording_start") or meeting.get("start_time") or "")
    try:
        utc = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise Refused(f"Zoom не назвал время записи: {stamp!r}") from None
    name = "GMT" + utc.strftime("%Y%m%d-%H%M%S") + "_Recording"
    local = utc.astimezone(MSK).date()
    if local != utc.date():
        name += f" ({local.isoformat()})"
    return name + ".m4a"


def target_dir(env: dict, stated) -> Path:
    """Куда класть запись: `--to` → первая папка `OBLAKO_AUDIO_DIRS` → «Аудио».

    Отдельной настройки под скачивание не заводим: человек уже назвал своё место
    записей один раз, и вторая настройка о том же неминуемо разъехалась бы с
    первой — файл ложился бы туда, где разбор его не ждёт. Берётся ПЕРВАЯ папка
    списка: он читается сверху вниз и начинается с главного места, а хвост —
    системные умолчания Zoom и «Загрузки».
    """
    if stated:
        return Path(stated).expanduser()
    for part in (env.get(AUDIO_DIRS_ENV) or "").split(";"):
        if part.strip():
            return Path(part.strip()).expanduser()
    return client.work_root(SCRIPT) / AUDIO_DIR


# ---------------------------------------------------------------------------
# Скачивание
# ---------------------------------------------------------------------------
def download(track: dict, target: Path, token: str, quiet: bool = False) -> None:
    """Дорожка → файл. Качаем в `.part` и переименовываем в самом конце.

    ПОЛОВИНА ЗАПИСИ НЕ СТАНОВИТСЯ ЗАПИСЬЮ. Оборванное чтение `read()` возвращает
    пустой кусок молча, как обычный конец файла: цикл выходит штатно, и без
    сверки размера получился бы файл с правильным именем и половиной встречи —
    разбор взял бы его не задумываясь, а человек недосчитался бы половины
    договорённостей, ничего об этом не узнав. Поэтому байты считаются и
    сверяются с тем, что назвало облако (проверено: цифры совпадают точно), а
    `.part` при расхождении остаётся `.part` — в разбор он не попадёт, его
    расширения нет в списке звуковых.

    Обрыв посреди чтения — это «сервер не ответил», а не «нечего качать»: без
    своей обработки он вышел бы наружу голым исключением с кодом 1, и агент
    прочитал бы отказ сети как «записи нет» и не повторил бы попытку.
    """
    request = urllib.request.Request(track["download_url"])
    request.add_header("Authorization", "Bearer " + token)
    part = target.with_name(target.name + ".part")
    expected = track.get("file_size") or 0
    got = 0
    try:
        with _open(request, timeout=TIMEOUT * 10) as response, part.open("wb") as sink:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                sink.write(chunk)
                got += len(chunk)
                if not quiet:
                    print(f"\r  качаю… {got / 1048576:.0f} МБ", end="", flush=True)
        if not quiet:
            print()
    except BROKEN as err:
        raise Silent(f"Связь оборвалась на {got / 1048576:.0f} МБ: {err}\n"
                     f"Недокачанное осталось в {part.name} — просто повтори.") from None
    if expected and got != expected:
        raise Silent(f"Скачано {got} байт вместо {expected} — связь оборвалась.\n"
                     f"Недокачанное осталось в {part.name} — просто повтори.")
    part.replace(target)


# ---------------------------------------------------------------------------
# Разбор команды
# ---------------------------------------------------------------------------
def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Забрать звук встречи из облака Zoom в папку записей.")
    parser.add_argument("--date", help="день встречи ДД.ММ.ГГ (по умолчанию — последняя запись)")
    parser.add_argument("--at", help="время начала ЧЧ:ММ по Москве — когда за день их несколько")
    parser.add_argument("--days", type=int, default=WINDOW,
                        help=f"сколько дней назад смотреть без --date, не больше {WINDOW}")
    parser.add_argument("--list", action="store_true", help="только показать, что есть в облаке")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="машинный вид списка — для агента")
    parser.add_argument("--force", action="store_true", help="скачать заново поверх готового файла")
    parser.add_argument("--to", help="папка для записи (по умолчанию — первая из OBLAKO_AUDIO_DIRS)")
    parser.add_argument("--meeting", metavar="UUID|НОМЕР",
                        help="экземпляр встречи: звук и транскрипт Zoom именно его, без выбора по дате")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="с --meeting: показать, куда лягут файлы, в сеть не ходить")
    return parser.parse_args(argv)


def fetch_pair(meeting: dict, folder: Path, token: str, force: bool, quiet: bool) -> dict:
    """Звук и транскрипт экземпляра → два файла с одним корнем имени.

    Возвращает, что вышло: пути и слово «why» про транскрипт, если его нет.
    Готовый файл того же размера второй раз не качается — как и в режиме по дате.
    `quiet` — для `--json`: агент читает вывод целиком как JSON, и строка
    «качаю… 12 МБ» посреди него сломала бы разбор ответа.
    """
    say = (lambda text: None) if quiet else print
    audio = audio_track(meeting)
    if audio is None:
        raise Usage(NO_AUDIO)
    names = transcript_track(meeting, audio)
    target = folder / file_name(meeting, audio)
    folder.mkdir(parents=True, exist_ok=True)
    got = {"audio": target, "transcript": None, "why": None}
    for track, path in ((audio, target), (names, target.with_suffix(".vtt"))):
        if track is None:
            continue
        size = track.get("file_size") or 0
        if path.exists() and not force and size and path.stat().st_size == size:
            say(f"Уже здесь: {path}")
        else:
            download(track, path, token, quiet)
            say(f"Готово: {path}")
        if track is names:
            got["transcript"] = path
    if names is None:
        got["why"] = ("Транскрипта Zoom у этой записи нет: облако его не включило или ещё "
                      "не дописало (он появляется позже звука). Имена говорящих не сшить — "
                      "расшифровка пойдёт без них; повторный запуск заберёт транскрипт, "
                      "когда он появится.")
        say(got["why"])
    return got


def run_meeting(args, env: dict) -> int:
    """Режим `--meeting`: файлы одного экземпляра встречи, а не выбор по дате."""
    folder = target_dir(env, args.to)
    if args.dry_run:
        plan = {"meeting": args.meeting, "path": f"/meetings/{meeting_path(args.meeting)}/recordings",
                "folder": str(folder), "dry_run": True}
        if args.as_json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(f"Спросил бы у Zoom {plan['path']} и положил бы звук с транскриптом в "
                  f"{folder}.\nНичего не скачано (--dry-run), в сеть не ходил.")
        return OK
    token = access_token(env)
    meeting = instance(token, args.meeting)
    if args.list:
        if args.as_json:
            print(json.dumps({"meeting": as_data(meeting)}, ensure_ascii=False, indent=2))
        else:
            print("Встреча: " + describe(meeting))
        return OK
    if not args.as_json:
        print("Встреча: " + describe(meeting))
    got = fetch_pair(meeting, folder, token, args.force, quiet=args.as_json)
    if args.as_json:
        print(json.dumps({"meeting": as_data(meeting), "audio": str(got["audio"]),
                          "transcript": str(got["transcript"]) if got["transcript"] else None,
                          "note": got["why"]}, ensure_ascii=False, indent=2))
    return OK


def run(argv) -> int:
    args = parse_args(argv)
    env = load_env()
    if args.meeting:
        if args.date or args.at:
            raise Usage("--meeting называет встречу сам: --date и --at с ним не нужны.")
        return run_meeting(args, env)
    if args.dry_run:
        raise Usage("--dry-run есть только у --meeting: режим по дате и так ничего не "
                    "качает без выбора (`--list`).")
    day = wanted_day(args.date)
    at = wanted_time(args.at)

    token = access_token(env)
    since, upto = window_for(day, max(1, args.days))
    found = of_day(recordings(token, since, upto), day)

    if not found:
        where = f"за {day.strftime(DATE_FMT)}" if day else f"за последние {min(args.days, WINDOW)} дн."
        if args.as_json:
            print(json.dumps({"meetings": [], "error": f"записей {where} нет"}, ensure_ascii=False))
        else:
            print(f"В облаке Zoom нет записей {where}.")
        return NOTHING

    if args.list or args.as_json:
        if args.as_json:
            print(json.dumps({"meetings": [as_data(item) for item in found]},
                             ensure_ascii=False, indent=2))
        else:
            print("Записи в облаке:")
            for item in found:
                print("  · " + describe(item))
        return OK

    meeting = pick(found, day, at)
    print("Встреча: " + describe(meeting))

    track = audio_track(meeting)
    if track is None:
        print(NO_AUDIO)
        return NOTHING

    target = target_dir(env, args.to) / file_name(meeting, track)
    target.parent.mkdir(parents=True, exist_ok=True)
    size = track.get("file_size") or 0
    if target.exists() and not args.force and size and target.stat().st_size == size:
        print(f"Уже здесь: {target}")
        return OK

    download(track, target, token)
    print(f"Готово: {target}")
    return OK


def main(argv=None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except Usage as err:
        # ТОЛЬКО первый аргумент: второй — сырые встречи Zoom, и `print(err)`
        # вывалил бы их целиком, вместе со служебными ссылками на скачивание.
        # Человеку нужна фраза, а из встреч — три поля, которые печатает
        # `describe`; список при отказе выбирать не украшение, а то самое, из
        # чего выбирают, и вторым заходом в облако он стоил бы лишнего запроса.
        print(err.args[0] if err.args else err)
        for item in (err.args[1] if len(err.args) > 1 else []):
            print("  · " + describe(item))
        return NOTHING
    except NoRecording as err:            # ловится ПЕРВЫМ: это подвид отказа
        print(err)
        return NO_RECORDING
    except Refused as err:
        print(err)
        return REFUSED
    except Silent as err:
        print(err)
        return SILENT


if __name__ == "__main__":
    raise SystemExit(main())

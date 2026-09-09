# -*- coding: utf-8 -*-
"""setup_check.py — повторяемая проверка установки пакета (блок 6).

ЗАЧЕМ ОН ЕСТЬ. Мастер установки — это разговор с агентом, и кончиться он обязан
не словами «готово», а ПРОВЕРКОЙ, которую можно запустить снова хоть завтра.
Слова стареют молча: ключ отзовут, `.env` перепишут, сервер переедет — и «у меня
всё настроено» окажется неправдой ровно в то утро, когда надо сдать планёрку.
Здесь же каждый ответ добывается заново.

ЧТО ПРОВЕРЯЕТСЯ, И ПОЧЕМУ ИМЕННО ЭТО. Каждая строка отвечает на вопрос «а
сработает ли разбор», и ни одна не проверяет саму себя:

    Python          версия интерпретатора, на котором всё это запущено
    .env            файл нашёлся, три значения на месте, ключ не испорчен
    Deepgram        КАБИНЕТ принял ключ — а не «строка непустая»
    Zoom            у ключа есть право на транскрипт помощника — иначе имена
                    говорящих придут через полчаса или не придут вовсе
    папки           `Разборы` и `Аудио` есть (нет — заводим тут же)
    команды агенту  указатели разложены и не устарели
    Библиотека      клоны на месте, `origin` наш, имя автора задано
    автомат         подключён ли, и на месте ли здесь всё, что ему отдали
    сервер          живой ответ по ключу: адрес, ключ, права и состав разом
    версия формата  сервер и пакет говорят на одном числе

ЗАПРОС К СЕРВЕРУ — НАСТОЯЩИЙ, И ЭТО СУТЬ. Проверять ключ «на вид» бессмысленно:
отозванный ключ выглядит ровно как живой. Одна выгрузка отвечает сразу на
четыре вопроса — тот ли адрес, принят ли ключ, есть ли у человека люди и не
разошлись ли версии, — и не пишет на сервере ничего.

ЧЕГО ЗДЕСЬ НЕТ. Zoom-коннектор проверяется НЕ отсюда: он живёт в клиенте агента
(Claude Code или Codex), а не в Python, и дотянуться до него скрипт не может.
Его проверяет мастер установки прямо на этой машине, и отказ там — не поломка:
остаётся локальная папка с записью, равноправный путь (решение 3.3.16). Что
скрипт может — сказать, где будут искать запись, и он говорит.

    python setup_check.py            проверить установку
    python setup_check.py --offline  без сети: только то, что видно на машине

КОД ВЫХОДА ЗДЕСЬ ТОЛЬКО ДВА: 0 всё готово, 1 есть что чинить. Кодов «сервер
отказал» и «сервер не ответил» у проверки нет намеренно — она не бросает работу
на первом отказе, а доходит до конца и показывает ВЕСЬ список: чинить три вещи
за один заход лучше, чем возвращаться трижды.

Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import fetch_tasks
import install_skills
import meeting
import oblako_client as client
import zoom_pull

SCRIPT = Path(__file__).resolve()
# Корень работы спрашивается у `oblako_client.work_root` — того же места, что
# отвечает механике разбора и указателям команд. «Папка скрипта» здесь не
# годится: в установочном пакете это одно и то же, а в репозитории проекта
# скрипты лежат в `Пакет/`, и проверка заводила бы `Пакет\Разборы`, пока работа
# идёт в `Разборы` корня. Хвалила бы она при этом папки, которых работа не
# касается.
HOME = client.work_root(SCRIPT)
VERSION_FILE = "ВЕРСИЯ"
SAMPLE_ENV = ".env.example"
WORK_DIRS = ("Разборы", "Аудио")
MIN_PYTHON = (3, 10)
GIT_TIMEOUT_SEC = 60
"""Потолок одного вызова git. Он нужен из-за `fetch`: сеть до GitHub из России
бывает вялой, и висеть без края проверка права не имеет — человек решит, что
она сломалась, и убьёт её на середине."""

AUTOMATON_SCRIPT = "avtomat.py"
AUTOMATON_TEMPLATE = Path("Автомат") / "расшифровка.md"
ZOOM_KEY_ENVS = ("ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET")
"""Три строки ключа Zoom — те же, что читает `zoom_pull.access_token`. Здесь они
названы ещё раз не ради проверки самого ключа (её делает `zoom_pull.py --list`),
а как признак: без ключа с тремя правами на записи автомату нечего забирать."""

DEEPGRAM_PROJECTS = "https://api.deepgram.com/v1/projects"
"""Самая дешёвая дверь Deepgram: список проектов кабинета. Она ничего не
распознаёт и денег не стоит — а живой ключ от отозванного отличает так же
надёжно, как расшифровка."""


class Report:
    """Список проверок и их исходов. Печатается по мере получения ответов.

    Ответы печатаются СРАЗУ, а не в конце: сетевые шаги идут секунды, и человек
    должен видеть, что проверка не зависла.
    """

    def __init__(self):
        self.failed = 0
        self.total = 0

    def ok(self, name: str, detail: str = "") -> None:
        self.total += 1
        print(f"  [ок]   {name}" + (f": {detail}" if detail else ""))

    def bad(self, name: str, detail: str, fix: str = "") -> None:
        self.total += 1
        self.failed += 1
        print(f"  [нет]  {name}: {detail}")
        if fix:
            print(f"         → {fix}")

    def skip(self, name: str, detail: str) -> None:
        """Проверять нечего — и это не «ок» и не «нет».

        Третий исход завёлся вместе с Библиотекой: пакет без неё целый, и
        считать ненастроенную Библиотеку успехом значило бы хвалить то, чего
        нет, а провалом — гнать человека настраивать необязательное. В счёт
        «готово N из N» такая строка не идёт по той же причине.
        """
        print(f"  [—]    {name}: {detail}")


def package_version() -> str:
    """Номер сборки из первой строки файла версии — или «неизвестна».

    ЧИТАЕТСЯ ОТ СКРИПТА, А НЕ ОТ `HOME`. Версия — свойство сборки: она лежит
    рядом с кодом, который ею подписан. В клоне пакета эти две папки — одна и
    та же, и промах не виден вовсе; в репозитории проекта рабочий корень выше
    (там `Разборы` и `.claude/`), а `ВЕРСИЯ` — в `Пакет/`, и проверка отвечала
    «неизвестна», пока клон той же сборки отвечал числом. Ранбук выкатки
    (блок 6) велит сверить эти два ответа перед публикацией — сверять было
    нечего.
    """
    try:
        first = (SCRIPT.parent / VERSION_FILE).read_text(
            encoding="utf-8-sig").splitlines()[0]
    except (OSError, IndexError):
        return "неизвестна"
    return first.strip() or "неизвестна"


# ---------------------------------------------------------------------------
# Проверки машины
# ---------------------------------------------------------------------------
def check_python(report: Report) -> None:
    running = sys.version_info[:3]
    said = ".".join(str(part) for part in running)
    if running[:2] >= MIN_PYTHON:
        report.ok("Python", said)
        return
    report.bad("Python", f"{said} — нужен {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее",
               "поставь свежий с https://www.python.org/downloads/ "
               "(на Windows — с галочкой «Add python.exe to PATH»)")


def check_env(report: Report, env: dict) -> dict:
    """Настройки и три значения в них. Возвращает то, что удалось прочитать.

    СУДИТ ПО ЗНАЧЕНИЯМ, А НЕ ПО ФАЙЛУ. Работа читает `.env`, а поверх него —
    окружение (`client.settings`), и без файла работает целиком: в облачной
    машине автомата `.env` НЕТ ВОВСЕ, там всё приезжает переменными. Пока
    проверка судила по одному лишь файлу, настроенная окружением машина получала
    «Не готово» и код 1, а связь с сервером не проверялась вовсе — `check_server`
    звали с пустым ответом. Человека посылали чинить исправное.

    Значения добываются ТЕМИ ЖЕ функциями, что и в работе (`client.access_key`,
    `client.base_url`), а не своими копиями: разъехавшись, проверка говорила бы
    «всё хорошо» там, где разбор уже отказывает.

    ФАЙЛ ИЩЕТСЯ ТАМ ЖЕ, ГДЕ ЕГО ИЩЕТ РАБОТА: от папки скриптов вверх, не выше
    корня рабочей копии (`client.settings`). Без потолка чужой `.env` в
    родительской папке клона отрапортовался бы «на месте», хотя рабочие скрипты
    его не читают.
    """
    found = client.find_dotenv(SCRIPT.parent, stop=HOME)
    values, broken = {}, []
    for name, getter, human in (("url", client.base_url, "Адрес сервера"),
                                ("key", client.access_key, "Ключ доступа")):
        try:
            values[name] = getter(env)
        except client.ClientError as error:
            broken.append((human, error.message))

    if found is not None:
        report.ok("Настройки", str(found))
    elif values:
        report.ok("Настройки", "файла .env нет — значения приехали окружением "
                               "(так работает облачная машина автомата)")
    else:
        # Ни файла, ни значений — только тогда заводим из образца, как и папки:
        # копия образца безопасна, ключей в ней нет. Человеку остаётся ровно одно
        # действие вместо двух, и оно названо ПУТЁМ, а не советом «скопируй файл».
        sample = HOME / SAMPLE_ENV
        if not sample.is_file():
            report.bad("Настройки", f"нет ни .env, ни образца {SAMPLE_ENV} в {HOME}",
                       "похоже, папка распакована не полностью — возьми её заново")
            return {}
        (HOME / ".env").write_bytes(sample.read_bytes())
        report.bad("Настройки", f"файла .env не было — создан из образца: {HOME / '.env'}",
                   "открой его и впиши три значения: адрес сервера и два ключа")
        return {}

    for human, message in broken:
        report.bad(human, message)
    if "url" in values:
        report.ok("Адрес сервера", values["url"])
    if "key" in values:
        # Длина, а не сам ключ: по ней видно обрезанную вставку, а показывать
        # ключ в консоли нельзя — вывод переживает сессию в истории терминала.
        report.ok("Ключ доступа", f"на месте, {len(values['key'])} символов")
    return values


def check_folders(report: Report) -> None:
    """Рабочие папки. Нет — заводим здесь же: это и есть «создание папок».

    Проверка, умеющая починить, лучше проверки, умеющей только пожаловаться, —
    но только там, где чинить безопасно. Пустая папка безопасна.
    """
    made = []
    for name in WORK_DIRS:
        folder = HOME / name
        if not folder.is_dir():
            folder.mkdir(parents=True, exist_ok=True)
            made.append(name)
    report.ok("Рабочие папки", ", ".join(WORK_DIRS)
              + (f" (создано: {', '.join(made)})" if made else ""))


def check_skills(report: Report) -> None:
    """Указатели на команды разложены по папкам клиентов и не устарели.

    Считает ТО ЖЕ, что и раскладывает (`install_skills.pointers`): второй
    счётчик однажды разошёлся бы с первым, и проверка хвалила бы неподключённое.
    """
    try:
        names = [name for name, _, _ in install_skills.skills()]
        root = install_skills.targets(home=False)
        stale = sum(1 for *_, same in install_skills.pointers(root) if not same)
    except (client.ClientError, OSError) as error:
        report.bad("Команды агенту", getattr(error, "message", str(error)),
                   "python install_skills.py")
        return
    if stale:
        report.bad("Команды агенту", f"не подключено или устарело: {stale}",
                   "python install_skills.py, потом перезапусти клиента")
        return
    report.ok("Команды агенту", ", ".join(names))


def check_recording(report: Report, env: dict) -> None:
    """Локальный путь к записи — тот, что остаётся, если Zoom-коннектор не встал.

    Это не проверка коннектора (до него скрипт не дотягивается — он в клиенте
    агента), а проверка ЗАПАСНОГО пути, который обязан работать всегда.

    Список папок спрашивается у `meeting.audio_dirs` — у того самого места,
    которое потом и будет там искать. Свой список показывал бы человеку не те
    папки, куда смотрит работа, и расходился бы молча.
    """
    places = [place for place in meeting.audio_dirs(env) if place.is_dir()]
    if places or (HOME / "Аудио").is_dir():
        shown = [str(place) for place in places] or [str(HOME / "Аудио")]
        report.ok("Куда класть запись", "; ".join(shown))
        return
    report.bad("Куда класть запись", "ни одной из папок поиска нет",
               f"положи запись в {HOME / 'Аудио'} или назови свои папки "
               f"в OBLAKO_AUDIO_DIRS")


def git(args: list, cwd=None, timeout: int = GIT_TIMEOUT_SEC) -> tuple:
    """Позвать git и вернуть (код возврата, вывод одной строкой).

    Отсутствие git — не поломка проверки, а её находка: код 127 и пустой вывод,
    а объясняет находку тот, кто спрашивал. Своё исключение здесь развалило бы
    весь прогон на машине, где git ещё не поставили, — а поставить его как раз и
    есть шаг мастера.

    `GIT_TERMINAL_PROMPT=0` — обязательный намордник. Без него `git fetch` в
    репозиторий, куда человека ещё не позвали, ВСТАЁТ и молча ждёт логин с
    паролем: проверка выглядит зависшей, а на самом деле ждёт ввода, которого в
    этом окне не будет.
    """
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        done = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=environment)
    except FileNotFoundError:               # git не поставлен вовсе
        return 127, ""
    except subprocess.TimeoutExpired:       # сеть встала — не ждём дольше края
        return 124, ""
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def check_library(report: Report, env: dict, offline: bool) -> None:
    """Клоны Библиотеки и имя автора коммитов.

    БИБЛИОТЕКА НЕОБЯЗАТЕЛЬНА. Пакет без неё разбирает планёрки ровно как прежде,
    поэтому ненастроенная Библиотека — не «нет», а третий исход (`Report.skip`):
    гнать руководителя отдела настраивать то, чем он не пользуется, значит
    научить его пропускать красные строки — и пропустит он заодно отозванный
    ключ.

    ЧТО СПРАШИВАЕТСЯ У КАЖДОГО АДРЕСА, И ПОЧЕМУ ИМЕННО ЭТО:

        клон на месте    папка есть и внутри `.git` — иначе писать некуда
        `origin` тот     клон ведёт в НАШ репозиторий, а не в чужой с тем же
                         именем: перепутанный `origin` отдаёт работу человека
                         не туда, и промах молчаливый
        сеть отвечает    `git fetch --dry-run` — живой ответ вместо «на вид
                         настроено»: снятому с репозитория человеку клон
                         выглядит исправным ровно до первой отправки

    `--offline` спрашивает только первые два: проверку зовут и там, где
    интернета нет вовсе, и тогда она обязана отвечать про машину, а не про сеть.

    ИМЯ АВТОРА — часть Библиотеки, а не украшение. История правок в ней и есть
    ответ на вопрос «кто это решил»; коммит без имени человека делает историю
    бесполезной ровно в тот день, когда её впервые спросят. Спрашивается оно у
    того же git и в той же папке, где будут коммиты, — глобальная настройка,
    перебитая локальной, иначе показывала бы не то имя, которым подпишется работа.

    АДРЕСА НЕ ПЕЧАТАЮТСЯ — только имена репозиториев. Токенов в них не бывает
    (доступ даёт `gh auth login`), но вывод переживает сессию в истории
    терминала, и правило «в консоль уходит имя, а не адрес» дешевле проверки
    каждого нового адреса на то, что в него вписали.
    """
    urls = client.library_urls(env)
    if not urls:
        report.skip("Библиотека", "не настроена")
        return

    folder = client.library_dir(HOME, env)
    ready, clones = [], []
    for url in urls:
        name = client.library_name(url)
        clone = folder / name
        if not (clone / ".git").exists():
            report.bad(f"Библиотека: {name}", f"клона нет в {folder}",
                       f"скажи агенту «настрой пакет» — он клонирует Библиотеку; "
                       f"сам: git clone <адрес из {client.LIBRARY_URLS_ENV}> "
                       f"\"{clone}\"")
            continue
        code, said = git(["-C", str(clone), "remote", "get-url", "origin"])
        if code == 127:
            report.bad("Библиотека", "git не найден",
                       "поставь git: Windows — winget install --id Git.Git -e, "
                       "macOS — brew install git")
            return
        if code != 0 or client.library_slug(said) != client.library_slug(url):
            report.bad(f"Библиотека: {name}", "клон ведёт в другой репозиторий",
                       f"удали папку {clone} и клонируй заново")
            continue
        if not offline:
            code, _ = git(["-C", str(clone), "fetch", "--dry-run", "origin"])
            if code != 0:
                report.bad(f"Библиотека: {name}", "сервер не отвечает или доступа нет",
                           "проверь связь; не проходит — попроси владельца позвать "
                           "тебя в репозиторий и сделай gh auth login")
                continue
        clones.append(clone)
        ready.append(name)

    if ready:
        report.ok("Библиотека доступна", ", ".join(ready))

    # Имя автора спрашивается в папке ПЕРВОГО клона: там будут коммиты, и
    # локальная настройка репозитория обязана быть видна. Клонов нет — вопрос
    # тот же, но к глобальной настройке.
    code, said = git(["config", "user.name"], cwd=clones[0] if clones else HOME)
    if code == 0 and said.strip():
        report.ok("Имя автора задано", said.strip())
        return
    report.bad("Имя автора задано", "нет — коммиты будут без человека",
               'git config --global user.name "Имя, как в Oblako"')


def check_automaton(report: Report, env: dict) -> None:
    """Автомат: подключён ли, и на месте ли здесь всё, что ему отдали.

    АВТОМАТ НЕОБЯЗАТЕЛЕН, как и Библиотека: без него планёрки расшифровывает этот
    компьютер, и «не подключён» — третий исход (`Report.skip`), а не «нет».

    ЧТО ЗДЕСЬ ВООБЩЕ МОЖНО ПРОВЕРИТЬ. Сам автомат — рутина в облаке claude.ai, и
    отсюда её не видно: ни её ключей, ни её сети, ни того, нажимает ли сервер
    кнопку. Живой ответ на это даёт пробный запуск мастера «подключи автомат», а
    не скрипт. Что видно с этой машины — три вещи, и по ним строка отвечает в
    ТРЁХ СОСТОЯНИЯХ:

        не подключён      мастер не проходили: в `.env` нет идентификатора
                          рутины (`OBLAKO_ROUTINE_ID`) — строка `[—]`, в счёт не
                          идёт;
        подключён         идентификатор есть, и здесь на месте всё, что автомату
                          отдали: сам скрипт `avtomat.py` и его инструкция
                          `Автомат/расшифровка.md` рядом (пакет целый), три
                          строки ключа Zoom, ключ Deepgram и адреса Библиотеки
                          в настройках — `[ок]`;
        подключён, но     идентификатор есть, а чего-то из этого нет — `[нет]` с
        не хватает        перечислением.

    ПОЧЕМУ `.env` ЭТОЙ МАШИНЫ ЧТО-ТО ЗНАЧИТ ДЛЯ ОБЛАКА. Рутина работает ТЕМИ ЖЕ
    ключами, что и разбор на этом компьютере: мастер переносит их отсюда в
    окружение рутины, а не заводит другие. Пропавший здесь ключ Zoom — почти
    всегда отозванный ключ, и тогда копия в облаке умерла молча; исчезнувшие
    адреса Библиотеки — транскрипту некуда лечь ни здесь, ни там. Строка не
    доказывает, что в облаке всё живо, — она говорит, что здесь нет признаков
    обратного, и называет следующий шаг, когда они есть.

    Идентификатор — адрес, а не секрет, и печатается: по нему человек находит
    рутину на claude.ai. Ключ-кнопка в `.env` не живёт вовсе, и проверять её
    здесь нечем — это нарочно.
    """
    routine = (env.get(client.ROUTINE_ENV) or "").strip()
    if not routine:
        report.skip("Автомат", "не подключён (по желанию: скажи агенту «подключи автомат»)")
        return

    missing = []
    home = SCRIPT.parent
    if not (home / AUTOMATON_SCRIPT).is_file() or not (home / AUTOMATON_TEMPLATE).is_file():
        missing.append(f"{AUTOMATON_SCRIPT} или {AUTOMATON_TEMPLATE} рядом со скриптами "
                       f"(пакет неполный — «обнови пакет»)")
    if any(not (env.get(name) or "").strip() for name in ZOOM_KEY_ENVS):
        missing.append("ключ Zoom — три строки в .env (файл «Записи Zoom — чтобы "
                       "помощник забирал их сам.md»)")
    if not (env.get("DEEPGRAM_API_KEY") or "").strip():
        missing.append("ключ Deepgram (DEEPGRAM_API_KEY)")
    if not client.library_urls(env):
        missing.append(f"адреса Библиотеки ({client.LIBRARY_URLS_ENV}) — транскрипту "
                       f"некуда лечь")
    if missing:
        report.bad("Автомат", "подключён, но не хватает: " + "; ".join(missing),
                   "восстанови это здесь и то же самое — в окружении рутины на claude.ai; "
                   "скажи агенту «подключи автомат», он пройдёт проверку заново")
        return
    report.ok("Автомат", f"подключён (рутина {routine})")


# ---------------------------------------------------------------------------
# Проверки сети
# ---------------------------------------------------------------------------
def check_deepgram(report: Report, env: dict) -> None:
    key = (env.get("DEEPGRAM_API_KEY") or "").strip()
    if not key:
        report.bad("Ключ Deepgram", "не задан",
                   "console.deepgram.com → API Keys → Create a New API Key, "
                   "вписать в DEEPGRAM_API_KEY")
        return
    if not (key.isascii() and key.isprintable()):
        report.bad("Ключ Deepgram", "испорчен: есть символы, которых в ключе не бывает",
                   "скопируй ключ заново целиком")
        return
    request = urllib.request.Request(
        DEEPGRAM_PROJECTS, headers={"Authorization": f"Token {key}"})
    # Дверь в сеть — та же единственная, что у своего сервера (`client.urlopen`):
    # проверка TLS и таймаут заданы там один раз, а тесты подменяют её целиком.
    try:
        with client.urlopen(request, client.TIMEOUT_READ_SEC):
            report.ok("Ключ Deepgram", "кабинет принял")
    except urllib.error.HTTPError as refusal:
        if refusal.code in (401, 403):
            report.bad("Ключ Deepgram", f"кабинет не принял (HTTP {refusal.code})",
                       "создай новый ключ в console.deepgram.com и перепиши "
                       "DEEPGRAM_API_KEY в .env")
        else:
            report.bad("Ключ Deepgram", f"кабинет ответил HTTP {refusal.code}",
                       "повтори позже; не проходит — покажи это разработчику")
    except OSError as broken:
        report.bad("Ключ Deepgram", f"до Deepgram не достучались ({type(broken).__name__})",
                   "проверь связь и повтори")


def check_zoom_transcript(report: Report, env: dict) -> None:
    """Третье право ключа Zoom — живым запросом, а не «на вид» (#469).

    ЗАЧЕМ ОТДЕЛЬНАЯ СТРОКА. Без права `cloud_recording:read:meeting_transcript:
    admin` всё работает — и потому поломка не видна: запись забирается, текст
    пишется, автомат отчитывается «готово». Не хватает только имён говорящих, а
    заметит это человек через сутки, открыв в Библиотеке «Спикер 0–5». Ровно так
    и вышло 09.09.2026 на первой боевой планёрке.

    ПРАВО ПРОВЕРЯЕТСЯ ЗАПРОСОМ ПО ПОСЛЕДНЕЙ ЗАПИСИ, и другого способа нет: Zoom
    не отдаёт список прав ключа. Ответ «транскрипта у этой записи нет» — тоже
    успех: право Zoom проверяет ПЕРВЫМ, и до разговора о самом транскрипте
    отказ по праву не доходит.

    ПРОПАВШЕЕ ПРАВО НАЗЫВАЕТСЯ МАШИННЫМ ИМЕНЕМ: в кабинете Zoom права ищут
    строкой, и «право на транскрипт» человек там не найдёт.
    """
    name = "Транскрипт помощника Zoom"
    if any(not (env.get(item) or "").strip() for item in ZOOM_KEY_ENVS):
        report.skip(name, "ключа Zoom нет — записи забирают руками")
        return
    since, upto = zoom_pull.window_for(None, zoom_pull.WINDOW)
    try:
        token = zoom_pull.access_token(env)
        found = zoom_pull.recordings(token, since, upto)
        fresh = next((one for one in found if (one.get("uuid") or "").strip()), None)
        if fresh is None:
            report.skip(name, "в облаке нет ни одной записи — право проверить не на чем")
            return
        _, missing = zoom_pull.assistant_transcript(token, fresh["uuid"])
    except zoom_pull.Usage as own:
        report.bad(name, str(own).splitlines()[0], "поправь ключ Zoom в .env")
        return
    except zoom_pull.Refused as refusal:
        report.bad(name, str(refusal).splitlines()[0],
                   "проверь права ключа Zoom: файл «Записи Zoom — чтобы помощник "
                   "забирал их сам.md», шаг 1")
        return
    except zoom_pull.Silent as broken:
        report.bad(name, str(broken).splitlines()[0], "проверь связь и повтори")
        return
    if missing == zoom_pull.NO_SCOPE:
        report.bad(name, f"у ключа нет права {zoom_pull.TRANSCRIPT_SCOPE}",
                   "кабинет Zoom → своё приложение Server-to-Server OAuth → Scopes → "
                   "добавь это право (файл «Записи Zoom — чтобы помощник забирал их "
                   "сам.md», шаг 1). Без него имена говорящих приходят через полчаса "
                   "или не приходят вовсе")
        return
    report.ok(name, "право на месте" if missing is None
              else "право на месте (у последней записи транскрипта нет — "
                   "помощник на встрече не работал)")


def check_server(report: Report, access: dict) -> None:
    """Живой вызов сервера: адрес, ключ, права и версия формата — одним махом."""
    if "url" not in access or "key" not in access:
        report.bad("Связь с сервером", "нечем: нет адреса или ключа",
                   "заполни .env и запусти проверку снова")
        return
    try:
        snapshot = client.call("GET", "/api/pc/export-tasks",
                               url=access["url"], key=access["key"],
                               timeout=client.TIMEOUT_READ_SEC)
    except client.Refused as refusal:
        report.bad("Связь с сервером", refusal.message,
                   "чаще всего ключ отозван — выпусти новый кнопкой «Ключ доступа» "
                   "в настройках Mini App")
        return
    except client.ClientError as broken:     # сеть, TLS, чужой ответ, битый ключ
        report.bad("Связь с сервером", broken.message, "проверь связь и OBLAKO_BASE_URL")
        return

    # Шапка снимка словами — та же, что печатает выгрузка перед планёркой:
    # человек сверяет по ней «мой ли это человек» одним и тем же текстом.
    report.ok("Связь с сервером", fetch_tasks.describe(snapshot))
    people = snapshot.get("people") or []
    # Своих людей нет — не поломка установки, но и разбирать планёрку не с кем:
    # человека ещё не завели руководителем отдела.
    if not people:
        report.bad("Состав", "по этому ключу не видно ни одного человека",
                   "скажи владельцу системы: отдел ещё не заведён или ты не его руководитель")

    try:
        client.check_export(snapshot)
    except client.ClientError as mismatch:
        report.bad("Версия формата", mismatch.message)
        return
    report.ok("Версия формата", f"v{client.PACKAGE_FORMAT_VERSION} — сервер и пакет сходятся")


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    client.setup_console()
    parser = argparse.ArgumentParser(description="Проверка установки пакета Oblako")
    parser.add_argument("--offline", action="store_true",
                        help="без сети: только то, что видно на этой машине")
    args = parser.parse_args(argv)

    env = client.settings(SCRIPT)
    key = env.get(client.KEY_ENV)
    report = Report()
    print(f"Пакет Oblako {package_version()} · проверка установки")
    try:
        check_python(report)
        access = check_env(report, env)
        check_folders(report)
        check_skills(report)
        check_recording(report, env)
        check_library(report, env, args.offline)
        check_automaton(report, env)
        if args.offline:
            print("  [—]    Сеть не проверялась (--offline)")
        else:
            check_deepgram(report, env)
            check_zoom_transcript(report, env)
            check_server(report, access)
    except Exception:                       # трассировка — только очищенная от ключа
        return client.crash(key)

    good = report.total - report.failed
    if report.failed:
        print(f"\nНе готово: {good} из {report.total}. Почини отмеченное и запусти "
              f"проверку снова: python setup_check.py")
    else:
        print(f"\nГотово: {good} из {good}. Можно работать — скажи агенту "
              f"«разбери планёрку».")
    return client.EXIT_OK if not report.failed else client.EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())

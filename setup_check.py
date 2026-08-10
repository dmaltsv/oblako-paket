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
    папки           `Разборы` и `Аудио` есть (нет — заводим тут же)
    команды агенту  указатели разложены и не устарели
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
import sys
import urllib.error
import urllib.request
from pathlib import Path

import fetch_tasks
import install_skills
import meeting
import oblako_client as client

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


def package_version() -> str:
    """Номер сборки из первой строки файла версии — или «неизвестна»."""
    try:
        first = (HOME / VERSION_FILE).read_text(encoding="utf-8-sig").splitlines()[0]
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
    """Файл настроек и три значения в нём. Возвращает то, что удалось прочитать.

    Значения добываются ТЕМИ ЖЕ функциями, что и в работе (`client.access_key`,
    `client.base_url`), а не своими копиями: разъехавшись, проверка говорила бы
    «всё хорошо» там, где разбор уже отказывает.
    """
    found = client.find_dotenv(HOME)
    if found is None:
        # Заводим из образца прямо здесь — как и папки: копия образца безопасна,
        # ключей в ней нет. Человеку остаётся ровно одно действие вместо двух, и
        # оно названо ПУТЁМ, а не советом «скопируй файл».
        sample = HOME / SAMPLE_ENV
        if not sample.is_file():
            report.bad("Настройки", f"нет ни .env, ни образца {SAMPLE_ENV} в {HOME}",
                       "похоже, папка распакована не полностью — возьми её заново")
            return {}
        (HOME / ".env").write_bytes(sample.read_bytes())
        report.bad("Настройки", f"файла .env не было — создан из образца: {HOME / '.env'}",
                   "открой его и впиши три значения: адрес сервера и два ключа")
        return {}
    report.ok("Настройки", str(found))

    values = {}
    for name, getter, human in (("url", client.base_url, "Адрес сервера"),
                                ("key", client.access_key, "Ключ доступа")):
        try:
            values[name] = getter(env)
        except client.ClientError as error:
            report.bad(human, error.message)
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
        if args.offline:
            print("  [—]    Сеть не проверялась (--offline)")
        else:
            check_deepgram(report, env)
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

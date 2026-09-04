# -*- coding: utf-8 -*-
"""library.py — механика Библиотеки поверх git: путь, слово, подпись, повторы (#420).

ЗАЧЕМ ОН ЕСТЬ. Библиотека — это репозитории git с документами: подготовки к
встречам, повестки, сводки недели, транскрипты, карты проектов. Ходить в них
агент мог бы и голыми командами git — но каждый раз чуть по-своему: сегодня файл
лёг бы в «Сводки», завтра в «сводки»; коммит ушёл бы без слова человека; `push`
при отставании превратился бы в импровизацию, а импровизация в git кончается
`--force`. Здесь эти решения заданы КОДОМ — ровно как порядок разбора планёрки
задан `meeting.py`. За агентом остаётся одно: СОСТАВИТЬ ТЕКСТ. Куда его положить,
чьим именем подписать и когда он попадёт в Библиотеку, решает скрипт.

ГЕЙТ «ЗАПИШИ» — ОДИН НА ВЕСЬ ПАКЕТ. Слово человека судит `oblako_client`, та же
функция, что стоит на дороге разбора планёрки: «ок» и «понял» командой не
считаются, «не записывай» — отказ. Второй судья рядом с первым однажды разошёлся
бы с ним, и одно и то же слово значило бы в двух местах разное.

ПРАВИЛО ПУТИ. Вид документа определяет папку и имя файла целиком — выбора у
агента нет:

    prep        Подготовка/<дата>/<Имя>.md          --name
    agenda      Повестки/<дата>.md
    summary     Сводки/<дата>.md
    transcript  Транскрипты/<дата> <название>.md    --title
    draft       Черновики/<дата> <что>.md           --title
    map         Карта проектов.md

У совета отделов нет — его файлы лежат от корня репозитория. Любой другой
репозиторий Библиотеки хранит документы отделов, поэтому запись в него требует
`--team`, и всё уходит внутрь `Отделы/<Отдел>/`.

АВТОМАТ ПИШЕТ ТОЛЬКО В ДВЕ ПАПКИ. `--as-automaton "<Имя>"` подписывает коммит
«Автомат: <Имя>» и разрешает ровно два вида — `transcript` и `draft`. Правило
держится не инструкцией рутине, а этим кодом: инструкцию модель однажды поймёт
иначе, а отказ скрипта одинаков всегда. Слово человека автомат не приносит — за
клавиатурой его нет; его решение живёт выше, на серии или на встрече, а здесь
гейтом служит сам путь. Слово, если оно всё-таки передано, судится тем же
правилом: «не записывай» останавливает и автомат.

СКРИПТ НЕ ВЫБИРАЕТ САМ. Ни репозиторий (`--repo` называется явно), ни отдел
(`--team` — умолчания «он же один» нет, решение 3.5.21), ни файл, лежащий сразу в
двух клонах (`log`/`diff` показывают оба имени и ждут `--repo`). Молчаливый выбор
здесь дороже отказа: сводка розницы, легшая в папку склада, читается как
настоящая.

СЕТЬ НУЖНА НЕ ВСЕМ КОМАНДАМ. `status` не ходит наружу вовсе: отставание он
называет по последнему `pull` — иначе «покажи, как дела» зависало бы в поезде.
`put` перед записью пробует обновиться, но неудача обновления его не
останавливает: коммит местный, и судить отправку будет `push`.

КОДЫ ВЫХОДА — те же, что у всего контура ПК (`oblako_client`):

    0  сделано
    1  не с чем работать: нет слова, нет файла, чужой вид для автомата, конфликт
    2  удалённая сторона не пустила: нет прав на репозиторий
    3  до Библиотеки не достучались: сеть, DNS, адрес

ТОКЕНЫ НЕ ПОКАЗЫВАЮТСЯ. Адрес репозитория бывает с токеном внутри
(`https://x:токен@github.com/...`), и git охотно повторяет его в тексте ошибки.
Всё печатаемое проходит через `clean`: сам токен вырезает `oblako_client.redact`,
а логин с паролем в любом адресе — правило ниже. В выводе адрес виден без них.

Команды:

    python library.py status [--json]
    python library.py pull [--repo sovet]
    python library.py put --repo sovet --kind prep --file Черновик.md
                          --word "запиши" --name "Лев" [--date 07.09.26]
    python library.py push [--repo sovet]
    python library.py log  --path "Карта проектов.md" [-n 5] [--repo sovet]
    python library.py diff --path "Карта проектов.md" [--repo sovet]

Зависимостей нет — только стандартная библиотека и сам git. Windows и macOS —
один путь.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import oblako_client as client

SCRIPT = Path(__file__).resolve()

# --- настройки из `.env` ----------------------------------------------------
URLS_ENV = "OBLAKO_LIBRARY_URLS"        # адреса репозиториев через `;`
DIR_ENV = "OBLAKO_LIBRARY_DIR"          # где держать клоны (по умолчанию — рядом с командами)
DEFAULT_DIR = "Библиотека"

# Репозиторий совета отделов не знает: его документы лежат от корня. Список, а не
# признак «в имени нет отделов»: репозиториев Библиотеки может стать больше, и
# каждый новый обязан назваться здесь явно — иначе сводка отдела молча легла бы
# в корень чужого репозитория.
ROOT_REPOS = ("sovet",)
TEAMS_DIR = "Отделы"

# Даты В ИМЕНАХ ФАЙЛОВ — ISO: имена сортируются как строки, и «2026-09-04» встаёт
# в список по порядку, а «04.09.26» — по числу дня. Человек и агент при этом
# называют дату так же, как везде в пакете (ДД.ММ.ГГ), поэтому принимаются оба
# написания, а пишется одно: иначе один и тот же день породил бы два файла.
ISO_DATE = "%Y-%m-%d"
SHORT_DATE = "%d.%m"                    # как дата выглядит в сообщении коммита
DATE_FORMATS = ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d")

# --- виды документов: путь и сообщение коммита ------------------------------
# `needs` — что обязан назвать вызывающий сверх даты. Сообщения стандартные и
# пишутся ЗДЕСЬ, а не агентом: история Библиотеки читается глазами, и «правки» с
# «обновил файл» вперемешку с настоящими строками превратили бы её в шум.
KINDS = {
    "prep": {
        "path": "Подготовка/{date}/{name}.md",
        "needs": "name",
        "message": "Подготовка к {dative} {short} — {name}",
        "what": "подготовка человека к встрече",
    },
    "agenda": {
        "path": "Повестки/{date}.md",
        "needs": None,
        "message": "Повестка {genitive} {short}",
        "what": "повестка встречи",
    },
    "summary": {
        "path": "Сводки/{date}.md",
        "needs": None,
        "message": "Сводка недели {plain} {short}",
        "what": "сводка недели",
    },
    "transcript": {
        "path": "Транскрипты/{date} {title}.md",
        "needs": "title",
        "message": "Транскрипт {genitive} {short}",
        "what": "расшифровка встречи",
    },
    "draft": {
        "path": "Черновики/{date} {title}.md",
        "needs": "title",
        "message": "Черновик {genitive} {short} — {title}",
        "what": "черновик (пишет автомат)",
    },
    "map": {
        "path": "Карта проектов.md",
        "needs": None,
        "message": "Карта проектов {plain} — правка {short}",
        "what": "карта проектов",
    },
}

# Что разрешено автомату — и вид, и папка. Проверяются ОБА: вид отсекает вызов
# сразу, папка страхует на случай, если правило пути когда-нибудь изменят.
AUTOMATON_KINDS = ("transcript", "draft")
AUTOMATON_DIRS = ("Транскрипты", "Черновики")
AUTOMATON_SIGN = "Автомат: {name}"

# Части пути, названные человеком (имя, название, отдел), путём быть не должны:
# «../..» в `--name` увёл бы запись за пределы клона. Заодно отсекаются символы,
# на которых спотыкается файловая система Windows.
FORBIDDEN_IN_NAME = re.compile(r"[\\/:*?\"<>|]")

# --- git --------------------------------------------------------------------
GIT_TIMEOUT_SEC = 120                   # молчащая сеть не должна вешать скрипт навсегда
PUSH_TRIES = 3                          # при отставании: забрать чужое и повторить

# Окружение git задано ЯВНО и одинаково на обеих ОС:
#   · `GIT_TERMINAL_PROMPT=0` — не спрашивать логин: за клавиатурой скрипт, и
#     вопрос «Username for https://github.com» повесил бы рутину автомата до
#     таймаута рутины, а не до таймаута сети;
#   · `LC_ALL=C` — сообщения git по-английски. Отказ разбирается по их ТЕКСТУ
#     (другого признака у git нет), а на локализованной машине русский перевод
#     «Permission denied» не совпал бы ни с одной строкой, и отказ по правам
#     поехал бы кодом 1 вместо 2.
GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "LC_ALL": "C",
    "LANGUAGE": "",
}
# `core.quotepath=false` — имена файлов кириллицей приходят как есть, а не
# «\320\237...»: их печатают человеку.
GIT_OPTIONS = ("--no-pager", "-c", "core.quotepath=false")

# Отказ удалённой стороны от недоступности отличается ТОЛЬКО текстом git, и
# порядок проверки важен: отказ по правам он тоже заканчивает словами «Could not
# read from remote repository», поэтому права смотрятся первыми.
REFUSED_MARKS = (
    "permission denied", "denied to", "authentication failed", "invalid username or password",
    "403 forbidden", "401 unauthorized", "returned error: 403", "returned error: 401",
    "access denied", "repository not found", "not authorized",
    "write access to repository not granted", "support for password authentication",
)
NO_SERVER_MARKS = (
    "could not resolve host", "could not resolve hostname", "failed to connect",
    "connection timed out", "connection refused", "network is unreachable",
    "operation timed out", "timed out", "the remote end hung up", "early eof",
    "could not read from remote repository", "does not appear to be a git repository",
    "unable to access", "ssl", "gnutls", "proxy", "no route to host",
)
CONFLICT_MARKS = ("conflict", "could not apply", "resolve all conflicts")
DIRTY_MARKS = ("cannot pull with rebase", "unstaged changes", "uncommitted changes",
               "please commit or stash")
BEHIND_MARKS = ("non-fast-forward", "fetch first", "behind its remote",
                "updates were rejected", "[rejected]")
NO_UPSTREAM_MARKS = ("no upstream branch", "has no upstream")

CONFLICT_FILE = re.compile(r"conflict \([^)]*\): merge conflict in (.+)", re.IGNORECASE)
# Логин с паролем в любом адресе: `https://x:токен@host/…` → `https://<токен скрыт>@host/…`
URL_CREDENTIALS = re.compile(r"(?<=://)[^/\s@]+(?=@)")


# ---------------------------------------------------------------------------
# Репозитории Библиотеки
# ---------------------------------------------------------------------------
class Repo:
    """Один репозиторий Библиотеки: имя, адрес и место клона на этой машине."""

    def __init__(self, name: str, url: str, path: Path):
        self.name = name
        self.url = url
        self.path = path

    @property
    def root_level(self) -> bool:
        """Файлы лежат от корня (совет) или внутри `Отделы/<Отдел>/` (всё прочее)."""
        return self.name.lower() in ROOT_REPOS

    @property
    def cloned(self) -> bool:
        return (self.path / ".git").exists()


def repo_name(url: str) -> str:
    """Имя репозитория — последний сегмент адреса, без `.git`.

    Разделитель и `/`, и `\\`: в `.env` бывает не только адрес GitHub, но и путь
    к папке (так Библиотеку показывают тестам и так её пробуют на своей машине).
    """
    tail = re.split(r"[\\/]", url.strip().rstrip("/\\"))[-1]
    return tail[:-4] if tail.lower().endswith(".git") else tail


def library_dir(env: dict) -> Path:
    """Куда кладутся клоны: `OBLAKO_LIBRARY_DIR` или `Библиотека` рядом с командами.

    Относительный путь считается от корня рабочей копии — того же, который
    называет место папке `Разборы`: разъехавшись, они легли бы в разные корни.
    """
    stated = (env.get(DIR_ENV) or "").strip()
    if not stated:
        return client.work_root(SCRIPT) / DEFAULT_DIR
    folder = Path(stated).expanduser()
    return folder if folder.is_absolute() else client.work_root(SCRIPT) / folder


def repos(env: dict) -> list:
    """Все репозитории Библиотеки из `.env` — или отказ с объяснением."""
    raw = (env.get(URLS_ENV) or "").strip()
    if not raw:
        raise client.Usage(
            f"Библиотека не настроена: в .env нет {URLS_ENV}",
            [f"{URLS_ENV}=<адрес репозитория>;<адрес репозитория> — через точку с запятой",
             "адреса и доступ заводит мастер установки (скилл ustanovka)"])
    folder = library_dir(env)
    found: list = []
    for url in [part.strip() for part in raw.split(";")]:
        if not url:
            continue
        name = repo_name(url)
        if not name:
            raise client.Usage(f"Из адреса не вычитать имя репозитория: {safe_url(url)}")
        if any(one.name.lower() == name.lower() for one in found):
            raise client.Usage(
                f"В {URLS_ENV} два репозитория с одним именем: «{name}»",
                ["имя — последний кусок адреса, и по нему их различают команды",
                 "переименуй один из них или убери лишний адрес"])
        found.append(Repo(name, url, folder / name))
    if not found:
        raise client.Usage(f"{URLS_ENV} задан, но пуст")
    return found


def chosen(args, env: dict) -> list:
    """Названный `--repo` или все репозитории Библиотеки."""
    named = (getattr(args, "repo", None) or "").strip()
    found = repos(env)
    if not named:
        return found
    return [pick(named, found)]


def pick(named: str, found: list) -> Repo:
    for repo in found:
        if repo.name.lower() == named.strip().lower():
            return repo
    raise client.Usage(
        f"Репозитория «{named}» в Библиотеке нет",
        [f"известны: {', '.join(one.name for one in found)}",
         f"список задаёт {URLS_ENV} в .env"])


def one_repo(named, env: dict) -> Repo:
    """Репозиторий записи. Умолчания нет — назвать его обязан вызывающий."""
    if not (named or "").strip():
        raise client.Usage(
            "Не назван репозиторий: --repo <имя>",
            [f"имена показывает library.py status (их задаёт {URLS_ENV} в .env)",
             "угадывать репозиторий система не вправе: их у тебя несколько"])
    return pick(named, repos(env))


# ---------------------------------------------------------------------------
# Печать: ни ключа, ни токена
# ---------------------------------------------------------------------------
def secrets(env: dict) -> list:
    """Всё, чего не должно быть в выводе: ключ доступа и пароли из адресов."""
    found = []
    key = (env.get(client.KEY_ENV) or "").strip()
    if key:
        found.append(key)
    for url in (env.get(URLS_ENV) or "").split(";"):
        match = URL_CREDENTIALS.search(url)
        if match:
            found.extend(part for part in match.group(0).split(":") if part)
    return found


def clean(text, env: dict) -> str:
    """Последний рубеж перед печатью: вырезать ключи и логин с паролем из адресов."""
    return URL_CREDENTIALS.sub("<токен скрыт>", client.redact(str(text), secrets(env)))


def safe_url(url: str) -> str:
    """Адрес без логина и пароля — таким его показывают человеку."""
    return URL_CREDENTIALS.sub("<токен скрыт>", url.strip())


def say(text, env: dict) -> None:
    print(clean(text, env))


# ---------------------------------------------------------------------------
# git через subprocess
# ---------------------------------------------------------------------------
def run_git(cwd, argv: list, timeout: int = GIT_TIMEOUT_SEC):
    """Позвать git и вернуть результат целиком. Ошибку разбирает вызывающий."""
    command = ["git", *GIT_OPTIONS, *argv]
    try:
        return subprocess.run(
            command, cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, **GIT_ENV},
            text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        raise client.Usage(
            "На этой машине нет git — без него Библиотека не работает",
            ["Windows: winget install --id Git.Git",
             "macOS: brew install git",
             "после установки закрой и открой терминал заново"]) from None
    except subprocess.TimeoutExpired:
        raise client.Unreachable(
            f"git молчит дольше {timeout} с — похоже, сети нет",
            ["попробуй позже: файл и коммит никуда не делись"]) from None


def git_text(cwd, argv: list):
    """Вывод git одной строкой — или None, если команда отказала."""
    result = run_git(cwd, argv)
    return result.stdout.strip() if result.returncode == 0 else None


def output(result) -> str:
    return f"{result.stdout or ''}\n{result.stderr or ''}".strip()


def tail(text: str, lines: int = 3) -> list:
    """Последние строки git — их и показывают человеку вместо всего потока."""
    said = [line.strip() for line in text.splitlines() if line.strip()]
    return said[-lines:]


def remote_error(what: str, result, env: dict) -> client.ClientError:
    """Отказ git наружу: права — код 2, недоступность — 3, всё прочее — 1."""
    text = output(result)
    low = text.lower()
    details = [clean(line, env) for line in tail(text)]
    if any(mark in low for mark in REFUSED_MARKS):
        return client.Refused(
            f"{what}: Библиотека не пустила",
            details + ["проверь, что тебя добавили в репозиторий и доступ не истёк",
                       "заводит доступ владелец Библиотеки"])
    if any(mark in low for mark in NO_SERVER_MARKS):
        return client.Unreachable(
            f"{what}: до Библиотеки не достучались",
            details + ["это сеть, а не отказ: повтори, когда связь вернётся"])
    return client.Usage(f"{what}: git отказался", details)


# ---------------------------------------------------------------------------
# Обновление и отправка
# ---------------------------------------------------------------------------
def clone(repo: Repo, env: dict) -> None:
    """Завести клон, которого ещё нет. Зовётся только из `pull`."""
    repo.path.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(repo.path.parent, ["clone", repo.url, repo.path.name])
    if result.returncode != 0:
        raise remote_error(f"{repo.name}: клон не завёлся", result, env)
    say(f"{repo.name}: клона не было — завёл: {repo.path}", env)


def in_rebase(repo: Repo) -> bool:
    """Осталось ли начатое слияние. Проверяется ПОСЛЕ отмены, а не вместо неё."""
    git_dir = git_text(repo.path, ["rev-parse", "--absolute-git-dir"]) or str(repo.path / ".git")
    return any((Path(git_dir) / name).exists() for name in ("rebase-merge", "rebase-apply"))


def conflict_stop(repo: Repo, text: str, env: dict) -> client.ClientError:
    """Один файл правили с двух сторон. Начатое слияние отменяется, работа встаёт.

    ОТМЕНА ОБЯЗАТЕЛЬНА. Оставить рабочую копию посреди слияния значит оставить
    человеку, который не программист, файл с маркерами `<<<<<<<` и репозиторий,
    где не работает ни одна следующая команда. Отмена возвращает всё к тому, что
    было: свой коммит цел, чужие правки — в Библиотеке. Если отмена почему-то не
    удалась, об этом говорится прямо и называется команда выхода — молча оставить
    человека в таком состоянии нельзя.
    """
    files = [name.strip() for name in CONFLICT_FILE.findall(text)]
    run_git(repo.path, ["rebase", "--abort"])
    where = ", ".join(f"«{name}»" for name in files) or "один и тот же файл"
    details = [
        "начатое слияние отменено: рабочая копия чистая, твой коммит на месте",
        f'чужую версию покажет library.py log --path "{files[0] if files else "<файл>"}"',
        "по правилам Библиотеки у каждого файла один автор — договоритесь, кто пишет этот",
        "свести две версии руками — минута для того, кто ведёт систему; позови его",
    ]
    if in_rebase(repo):
        details.insert(0, "ВАЖНО: слияние осталось незавершённым, отменить его — "
                          f'git -C "{repo.path}" rebase --abort')
    return client.Usage(f"{repo.name}: {where} правили с двух сторон — "
                        f"свести автоматически нельзя", details)


def pull_rebase(repo: Repo, env: dict) -> None:
    """`git pull --rebase` — или понятный отказ вместо трассировки."""
    result = run_git(repo.path, ["pull", "--rebase"])
    if result.returncode == 0:
        return
    text = output(result)
    low = text.lower()
    if any(mark in low for mark in CONFLICT_MARKS):
        raise conflict_stop(repo, text, env)
    if any(mark in low for mark in DIRTY_MARKS):
        raise client.Usage(
            f"{repo.name}: в клоне есть незаписанные правки — обновиться поверх них нельзя",
            tail(text) + ["что именно правлено, покажет library.py status",
                          "запиши их (library.py put) или убери — и повтори"])
    raise remote_error(f"{repo.name}: обновить не вышло", result, env)


def push_one(repo: Repo, env: dict) -> None:
    """Отправить свои коммиты. Библиотека ушла вперёд — забрать чужое и повторить."""
    for attempt in range(1, PUSH_TRIES + 1):
        result = run_git(repo.path, ["push"])
        if result.returncode == 0:
            done = "отправлять нечего" if "up-to-date" in output(result).lower() else "отправлено"
            say(f"{repo.name}: {done}", env)
            return
        text = output(result)
        low = text.lower()
        if any(mark in low for mark in NO_UPSTREAM_MARKS):
            # Свежая ветка: у неё ещё нет пары в Библиотеке — назвать её явно.
            branch = git_text(repo.path, ["rev-parse", "--abbrev-ref", "HEAD"]) or "HEAD"
            result = run_git(repo.path, ["push", "--set-upstream", "origin", branch])
            if result.returncode == 0:
                say(f"{repo.name}: отправлено (ветка {branch} заведена в Библиотеке)", env)
                return
            text = output(result)
            low = text.lower()
        if any(mark in low for mark in BEHIND_MARKS):
            if attempt == PUSH_TRIES:
                raise client.Usage(
                    f"{repo.name}: {PUSH_TRIES} раза подряд Библиотека уходила вперёд — "
                    f"отправить не вышло",
                    ["в неё пишут прямо сейчас: повтори library.py push через минуту",
                     "твой коммит на месте, ничего не потеряно"])
            say(f"{repo.name}: Библиотека ушла вперёд — забираю чужое и повторяю "
                f"(попытка {attempt + 1} из {PUSH_TRIES})", env)
            pull_rebase(repo, env)
            continue
        raise remote_error(f"{repo.name}: отправить не вышло", result, env)


# ---------------------------------------------------------------------------
# Правило пути и подпись
# ---------------------------------------------------------------------------
def library_date(stated) -> date:
    """Дата документа. Без неё — сегодня; иначе ДД.ММ.ГГ или ISO."""
    said = (stated or "").strip()
    if not said:
        return date.today()
    for shape in DATE_FORMATS:
        try:
            return datetime.strptime(said, shape).date()
        except ValueError:
            continue
    raise client.Usage(
        f"Дату не разобрать: {said!r}",
        [f"формат — ДД.ММ.ГГ (например {date.today().strftime('%d.%m.%y')}) "
         f"или {date.today().strftime(ISO_DATE)}"])


def safe_part(value, flag: str, what: str) -> str:
    """Часть имени файла, названная человеком. Путём она быть не может."""
    said = (value or "").strip()
    if not said:
        raise client.Usage(
            f"Не назван {what}: {flag} «…»",
            ["без него правило пути не даёт имени файла — угадывать система не вправе"])
    if said in (".", "..") or FORBIDDEN_IN_NAME.search(said):
        raise client.Usage(
            f"{flag}: «{said}» — это путь, а не {what}",
            ['в имени не бывает / \\ : * ? " < > | — оно кладётся в имя файла как есть'])
    return said


def about(repo: Repo, team) -> dict:
    """Как встреча называется в сообщении коммита: у совета одно, у отдела другое."""
    if repo.root_level:
        return {"dative": "совету", "genitive": "совета", "plain": "совета"}
    return {"dative": f"планёрке {team}", "genitive": f"планёрки {team}", "plain": str(team)}


def place(repo: Repo, kind: str, when: date, args) -> tuple:
    """Куда лечь и как подписаться: путь внутри клона и сообщение коммита."""
    rule = KINDS.get(kind)
    if rule is None:
        raise client.Usage(
            f"Вида «{kind}» не бывает: --kind <вид>",
            [f"{name} — {one['what']}" for name, one in KINDS.items()])
    team = None if repo.root_level else safe_part(getattr(args, "team", None), "--team", "отдел")
    fields = {
        "date": when.strftime(ISO_DATE),
        "short": when.strftime(SHORT_DATE),
        "name": "", "title": "",
        **about(repo, team),
    }
    if rule["needs"] == "name":
        fields["name"] = safe_part(getattr(args, "name", None), "--name",
                                   "автор (имя, как в Oblako)")
    if rule["needs"] == "title":
        fields["title"] = safe_part(getattr(args, "title", None), "--title",
                                    "название документа")
    inside = rule["path"].format(**fields)
    target = inside if repo.root_level else f"{TEAMS_DIR}/{team}/{inside}"
    return target, rule["message"].format(**fields)


def automaton_allows(target: str, repo: Repo) -> bool:
    """Автомату открыты две папки — и это проверяется по САМОМУ ПУТИ, не по виду."""
    parts = target.split("/")
    if not repo.root_level:
        parts = parts[2:]
    return bool(parts) and parts[0] in AUTOMATON_DIRS


def identity(repo: Repo) -> dict:
    """Имя и почта клона — ОДНИМ запросом: их спрашивает каждая запись."""
    said = git_text(repo.path, ["config", "--get-regexp", r"^user\.(name|email)$"]) or ""
    found = {}
    for line in said.splitlines():
        key, _, value = line.strip().partition(" ")
        found[key.strip()] = value.strip()
    return found


def author_of(repo: Repo, sign: str) -> list:
    """Чем подписать коммит: именем клона или «Автомат: <Имя>».

    Имя и почта КЛОНА проверяются в обоих случаях: без них git не даёт
    зафиксировать ничего и объясняет это семью строками про `git config`. Отказ
    здесь короче и называет то же самое своими словами.
    """
    who = identity(repo)
    name, email = who.get("user.name"), who.get("user.email")
    if not name or not email:
        raise client.Usage(
            f"{repo.name}: не задано, чьим именем подписывать коммиты",
            [f'git -C "{repo.path}" config user.name "Имя, как в Oblako"',
             f'git -C "{repo.path}" config user.email "почта@пример.рф"',
             "это делает мастер установки (скилл ustanovka), шаг «Библиотека»"])
    return ["-c", f"user.name={AUTOMATON_SIGN.format(name=sign)}"] if sign else []


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------
def status_of(repo: Repo) -> dict:
    """Карточка репозитория. В сеть НЕ ходит: отставание — по последнему `pull`."""
    card = {"repo": repo.name, "url": safe_url(repo.url), "path": str(repo.path),
            "clone": repo.cloned, "branch": None, "behind": None, "ahead": None,
            "dirty": [], "author": None, "email": None}
    if not repo.cloned:
        return card
    card["branch"] = git_text(repo.path, ["rev-parse", "--abbrev-ref", "HEAD"])
    who = identity(repo)
    card["author"] = who.get("user.name")
    card["email"] = who.get("user.email")
    counted = git_text(repo.path, ["rev-list", "--count", "--left-right", "@{upstream}...HEAD"])
    if counted:
        behind, _, ahead = counted.partition("\t")
        card["behind"] = int(behind.strip() or 0)
        card["ahead"] = int(ahead.strip() or 0)
    dirty = git_text(repo.path, ["status", "--porcelain"]) or ""
    card["dirty"] = [line[3:].strip() for line in dirty.splitlines() if line.strip()]
    return card


def status_lines(cards: list, folder: Path) -> list:
    said = [f"Библиотека на этой машине: {folder}"]
    for card in cards:
        if not card["clone"]:
            said.append(f"{card['repo']} — клона нет: {card['path']}")
            said.append(f"  заведёт library.py pull --repo {card['repo']}")
            continue
        said.append(f"{card['repo']} — клон есть, ветка {card['branch'] or '?'}")
        who = card["author"] or "НЕ ЗАДАНО (коммитить нельзя)"
        said.append(f"  автор коммитов: {who}")
        if card["behind"] is None:
            said.append("  сверить с Библиотекой нечем: у ветки нет пары в origin")
        else:
            said.append(f"  отставание от Библиотеки: {card['behind']} "
                        f"(по последнему pull), своё неотправленное: {card['ahead']}")
        said.append(f"  незакоммиченных файлов: {len(card['dirty'])}"
                    + (f" — {', '.join(card['dirty'][:5])}" if card["dirty"] else ""))
    return said


def cmd_status(args, env: dict) -> int:
    folder = library_dir(env)
    cards = [status_of(repo) for repo in repos(env)]
    if args.json:
        say(json.dumps({"library": str(folder), "repos": cards},
                       ensure_ascii=False, indent=2), env)
        return client.EXIT_OK
    for line in status_lines(cards, folder):
        say(line, env)
    return client.EXIT_OK


def cmd_pull(args, env: dict) -> int:
    for repo in chosen(args, env):
        if not repo.cloned:
            clone(repo, env)
            continue
        pull_rebase(repo, env)
        say(f"{repo.name}: свежая копия", env)
    return client.EXIT_OK


def cmd_put(args, env: dict) -> int:
    """Записать готовый текст в Библиотеку и зафиксировать его.

    ПОРЯДОК ШАГОВ ЗДЕСЬ — ЭТО И ЕСТЬ ГЕЙТ. Слово судится ПЕРВЫМ, до чтения файла
    и до единого касания клона: отказ обязан не оставлять следа, а «сначала
    записали, потом проверили» оставляет его всегда.
    """
    sign = (getattr(args, "as_automaton", None) or "").strip()
    said = getattr(args, "word", None)
    if sign:
        if args.kind not in AUTOMATON_KINDS:
            raise client.Usage(
                f"Автомату вид «{args.kind}» закрыт",
                [f"автомат пишет только: {', '.join(AUTOMATON_KINDS)}",
                 "карту, сводку, подготовку и повестку записывает человек своим словом"])
        if said:
            client.confirmed_by(said)          # слово принесли — судим тем же правилом
    else:
        client.confirmed_by(said)

    repo = one_repo(getattr(args, "repo", None), env)
    when = library_date(getattr(args, "date", None))
    target, message = place(repo, args.kind, when, args)
    if sign and not automaton_allows(target, repo):
        raise client.Usage(
            f"Автомат пишет только в {' и '.join(AUTOMATON_DIRS)}, а путь ведёт в «{target}»",
            ["это правило Библиотеки, а не настройка: менять его — решением владельца"])

    source = Path(getattr(args, "file", None) or "").expanduser()
    if not (args.file or "").strip() or not source.is_file():
        raise client.Usage(
            f"Готового текста нет: --file «{args.file or ''}»",
            ["агент сначала пишет текст в файл, и только потом зовёт put"])
    body = source.read_bytes()

    if not repo.cloned:
        raise client.Usage(
            f"{repo.name}: клона нет — записывать некуда",
            [f"заведёт library.py pull --repo {repo.name}"])

    # Свежая копия ПЕРЕД записью — правило Библиотеки. Не вышло по сети — это не
    # повод не записать: коммит местный, и отправку рассудит push.
    try:
        pull_rebase(repo, env)
    except client.Unreachable as away:
        say(f"Библиотека не обновилась ({away.message}) — пишу в местную копию, "
            f"отправишь позже: library.py push --repo {repo.name}", env)
    except client.Refused as away:
        say(f"Библиотека не обновилась ({away.message}) — пишу в местную копию", env)

    full = repo.path / target
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(body)

    options = author_of(repo, sign)
    added = run_git(repo.path, ["add", "--", target])
    if added.returncode != 0:
        raise client.Usage(f"{repo.name}: git не принял файл «{target}»", tail(output(added)))
    if run_git(repo.path, ["diff", "--cached", "--quiet", "--", target]).returncode == 0:
        say(f"{repo.name}: файл уже такой — коммитить нечего: {target}", env)
        return client.EXIT_OK
    made = run_git(repo.path, [*options, "commit", "-m", message, "--", target])
    if made.returncode != 0:
        raise client.Usage(f"{repo.name}: коммит не вышел", tail(output(made)))

    stamp = git_text(repo.path, ["log", "-1", "--pretty=%h %an"]) or ""
    say(f"Записано: {repo.name}/{target}", env)
    say(f"Коммит {stamp} — «{message}»", env)
    say(f"Дальше: library.py push --repo {repo.name}", env)
    return client.EXIT_OK


def cmd_push(args, env: dict) -> int:
    named = bool((getattr(args, "repo", None) or "").strip())
    for repo in chosen(args, env):
        if not repo.cloned:
            if named:
                raise client.Usage(f"{repo.name}: клона нет — отправлять нечего",
                                   [f"заведёт library.py pull --repo {repo.name}"])
            say(f"{repo.name}: клона нет — пропускаю", env)
            continue
        push_one(repo, env)
    return client.EXIT_OK


def where_is(args, env: dict) -> tuple:
    """Репозиторий и путь внутри него. Файл в двух клонах — отказ, а не выбор."""
    said = (getattr(args, "path", None) or "").strip()
    if not said:
        raise client.Usage("Не назван файл: --path «Карта проектов.md»")
    found = repos(env)
    given = Path(said).expanduser()
    if given.is_absolute():
        for repo in found:
            try:
                return repo, given.resolve().relative_to(repo.path.resolve()).as_posix()
            except (ValueError, OSError):
                continue
        raise client.Usage(f"Этот путь не ведёт ни в один клон Библиотеки: {said}")
    inside = said.replace("\\", "/").lstrip("/")
    if (getattr(args, "repo", None) or "").strip():
        return pick(args.repo, found), inside
    hits = [repo for repo in found if repo.cloned and (repo.path / inside).exists()]
    if len(hits) == 1:
        return hits[0], inside
    if not hits:
        raise client.Usage(
            f"Такого файла нет ни в одном клоне: {inside}",
            ["проверь путь (он считается от корня репозитория) или назови --repo <имя>",
             "свежая ли копия — library.py pull"])
    raise client.Usage(
        f"Файл с таким путём есть в нескольких репозиториях: {inside}",
        [f"назови нужный: --repo {' | '.join(one.name for one in hits)}"])


def cmd_log(args, env: dict) -> int:
    repo, inside = where_is(args, env)
    result = run_git(repo.path, ["log", f"-n{max(1, args.count)}", "--date=short",
                                 "--pretty=%h  %ad  %an — %s", "--", inside])
    if result.returncode != 0:
        raise client.Usage(f"{repo.name}: историю не показать", tail(output(result)))
    text = result.stdout.strip()
    say(text or f"{repo.name}/{inside}: в Библиотеку этот файл ещё не попадал", env)
    return client.EXIT_OK


def cmd_diff(args, env: dict) -> int:
    repo, inside = where_is(args, env)
    result = run_git(repo.path, ["diff", "HEAD", "--", inside])
    if result.returncode != 0:
        raise client.Usage(f"{repo.name}: разницу не показать", tail(output(result)))
    text = result.stdout.strip()
    say(text or f"{repo.name}/{inside}: правок нет — файл совпадает с последним коммитом", env)
    return client.EXIT_OK


COMMANDS = {
    "status": cmd_status, "pull": cmd_pull, "put": cmd_put, "push": cmd_push,
    "log": cmd_log, "diff": cmd_diff,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Библиотека Oblako: документы отделов и совета")
    subs = parser.add_subparsers(dest="command", required=True)

    status = subs.add_parser("status", help="что за репозитории и в каком они состоянии")
    status.add_argument("--json", action="store_true", help="машинный вид для агента")

    pull = subs.add_parser("pull", help="свежая копия Библиотеки (заведёт клон, если его нет)")
    pull.add_argument("--repo", help="только этот репозиторий (без него — все)")

    put = subs.add_parser("put", help="записать готовый текст и зафиксировать его")
    put.add_argument("--repo", help="репозиторий: имя из library.py status")
    put.add_argument("--kind", default="", help="вид документа: " + ", ".join(KINDS))
    put.add_argument("--file", help="файл с готовым текстом")
    put.add_argument("--word", help="то, что сказал человек, дословно")
    put.add_argument("--team", help="отдел (репозиторий отделов: файлы лежат в Отделы/<Отдел>/)")
    put.add_argument("--date", help="дата документа ДД.ММ.ГГ или ISO (по умолчанию сегодня)")
    put.add_argument("--name", help="автор подготовки — имя, как в Oblako")
    put.add_argument("--title", help="название транскрипта или черновика")
    put.add_argument("--as-automaton", dest="as_automaton", metavar="ИМЯ",
                     help="подписать «Автомат: ИМЯ» (только транскрипты и черновики)")

    push = subs.add_parser("push", help="отправить свои коммиты в Библиотеку")
    push.add_argument("--repo", help="только этот репозиторий (без него — все)")

    log = subs.add_parser("log", help="история файла")
    log.add_argument("--path", help="путь внутри репозитория")
    log.add_argument("--repo", help="репозиторий (без него — тот, где файл нашёлся)")
    log.add_argument("-n", dest="count", type=int, default=10, help="сколько записей (10)")

    diff = subs.add_parser("diff", help="незаписанная разница файла")
    diff.add_argument("--path", help="путь внутри репозитория")
    diff.add_argument("--repo", help="репозиторий (без него — тот, где файл нашёлся)")
    return parser


def main(argv=None) -> int:
    client.setup_console()
    args = _parser().parse_args(argv)
    env = client.settings(SCRIPT)
    try:
        return COMMANDS[args.command](args, env)
    except client.ClientError as error:
        return client.fail(error, secrets(env))
    except Exception:                         # трассировка — только очищенная от ключей
        return client.crash(secrets(env))


if __name__ == "__main__":
    sys.exit(main())

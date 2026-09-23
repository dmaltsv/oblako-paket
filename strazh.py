# -*- coding: utf-8 -*-
"""strazh.py — страж слова: сказал ли «отправляй» сам человек (#508, Р8′).

ЗАЧЕМ ОН ЕСТЬ. Разбор планёрки в облаке делает рутина Claude Code, а рутина
идёт БЕЗ ПОДТВЕРЖДЕНИЙ: первый ход окна проходит без человека, и модель, только
что разобравшая встречу, по инерции тянется её отправить. Гейт `confirm --word`
проверяет само слово, но не того, кто его сказал: «отправляй» модель читает и в
инструкции рутины, и в нагрузке сигнала, и в теле навыка, и в тексте встречи,
где его говорят люди друг другу. Страж читает ЖУРНАЛ РАЗГОВОРА (JSONL, его ведёт
Claude Code) и пропускает `meeting.py confirm` и `send`, только если слово пришло
сообщением самого человека.

ПРАВИЛО — БЕЛЫЙ СПИСОК, А НЕ «ВСЁ ПОСЛЕ ПЕРВОГО СООБЩЕНИЯ». Сообщение человека —
запись `type: user` с пометкой `origin.kind = human`, без блоков `tool_result` и
без служебных пометок (`isMeta`, `isCompactSummary`, `isSidechain`,
`isVisibleInTranscriptOnly`). Прототип считал человеком всё после первого
сообщения — и на репетиции засчитал за человека нагрузку сигнала вторым ходом
(Э0, окно 2). Пометку `origin` пишет сам Claude Code: инструкция рутины несёт
`task-notification`, человек — `human` (Э0, проверка Г; журнал компьютера — так
же). Сообщение, которое человек дописал, пока модель работала, Claude Code
кладёт вложением `queued_command` с той же пометкой — оно тоже человек: иначе
его «стой» после «отправляй» страж бы не услышал.

ОЧЕРЕДЬ — ЗАКРЫВАЕТ, НО НЕ ОТКРЫВАЕТ (#520). Ещё раньше пометки то же сообщение
ложится в очередь: запись `queue-operation` (`enqueue`) с текстом, но без
пометки, чьё оно (журналы компьютера, 14.09.2026). Модель успевает вызвать
`confirm && send` одной командой, пока «стой» лежит в очереди, — поэтому текст
очереди после последнего сообщения человека страж считает его новым последним
сообщением: слова нет — запрет; слово есть — тоже запрет, пока сообщение не
легло с пометкой (решение руководителя 14.09.2026). Пропустить по очереди
нельзя: очередью едут и задание рутины, и уведомления. Уведомления Claude Code
(`NOTICES`) — не человек; прочие ходы очереди (`dequeue`, `remove`) — служебные.
Своё «отправляй» человек из очереди не теряет: запись с пометкой ложится ПОЗЖЕ
записи очереди.

ПРОПУСК — ТОЛЬКО ТАК: слово-команда в ПОСЛЕДНЕМ сообщении человека (судит его
`oblako_client.confirmed_by`, тот же судья, что у `confirm --word`), и ДО этого
сообщения модель уже вызвала показ разбора (`meeting.py preview`). Слово,
сказанное раньше, не переживает следующего сообщения: после «отправляй» человек
мог попросить правку. Поэтому повтор отправки («попробуй ещё раз», «без
публикации») требует нового «отправляй» — решение руководителя 13.09.2026.

НЕЗНАКОМОЕ — ЗАПРЕТ (FAIL-CLOSED). Формат журнала — исследовательская часть
Claude Code и может меняться. Нет журнала, он не читается, строка не разбирается
как JSON, запись без вида, запись человека или модели незнакомой формы, пометка
человека на записи незнакомого вида — запрет. Служебные записи БЕЗ человека и
без модели (снимки, метки, ходы очереди, вложения окружения) не судятся вовсе: они
появляются с каждым выпуском Claude Code, и запрет на них закрыл бы отправку из
окна и с компьютера разом, ничего не прибавив к защите — слово человека в них
не живёт.

ДВА НОСИТЕЛЯ, ОДИН РАЗБОР. (1) Проверка внутри скрипта у ОБЕИХ дверей к серверу —
`meeting.py confirm`/`send` и `send_package.py --package`: в облаке
(`CLAUDE_CODE_REMOTE=true`) скрипт сам находит журнал окна — самый свежий
`*.jsonl` в `~/.claude/projects` — и судит его (`require_word_in_cloud`). На
компьютере журнал скриптом не судится: у Codex его нет вовсе, и держит
`confirm --word`, как прежде. (2) Хук `PreToolUse` Claude Code (`python strazh.py
hook`): берёт журнал из своего входа (`transcript_path`), судит тем же `judge` и
запрещает команду с объяснением модели. Хук ставят в файл настроек Claude Code
(`install_hook`): в облаке — `avtomat.py run` в `~/.claude/settings.json`
машины, на компьютере — `install_skills.py` рядом со скиллами. Хук молчит на
любую другую команду и молчит на пропуске: разрешение от хука перебило бы вопрос
о правах, который человек на компьютере видит у каждой команды.

ВЫЗОВ, А НЕ УПОМИНАНИЕ (#520). Хук судит команду, которая ВЫЗЫВАЕТ подтверждение
или отправку, а не любую, где встретились эти слова: `git commit -m "…meeting.py
send…"`, `gh issue comment`, `grep "meeting.py send"` — упоминание, хук молчит
(без этого запрет получали коммиты и комментарии к тикетам в окнах разработки,
куда хук кладёт `install_skills.py`). Строка режется так, как её режет оболочка
(`_Shell`, bash или PowerShell — по имени инструмента), и совпадение прощается,
только если целиком лежит в словах программы, которая текст лишь ищет, читает
или печатает (`TEXT_PROGRAMS`), а её вывод не уходит по `|` программе другого
рода. Подстановка `$(…)` исполняется и внутри такой программы — судится по
своему содержимому. Всё прочее — строку не разобрать, программа не из списка —
судится, как раньше: промах в сторону запрета стоит повторного «отправляй», в
сторону пропуска — чужих задач. Хук держит отправку, в которую модель тянется
по инерции, а не нарочный обход (скрипт, записанный прошлым шагом; программа из
списка, которой велено исполнить команду): его в облаке держит проверка внутри
скрипта.

    python strazh.py hook        вход хука PreToolUse (читает stdin)
    python meeting.py strazh     самопроверка: вердикт по журналу этого окна

Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional

import oblako_client as client

SCRIPT = Path(__file__).resolve()

REMOTE_ENV = "CLAUDE_CODE_REMOTE"      # облачная сессия Claude Code: «true»

# Команды, которые страж судит, и команда показа. Между именем скрипта и
# подкомандой бывают кавычки (`python "<папка команд>/meeting.py" send` — так
# пишет указатель скилла; `meeting.py "send"`), перенос строки `\` (PowerShell —
# обратной кавычкой) и — в сыром JSON входа хука — экранирующий `\"`: всё это
# разрешено, иначе обход стража стоил бы одной пары кавычек. Тот же скрипт
# зовут и модулем (`python -m meeting send`, `meeting.main([... "send"])`).
# Дверей к серверу у пакета ДВЕ (шапка `oblako_client.require_confirmation`):
# вторая — `send_package.py --package`, и `argparse` понимает флаг сокращённым
# вплоть до `--pa`. Это текст, в котором ИЩУТ вызов; упоминание от вызова
# отличает разбор строки (`_calls_sending`, шапка).
_GAP = r"""[\\"'`\s]+"""
SENDING = re.compile(rf"""meeting\.py{_GAP}(confirm|send)\b"""
                     rf"""|(?<![\w-])-m{_GAP}meeting{_GAP}(confirm|send)\b"""
                     r"""|\bmeeting\.main\b[\s\S]{0,200}?\b(confirm|send)\b"""
                     r"""|send_package\.py\b[\s\S]{0,500}?--pa(?:c(?:k(?:a(?:ge?)?)?)?)?\b""")
PREVIEW = re.compile(rf"""meeting\.py{_GAP}preview\b""")

# Программы, которые текст команды только ищут, читают или печатают: совпадение
# в их словах — упоминание (шапка, «Вызов, а не упоминание»). Список закрытый:
# программа не из него — судится. `cat`, `echo`, `printf` здесь ради коммита
# сообщением `-m "$(cat <<'EOF' … EOF)"`: так его пишет Claude Code.
TEXT_PROGRAMS = frozenset({
    "git", "gh", "grep", "egrep", "fgrep", "rg", "findstr", "cat", "echo", "printf",
    "head", "tail", "sort", "uniq", "wc",
    "select-string", "sls", "select-object", "write-output", "write-host",
})
# Слова перед программой, которые сами ничего не исполняют: `if git grep …`.
PREFIX_WORDS = frozenset({"!", "{", "if", "then", "else", "elif", "do", "while", "until", "time"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")    # `GIT_INDEX_FILE=… git commit`

# Сообщение человека и служебные пометки записи — белый список (см. шапку).
HUMAN = "human"
SERVICE_MARKS = ("isMeta", "isCompactSummary", "isSidechain", "isVisibleInTranscriptOnly")
QUEUED = "queued_command"              # дописанное человеком, пока модель работала
QUEUE, ENQUEUE = "queue-operation", "enqueue"   # то же сообщение раньше, в очереди
# Уведомления, которые Claude Code везёт той же очередью (журналы компьютера,
# 14.09.2026). Незнакомый конверт — человек: он закрывает, а не открывает.
NOTICES = re.compile(r"<(task-notification|cross-session-message|system-reminder)[\s>]")

# Хук в файле настроек Claude Code. На компьютере команды зовёт и PowerShell, и
# судить надо оба инструмента: иначе «send» мимо стража уехал бы через соседний.
HOOK_EVENT = "PreToolUse"
HOOK_MATCHER = "Bash|PowerShell"
HOOK_TIMEOUT_SEC = 30
HOOK_MARK = re.compile(r"""strazh\.py["']?\s+hook\b""")

WORD_PASS = "слово «отправляй» — в последнем сообщении человека, после показа разбора"
NO_JOURNAL = "журнал разговора не найден"
NO_HUMAN = "в журнале нет ни одного сообщения человека"
NO_WORD = "в последнем сообщении человека нет слова «отправляй»"
IN_QUEUE = "последнее сообщение человека ещё в очереди — модель его не прочла"
NOT_SHOWN = "до слова человека разбор не показан"
UNKNOWN = "формат журнала незнаком"

FROM_COMPUTER = "отправьте с компьютера: скажите помощнику «разбери планёрку»"


class Verdict(NamedTuple):
    """Вердикт стража: пропуск или запрет — и причина словами."""

    allow: bool
    why: str


class _Unknown(Exception):
    """Запись, которую страж не понимает. Всегда кончается запретом."""


# ---------------------------------------------------------------------------
# Разбор журнала
# ---------------------------------------------------------------------------
def _text(content) -> str:
    """Текст записи: строка (облако) или блоки `text` (компьютер)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
        raise _Unknown
    parts = []
    for block in content:
        if block.get("type") == "text":
            if not isinstance(block.get("text"), str):
                raise _Unknown
            parts.append(block["text"])
    return "\n".join(parts)


def _origin(holder: dict) -> Optional[str]:
    """Вид пометки `origin` — или None, если пометки нет."""
    if "origin" not in holder:
        return None
    origin = holder["origin"]
    if not isinstance(origin, dict) or not isinstance(origin.get("kind"), str):
        raise _Unknown
    return origin["kind"]


def _marked_human(holder) -> bool:
    """Пометка человека у записи не `user` и у вложения. Читается мягко: поле
    `origin` другой формы у служебной записи — не повод закрыть отправку."""
    origin = holder.get("origin") if isinstance(holder, dict) else None
    return isinstance(origin, dict) and origin.get("kind") == HUMAN


def _content(record: dict):
    message = record.get("message")
    if not isinstance(message, dict) or "content" not in message:
        raise _Unknown
    return message["content"]


def _human_text(record: dict) -> Optional[str]:
    """Текст сообщения человека — или None, если запись не человек.

    Кидает `_Unknown` на записи человека или модели незнакомой формы и на
    пометке человека у записи незнакомого вида (см. шапку).
    """
    kind = record.get("type")
    if kind == "user":
        content = _content(record)
        text = _text(content)                           # форма текста — всегда
        origin = _origin(record)
        if origin != HUMAN or any(record.get(mark) for mark in SERVICE_MARKS):
            return None
        if isinstance(content, list) and any(b.get("type") == "tool_result" for b in content):
            return None
        return text
    attachment = record.get("attachment") if kind == "attachment" else None
    if _marked_human(record) or _marked_human(attachment):
        # Человек вне записи `user` понятен в одном виде — дописанное на ходу.
        # Любой другой вид незнаком: слово, которого страж не распознал, равно
        # слову, которого не было, — а вот «стой» пропустить нельзя.
        if not isinstance(attachment, dict) or attachment.get("type") != QUEUED \
                or record.get("isSidechain"):
            raise _Unknown
        return _text(attachment.get("prompt"))
    return None


def _queued_text(record: dict) -> Optional[str]:
    """Текст сообщения, положенного в очередь, — или None, если запись не такая.

    Читается мягко, как всякая служебная запись: текст не строкой (картинка) —
    сообщение без слова, а не незнакомый формат.
    """
    if record.get("type") != QUEUE or record.get("operation") != ENQUEUE:
        return None
    content = record.get("content")
    if not isinstance(content, str):
        return ""
    return None if NOTICES.match(content.lstrip()) else content


def _shows_review(record: dict) -> bool:
    """Ход модели, в котором она вызвала показ разбора."""
    if record.get("type") != "assistant":
        return False
    content = _content(record)
    if isinstance(content, str):
        return False
    if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
        raise _Unknown
    if record.get("isSidechain"):
        return False
    for block in content:
        given = block.get("input") if block.get("type") == "tool_use" else None
        command = given.get("command") if isinstance(given, dict) else None
        if isinstance(command, str) and PREVIEW.search(command):
            return True
    return False


def _is_write_command(text: str) -> bool:
    """Команда ли это «отправляй» — тем же судьёй, что у `confirm --word`."""
    try:
        client.confirmed_by(text)
    except client.Usage:
        return False
    return True


def judge(path) -> Verdict:
    """Вердикт по журналу разговора. Один на хук и на скрипт."""
    if not path or not isinstance(path, (str, os.PathLike)):
        return Verdict(False, NO_JOURNAL)
    path = Path(path)
    if not path.exists():
        return Verdict(False, NO_JOURNAL)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return Verdict(False, f"журнал разговора не читается ({type(error).__name__})")

    last_human = None                   # (номер строки, текст)
    last_queued = None                  # то же — у записи очереди
    shown_at = []
    # Строки — по «\n», а не `splitlines`: тот режет и по U+2028, которое JSON
    # Claude Code оставляет внутри строк как есть, и живой журнал с таким
    # символом в сообщении читался бы битым.
    for number, line in enumerate(raw.split("\n"), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            return Verdict(False, f"строка {number} журнала не разбирается — {UNKNOWN}")
        try:
            if not isinstance(record, dict) or not isinstance(record.get("type"), str):
                raise _Unknown
            text = _human_text(record)
            queued = _queued_text(record)
            if text is not None:
                last_human = (number, text)
            elif queued is not None:
                last_queued = (number, queued)
            elif _shows_review(record):
                shown_at.append(number)
        except _Unknown:
            return Verdict(False, f"запись {number} журнала незнакомого вида — {UNKNOWN}")

    if last_human is None:
        return Verdict(False, NO_HUMAN)
    number, text = last_human
    if last_queued is not None and last_queued[0] > number:
        # Новое последнее сообщение человека — но из очереди: закрыть может,
        # открыть нет (шапка, «Очередь»).
        return Verdict(False, IN_QUEUE if _is_write_command(last_queued[1]) else NO_WORD)
    if not _is_write_command(text):
        return Verdict(False, NO_WORD)
    if not any(at < number for at in shown_at):
        return Verdict(False, NOT_SHOWN)
    return Verdict(True, WORD_PASS)


def find_journal() -> Optional[Path]:
    """Журнал окна без подсказки хука: самый свежий `*.jsonl` в `~/.claude/projects`.

    В облаке машина рутины заводится под окно, и журнал на ней один (Э0). Журналы
    помощников (`<сессия>/subagents/…`) лежат глубже и сюда не попадают.
    """
    newest, newest_at = None, None
    for path in (Path.home() / ".claude" / "projects").glob("*/*.jsonl"):
        try:
            at = path.stat().st_mtime
        except OSError:                             # журнал исчез между поиском и чтением
            continue
        if newest_at is None or at > newest_at:
            newest, newest_at = path, at
    return newest


# ---------------------------------------------------------------------------
# Носитель 1: проверка внутри скрипта
# ---------------------------------------------------------------------------
def in_cloud() -> bool:
    """Облачная сессия Claude Code — там окно рутины и нет человека у экрана."""
    return (os.environ.get(REMOTE_ENV) or "").strip().lower() == "true"


def refusal(verdict: Verdict, cloud: bool) -> tuple:
    """Отказ словами модели: (сообщение, подробности). Один на оба носителя."""
    details = ["не подставляй «отправляй» за человека и не обходи эту проверку",
               "человек в окне — пусть скажет «отправляй» сам, отдельным сообщением "
               "после показа разбора"]
    if cloud:
        details.append(FROM_COMPUTER)
    return f"Страж слова: слова человека в этом окне не было — {verdict.why}", details


def require_word_in_cloud() -> None:
    """В облаке — вердикт по журналу окна или отказ. На компьютере — ничего.

    Зовут обе двери к серверу — `meeting.py confirm`/`send` первым делом (запрет
    не должен оставлять ни пакета, ни расписки) и `send_package.py --package`
    рядом с гейтом отпечатка.
    """
    if not in_cloud():
        return
    verdict = judge(find_journal())
    if not verdict.allow:
        raise client.Usage(*refusal(verdict, cloud=True))


# ---------------------------------------------------------------------------
# Вызов или упоминание: разбор строки команды
# ---------------------------------------------------------------------------
class _Unparsed(Exception):
    """Строка, которую страж не разрезал как оболочка. Судится целиком."""


class _Command:
    """Простая команда строки: её место, слова и вложенные куски.

    `subs` — (начало, конец, команды, блок): подстановка `$(…)` отдаёт программе
    свой ВЫВОД и прощается только вместе с ней; блок PowerShell `{…}` — код,
    который судится сам по себе. `bodies` — (начало, конец, исполнимое): тело
    heredoc, которое читает программа.
    """

    def __init__(self, start: int):
        self.start = self.end = start
        self.words: list = []
        self.subs: list = []
        self.bodies: list = []
        self.piped = False              # вывод уходит следующей команде по `|`

    def empty(self) -> bool:
        return not (self.words or self.subs)

    def program(self) -> Optional[str]:
        """Имя программы без пути и `.exe` — или None, если его не узнать."""
        for word in self.words:
            if word in PREFIX_WORDS or ASSIGNMENT.match(word):
                continue
            if "\0" in word:                        # имя программы — из подстановки
                return None
            name = re.split(r"[\\/]", word)[-1].lower()
            return name[:-4] if name.endswith(".exe") else name
        return None


class _Shell:
    """Режет строку, как оболочка, — ровно настолько, чтобы найти простые
    команды, их программы, подстановки и тела heredoc. Чего не понял — `_Unparsed`.

    bash: `\\` — экранирование, `` `…` `` и `$(…)` — подстановки, `<<` — heredoc.
    PowerShell: `` ` `` — экранирование, `$(…)`/`@(…)` — подстановки, `{…}` — блок,
    `@'…'@`/`@"…"@` — многострочные строки.
    """

    def __init__(self, text: str, powershell: bool):
        self.text, self.ps, self.at = text, powershell, 0
        self.escape = "`" if powershell else "\\"
        self.heredocs: list = []        # ждут конца строки: (команда, разделитель, живое, табы)

    def parse(self) -> list:
        commands = self._list(None)
        if self.heredocs:
            raise _Unparsed
        return commands

    def _list(self, closer: Optional[str]) -> list:
        text, commands, depth = self.text, [], 0
        command, word = _Command(self.at), None
        while True:
            if self.at >= len(text):
                if closer is not None:
                    raise _Unparsed
                break
            ch, two = text[self.at], text[self.at:self.at + 2]
            if ch == closer and (closer != ")" or depth == 0):
                break
            if ch in " \t\r":
                word = self._word(command, word)
                self.at += 1
            elif ch == self.escape:
                if text.startswith("\n", self.at + 1) or text.startswith("\r\n", self.at + 1):
                    self.at = text.index("\n", self.at) + 1       # перенос строки
                else:
                    word = (word or []) + [text[self.at + 1:self.at + 2]]
                    self.at += 2
            elif ch == "'":
                end = text.find("'", self.at + 1)
                if end < 0:
                    raise _Unparsed
                word = (word or []) + [text[self.at + 1:end]]
                self.at = end + 1
            elif ch == '"':
                self.at += 1
                word = self._quoted(command, word or [], '"')
            elif self.ps and two in ("@'", '@"') and text[self.at + 2:self.at + 4].lstrip("\r")[:1] == "\n":
                # Многострочная строка PowerShell: конец — `'@`/`"@` в начале строки.
                terminator = "\n" + two[1] + "@"
                if two == "@'":
                    end = text.find(terminator, self.at)
                    if end < 0:
                        raise _Unparsed
                    word = (word or []) + [text[self.at + 2:end]]
                    self.at = end + len(terminator)
                else:
                    self.at += 2
                    word = self._quoted(command, word or [], terminator)
            elif two == "$(" or (self.ps and two == "@(") or (not self.ps and two in ("<(", ">(")):
                word = self._sub(command, word, 2, ")", block=False)
            elif ch == "`" and not self.ps:
                word = self._sub(command, word, 1, "`", block=False)
            elif ch == "{" and self.ps:
                word = self._sub(command, word, 1, "}", block=True)
            elif not self.ps and text.startswith("<<<", self.at):
                word = self._word(command, word)
                self.at += 3
            elif not self.ps and two == "<<":
                word = self._word(command, word)
                self._heredoc(command)
            elif self.ps and two == "<#":                  # блочный комментарий PowerShell
                end = text.find("#>", self.at)
                if end < 0:
                    raise _Unparsed
                self.at = end + 2
            elif ch == "#" and word is None:                # комментарий до конца строки
                end = text.find("\n", self.at)
                self.at = len(text) if end < 0 else end
            elif two in (">&", "&>"):                   # `2>&1`, `&>файл` — не разделитель
                word = (word or []) + [two]
                self.at += 2
            elif ch in ";&|\n()" or ch == "}" and self.ps:
                piped = ch == "|" and two != "||"
                if ch == "(":
                    depth += 1
                elif ch == ")" and depth:
                    depth -= 1
                word = self._word(command, word)
                self._end(commands, command, piped)
                self.at += 2 if two in ("&&", "||", "|&", ";;") else 1
                if ch == "\n":
                    self._bodies()
                command = _Command(self.at)
            else:
                word = (word or []) + [ch]
                self.at += 1
        self._word(command, word)
        self._end(commands, command, False)
        return commands

    @staticmethod
    def _word(command: _Command, word) -> None:
        if word is not None:
            command.words.append("".join(word))
        return None

    def _end(self, commands: list, command: _Command, piped: bool) -> None:
        command.end = self.at
        if not command.empty():
            command.piped = piped
            commands.append(command)
        elif piped and commands:                    # `(… ) | bash`: труба у группы
            commands[-1].piped = True

    def _quoted(self, command: _Command, word: list, terminator: str) -> list:
        """Строка в двойных кавычках (или `@"…"@`) до `terminator`: подстановки живы."""
        text = self.text
        while True:
            if self.at >= len(text):
                raise _Unparsed
            if text.startswith(terminator, self.at):
                self.at += len(terminator)
                return word
            ch = text[self.at]
            if ch == self.escape:
                word = word + [text[self.at + 1:self.at + 2]]
                self.at += 2
            elif text.startswith("$(", self.at):
                word = self._sub(command, word, 2, ")", block=False)
            elif ch == "`" and not self.ps:
                word = self._sub(command, word, 1, "`", block=False)
            else:
                word = word + [ch]
                self.at += 1

    def _sub(self, command: _Command, word, opener: int, closer: str, block: bool) -> list:
        self.at += opener
        start = self.at
        inner = self._list(closer)
        command.subs.append((start, self.at, inner, block))
        self.at += 1                                # закрывающий знак
        return (word or []) + ["\0"]

    def _heredoc(self, command: _Command) -> None:
        self.at += 2
        tabs = self.text.startswith("-", self.at)
        found = re.compile(r"""-?[ \t]*(['"]?)([^\s'"<>;&|()]+)\1""").match(self.text, self.at)
        if not found:
            raise _Unparsed
        self.at = found.end()
        self.heredocs.append((command, found.group(2), not found.group(1), tabs))

    def _bodies(self) -> None:
        """Тела heredoc — со строки после команды до строки-разделителя."""
        text = self.text
        for command, delimiter, live, tabs in self.heredocs:
            start = self.at
            while True:
                end = text.find("\n", self.at)
                line = text[self.at:len(text) if end < 0 else end].rstrip("\r")
                if (line.lstrip("\t") if tabs else line) == delimiter:
                    body = text[start:self.at]
                    command.bodies.append((start, self.at, live and ("$(" in body or "`" in body)))
                    self.at = len(text) if end < 0 else end + 1
                    break
                if end < 0:
                    raise _Unparsed
                self.at = end + 1
        self.heredocs = []


def _reads_text(commands: list, index: int) -> bool:
    """Команда — программа из `TEXT_PROGRAMS`, и дальше по `|` — только такие же."""
    for command in commands[index:]:
        if command.program() not in TEXT_PROGRAMS:
            return False
        if not command.piped:
            return True
    return True


def _mark_text(commands: list, mask: bytearray) -> None:
    """Отметить в `mask` знаки, которые — данные программы, текст не исполняющей."""
    for index, command in enumerate(commands):
        text_only = _reads_text(commands, index)
        if text_only:
            mask[command.start:command.end] = b"\1" * (command.end - command.start)
            for start, end, executable in command.bodies:
                if not executable:
                    mask[start:end] = b"\1" * (end - start)
        for start, end, inner, block in command.subs:
            mask[start:end] = bytes(end - start)
            if text_only or block:
                _mark_text(inner, mask)


def _calls_sending(command: str, tool) -> bool:
    """Вызывает ли команда подтверждение или отправку (шапка, «Вызов, а не упоминание»)."""
    found = [match.span() for match in SENDING.finditer(command)]
    if not found:
        return False
    try:
        commands = _Shell(command, powershell=tool == "PowerShell").parse()
    except (_Unparsed, RecursionError):
        return True
    mask = bytearray(len(command))
    _mark_text(commands, mask)
    return not all(all(mask[start:end]) for start, end in found)


# ---------------------------------------------------------------------------
# Носитель 2: хук PreToolUse
# ---------------------------------------------------------------------------
def _deny(reason: str) -> str:
    # ASCII-JSON: вывод хука читает Claude Code как UTF-8, а консоль Windows
    # пишет в чужой кодировке — экранированный текст доезжает одинаково везде.
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": HOOK_EVENT,
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=True)


def _broken(what: str) -> str:
    # «С компьютера» — только в облаке, как у `refusal`: на компьютере человек уже там.
    where = f" {FROM_COMPUTER}." if in_cloud() else ""
    return _deny(f"Страж слова: {what} — отправка без проверки запрещена.{where}")


def hook_answer(raw: str) -> str:
    """Ответ хука на вход Claude Code: JSON с запретом или пустая строка.

    Хук не спасает сбой ВНЕ Python: пропал интерпретатор из записанного пути,
    вышел таймаут — Claude Code такую ошибку считает неблокирующей и команду
    выполняет. Первое видит проверка установки (`hook_state`); в облаке отправку
    держит и проверка внутри скрипта, на компьютере — `confirm --word`.
    """
    try:
        data = json.loads(raw)
        command = data.get("tool_input", {}).get("command")
        tool = data.get("tool_name")
    except (ValueError, AttributeError):
        # Вход не разобрать — судим по сырому тексту: на отправке сбой — запрет.
        return _broken("вход хука не разобрать") if SENDING.search(raw) else ""
    if not isinstance(command, str) or not _calls_sending(command, tool):
        return ""
    verdict = judge(data.get("transcript_path"))
    if verdict.allow:
        return ""
    message, details = refusal(verdict, in_cloud())
    return _deny(message + ". " + "; ".join(details) + ".")


# ---------------------------------------------------------------------------
# Установка хука в файл настроек Claude Code
# ---------------------------------------------------------------------------
HOOK_STATE_WORDS = {"same": "стоит", "stale": "устарел", "missing": "не подключён",
                    "added": "поставлен", "updated": "обновлён"}
"""Слова состояний хука — одни на автомат и проверку установки. Таблица
`install_skills.py` пишет состояние своими отметками (`GUARD_MARKS`), в строку
к отметкам скиллов."""

HOOK_COMMAND = re.compile(r'^"(?P<python>[^"]+)" "(?P<script>[^"]+)" hook$')


def settings_file(root: Path) -> Path:
    """Файл настроек Claude Code под корнем: рабочая копия или домашняя папка."""
    return Path(root) / ".claude" / "settings.json"


def hook_command() -> str:
    """Команда хука: абсолютные пути интерпретатора и скрипта в папке команд.

    Пути — с прямыми слэшами и в кавычках: так команду одинаково читают bash
    облака, Git Bash и cmd компьютера, а пробел в «Мои документы» её не рвёт.
    Интерпретатор — ЭТОТ: `python` в PATH на Windows бывает заглушкой магазина.
    """
    return f'"{Path(sys.executable).as_posix()}" "{SCRIPT.as_posix()}" hook'


def hook_entry() -> dict:
    return {"matcher": HOOK_MATCHER,
            "hooks": [{"type": "command", "command": hook_command(),
                       "timeout": HOOK_TIMEOUT_SEC}]}


def _is_guard_hook(hook) -> bool:
    """Хук стража — узнаётся по скрипту, а не по всей строке команды."""
    return (isinstance(hook, dict) and isinstance(hook.get("command"), str)
            and HOOK_MARK.search(hook["command"]) is not None)


def _holds_guard_hook(entry) -> bool:
    """Запись `PreToolUse`, среди хуков которой есть хук стража."""
    return (isinstance(entry, dict) and isinstance(entry.get("hooks"), list)
            and any(_is_guard_hook(hook) for hook in entry["hooks"]))


def _works_here(entry: dict) -> bool:
    """Запись стража исправна НА ЭТОЙ МАШИНЕ: судит оба инструмента, ведёт в эту
    папку команд, и интерпретатор из её команды существует.

    Интерпретатор сверяется наличием, а не равенством с текущим: установку и
    проверку законно зовут разными `python` (`py`, `python3`, venv), и хук,
    поставленный одним, от проверки другим устаревшим не становится.
    """
    hooks = entry.get("hooks")
    if entry.get("matcher") != HOOK_MATCHER or len(hooks) != 1:
        return False
    hook = hooks[0]
    found = HOOK_COMMAND.match(hook.get("command") or "")
    return (found is not None and hook.get("type") == "command"
            and hook.get("timeout") == HOOK_TIMEOUT_SEC
            and found["script"] == SCRIPT.as_posix()
            and Path(found["python"]).is_file())


def _read_settings(path: Path) -> dict:
    """Настройки как есть. Чужой файл, который не разобрать, не переписывается."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as error:
        raise client.Usage(f"Файл настроек Claude Code не разобрать: {path} ({error})",
                           ["страж слова не поставлен: чужой файл не переписываю — "
                            "поправь его и повтори"]) from None
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    if not isinstance(hooks, dict) or not isinstance(hooks.get(HOOK_EVENT, []), list):
        raise client.Usage(f"Файл настроек Claude Code незнакомой формы: {path}",
                           ["страж слова не поставлен: ждал объект с `hooks` — "
                            "поправь файл и повтори"])
    return data


def hook_state(path: Path) -> str:
    """«same» — хук стоит и исправен здесь, «stale» — стоит, но не тот, «missing» — нет."""
    entries = _read_settings(Path(path)).get("hooks", {}).get(HOOK_EVENT, [])
    guards = [entry for entry in entries if _holds_guard_hook(entry)]
    if not guards:
        return "missing"
    return "same" if len(guards) == 1 and _works_here(guards[0]) else "stale"


def install_hook(path: Path) -> str:
    """Дописать хук стража в файл настроек. Возвращает «added», «updated» или «same».

    Чужие ключи и чужие хуки файла остаются как были. Свой хук узнаётся по
    скрипту (`strazh.py … hook`), а не по всей строке: переехавшая папка команд
    или пропавший интерпретатор — это тот же хук с негодным адресом, и повтор
    заменяет его, а не заводит второй.
    """
    path = Path(path)
    state = hook_state(path)
    if state == "same":
        return state
    data = _read_settings(path)
    hooks = data.setdefault("hooks", {})
    kept = []
    for entry in hooks.get(HOOK_EVENT, []):
        if not _holds_guard_hook(entry):
            kept.append(entry)
            continue
        rest = [hook for hook in entry["hooks"] if not _is_guard_hook(hook)]
        if rest:
            kept.append({**entry, "hooks": rest})
    hooks[HOOK_EVENT] = kept + [hook_entry()]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Через временный файл: оборвись запись посередине — у человека остались бы
    # полфайла настроек Claude Code вместо его модели, хуков и разрешений.
    pending = path.with_name(path.name + ".oblako-tmp")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="\n")
    os.replace(pending, path)
    return "added" if state == "missing" else "updated"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv != ["hook"]:
        print("python strazh.py hook — вход хука PreToolUse Claude Code (читает stdin). "
              "Самопроверка стража: python meeting.py strazh", file=sys.stderr)
        return client.EXIT_USAGE
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    try:
        answer = hook_answer(raw)
    except Exception as error:                  # сбой самого стража
        # Сырой вход — JSON с экранированными кавычками; `SENDING` их пропускает.
        answer = _broken(f"сбой стража ({type(error).__name__})") \
            if SENDING.search(raw) else ""
    if answer:
        sys.stdout.write(answer + "\n")
    return client.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

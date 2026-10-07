# -*- coding: utf-8 -*-
"""postanovka.py — задачи из разговора Claude: поставить, поправить, снять (#679).

Человек разбирает в Claude документ и говорит «поставь Арине сверку остатков по
кассе до пятницы» — задача уходит сразу, обычным ПОРУЧЕНИЕМ от него, как из
приложения: без пометки встречи и без поста в чат отдела (спека #675). Так же
«поправь срок на понедельник» и «сними, это не Алине». Запуск и отправка — одно
сообщение: показа до отправки нет, после отправки скрипт печатает карточку
отправленного целиком — номер, кому, название, описание, дедлайн, важность,
просьбу «скажи, чем кончилось».

ДВЕРЬ ТА ЖЕ, ЧТО У ПРИЛОЖЕНИЯ. Запись идёт ручками приложения вторым адресом под
корнем контура ПК (`/api/pc/tasks…`, контракт — у `api_pc_assignees` в
`bot/web.py`): права, белые списки полей, отказы и конверты получателю судит
сервер, и второго судьи здесь нет. Себе законны рабочий день и дедлайн, другому
— только дедлайн; просьба о комментарии — только в чужой задаче; кто вправе
править и снимать — тоже сервер. Отказ доезжает СЛОВАМИ ЯДРА и печатается
дословно: «Такая задача уже есть в списке: «…»», «сотрудник выключен».

ЗАПИСЬ — ТОЛЬКО СО СЛОВАМИ ЧЕЛОВЕКА. `add`, `edit` и `drop` требуют `--word` —
последнее сообщение человека дословно, — и судит его судья двери задач
`oblako_client.task_ordered_by` ДО ключа и до сети: «поставь/ставь», «поправь»,
«сними», «отправляй»; отрицание прямо перед словом — отказ; «да» и «ок» — не
команда. Слово в `--word` пишет модель, поэтому в Claude Code команду тем же
судьёй ещё раз сверяет страж — хук `strazh.py`, по последнему сообщению человека
в журнале разговора (#680); в облаке, где ключ лежит в окружении машины, тот же
журнал сверяет и сам скрипт (`strazh.require_word_in_cloud`), как разбор. У
Codex хука нет — там держит только судья слова. Чтение (`people`, `mine`) слова
не спрашивает.

ОДНА ЗАДАЧА — ОДИН ВЫЗОВ. Несколько разных задач в одном сообщении — вызов на
каждую: принятые уходят, про отвергнутую сказано её отказом. Одна задача
нескольким людям — один вызов с `--to` на каждого: у каждого своя копия, у кого
такая уже есть — тому не ставится, и сервер называет его по имени.

Подкоманды:
  people                       кому можно поставить: номер, имя, отделы
  mine                         мои открытые: поручения другим и свои задачи
  add  --word СЛОВА --text НАЗВАНИЕ [--to НОМЕР …] [--description ОПИСАНИЕ]
       [--deadline ГГГГ-ММ-ДД] [--due ГГГГ-ММ-ДД] [--importance 1|2|3]
       [--needs-comment]       поставить: без --to — себе, с одним — ему,
                               с несколькими — каждому свою копию
  edit НОМЕР --word СЛОВА [--text …] [--description …] [--deadline … | --no-deadline]
       [--due …] [--importance 1|2|3] [--needs-comment | --no-needs-comment]
                               поправить: уходит только названное
  drop НОМЕР --word СЛОВА      снять

Важность: 3 — важная (🔥), 2 — обычная (её не называют), 1 — неважная.

Коды выхода — общие у клиентов сервера, см. `oblako_client`: 0 — сделано,
1 — негодный вызов, нет слова человека, нет настроек или сервер ещё не знает
двери задач, 2 — сервер отказал (его слова — в выводе), 3 — до сервера не
достучались: ушла ли запись, неизвестно, — сначала `mine`, потом повтор.

Примеры:
  python postanovka.py people
  python postanovka.py add --word "Поставь Арине сверку остатков до пятницы" --to 5
         --text "Сверка остатков по кассе" --description "…" --deadline 2026-10-09
  python postanovka.py edit 123 --word "поправь срок на понедельник" --deadline 2026-10-12
  python postanovka.py drop 123 --word "сними, это не Алине"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import oblako_client as client
import strazh

SCRIPT = Path(__file__).resolve()

# Сервер до двери задач (#678) отвечает на её адреса общим 404 Flask. Это не
# отказ, а отставший сервер — тот же судья и тот же код 1, что у среза
# (`oblako_client.server_lacks`): «проверь ключ» водило бы человека не туда.
OLD_SERVER = ("Сервер ещё не умеет ставить задачи из Claude — скажи владельцу "
              "системы: сервер нужно обновить. Пакет здесь ни при чём.")

IMPORTANCE = {3: "🔥 важная", 2: "обычная", 1: "неважная"}
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота",
            "воскресенье")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Задачи из разговора Claude: поставить, поправить, снять")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("people", help="кому можно поставить задачу")
    subs.add_parser("mine", help="мои открытые: поручения другим и свои задачи")

    def word(sub):
        # НЕ `required`: без слова argparse вышел бы кодом 2, а 2 у клиентов —
        # «сервер отказал». Отсутствие слова судит `task_ordered_by` кодом 1.
        sub.add_argument("--word", help="последнее сообщение человека дословно")

    add = subs.add_parser("add", help="поставить задачу себе, другому или нескольким")
    word(add)
    add.add_argument("--text", required=True, help="название: коротко, что сделать")
    add.add_argument("--to", type=int, action="append", dest="owners", metavar="НОМЕР",
                     help="кому (номер из people); без него — себе, несколько — каждому")
    add.add_argument("--description", help="описание: что сделать, зачем, на что опереться")
    add.add_argument("--deadline", metavar="ГГГГ-ММ-ДД", help="дедлайн")
    add.add_argument("--due", metavar="ГГГГ-ММ-ДД", help="рабочий день — только себе")
    add.add_argument("--importance", type=int, choices=(1, 2, 3),
                     help="3 — важная, 2 — обычная, 1 — неважная")
    add.add_argument("--needs-comment", action="store_true", dest="needs_comment",
                     help="попросить сказать, чем кончилось (только другому)")

    edit = subs.add_parser("edit", help="поправить задачу: уходит только названное")
    edit.add_argument("task", type=int, metavar="НОМЕР", help="номер задачи из mine")
    word(edit)
    edit.add_argument("--text", help="новое название")
    edit.add_argument("--description", help="новое описание")
    edit.add_argument("--deadline", metavar="ГГГГ-ММ-ДД", help="новый дедлайн")
    edit.add_argument("--no-deadline", action="store_true", dest="no_deadline",
                      help="снять дедлайн")
    edit.add_argument("--due", metavar="ГГГГ-ММ-ДД", help="рабочий день — только своей")
    edit.add_argument("--importance", type=int, choices=(1, 2, 3),
                      help="3 — важная, 2 — обычная, 1 — неважная")
    edit.add_argument("--needs-comment", action=argparse.BooleanOptionalAction,
                      dest="needs_comment", default=None,
                      help="просить или больше не просить сказать, чем кончилось")

    drop = subs.add_parser("drop", help="снять задачу")
    drop.add_argument("task", type=int, metavar="НОМЕР", help="номер задачи из mine")
    word(drop)
    return parser


# ---------------------------------------------------------------------------
# Сервер
# ---------------------------------------------------------------------------
def _call(method: str, path: str, env: dict, *, body: Optional[dict] = None) -> dict:
    """Запрос двери задач общим клиентом; отказ сервера — его словами.

    Ключ спрашивается ЗДЕСЬ, то есть после судьи слова: запись без команды
    человека кончается до ключа и до сети.
    """
    url, key = client.base_url(env), client.access_key(env)
    raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    timeout = client.TIMEOUT_READ_SEC if method == "GET" else client.TIMEOUT_TASK_SEC
    try:
        return client.call(method, path, url=url, key=key, timeout=timeout, body=raw)
    except client.Refused as refusal:
        if client.server_lacks(refusal):
            raise client.Usage(OLD_SERVER) from None
        if not refusal.reason:
            raise
        # Слова ядра — человеку дословно, без рамки общего клиента: она советует
        # проверить ключ и отдел, а здесь 403 — это чаще «поручение закрыто».
        raise client.Refused(f"Сервер отказал: {refusal.reason}", refusal.details,
                             status=refusal.status, field=refusal.field,
                             reason=refusal.reason) from None


def _names(env: dict, tasks: list) -> dict:
    """Имена хозяев для карточки — у задачи в ответе записи есть только номер.

    Спрашивается ПОСЛЕ записи и только для показа: запись уже ушла, и сбой этого
    чтения не должен звучать как её неудача — тогда в карточке номер вместо имени.
    """
    if all(task.get("owner_id") == task.get("created_by") for task in tasks):
        return {}
    try:
        people = _call("GET", "/api/pc/assignees", env).get("people") or []
    except client.ClientError:
        return {}
    return {one.get("id"): one.get("name") for one in people}


# ---------------------------------------------------------------------------
# Вид
# ---------------------------------------------------------------------------
def _day(value: Optional[str]) -> str:
    """«09.10.2026, пятница»: день недели — чтобы «до пятницы» сверялось глазом."""
    if not value:
        return "нет"
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{day:%d.%m.%Y}, {WEEKDAYS[day.weekday()]}"


def card(task: dict, names: dict) -> list:
    """Карточка задачи целиком — то, что человек проверяет после отправки."""
    owner = task.get("owner_id")
    whom = ("себе" if owner == task.get("created_by")
            else names.get(owner) or f"человек №{owner}")
    lines = [f"№{task.get('id')} · кому: {whom}",
             f"  Название: {task.get('text')}"]
    description = (task.get("description") or "").strip()
    if description:
        lines.append("  Описание: " + description.replace("\n", "\n            "))
    else:
        lines.append("  Описание: нет")
    lines.append(f"  Дедлайн: {_day(task.get('deadline'))}")
    if task.get("due"):
        lines.append(f"  Рабочий день: {_day(task.get('due'))}")
    lines.append(f"  Важность: {IMPORTANCE.get(task.get('importance'), task.get('importance'))}")
    lines.append("  Просьба «скажи, чем кончилось»: "
                 + ("да" if task.get("needs_comment") else "нет"))
    return lines


# ---------------------------------------------------------------------------
# Подкоманды
# ---------------------------------------------------------------------------
def people(env: dict) -> int:
    answer = _call("GET", "/api/pc/assignees", env)
    for one in answer.get("people") or []:
        teams = ", ".join(one.get("teams") or []) or "без отдела"
        print(f"№{one.get('id')}  {one.get('name')} — {teams}")
    return client.EXIT_OK


def mine(env: dict) -> int:
    answer = _call("GET", "/api/pc/my-tasks", env)

    def row(task: dict, whom: bool) -> str:
        head = f"  №{task.get('id')} · " + (f"{task.get('owner')} · " if whom else "")
        deadline = task.get("deadline")
        return head + f"{task.get('text')} · " + (
            f"дедлайн {_day(deadline)}" if deadline else "без дедлайна")

    for title, key, whom in (("Мои поручения — открытые", "assignments", True),
                             ("Свои задачи — открытые", "own", False)):
        tasks = answer.get(key) or []
        print(f"{title}: {len(tasks) or 'нет'}")
        for task in tasks:
            print(row(task, whom))
    return client.EXIT_OK


def add(args, env: dict) -> int:
    body: dict = {"text": args.text}
    owners = args.owners or []
    if len(owners) == 1:
        body["owner_id"] = owners[0]
    elif owners:
        body["owner_ids"] = owners
    for name in ("description", "deadline", "due", "importance"):
        value = getattr(args, name)
        if value is not None:
            body[name] = value
    if args.needs_comment:
        body["needs_comment"] = True
    if len(owners) > 1:
        answer = _call("POST", "/api/pc/tasks/many", env, body=body)
        tasks = answer.get("tasks") or []
        print(f"Поставлено: {len(tasks)} из {len(owners)}")
    else:
        answer = _call("POST", "/api/pc/tasks", env, body=body)
        tasks = [answer.get("task") or {}]
        print("Поставлено:")
    names = _names(env, tasks)
    for task in tasks:
        print("\n".join(card(task, names)))
    if answer.get("words"):
        print(answer["words"])
    return client.EXIT_OK


def edit(args, env: dict) -> int:
    body: dict = {}
    for name in ("text", "description", "deadline", "due", "importance", "needs_comment"):
        value = getattr(args, name)
        if value is not None:
            body[name] = value
    if args.no_deadline:
        if "deadline" in body:
            raise client.Usage("--deadline и --no-deadline вместе не работают: выбери одно")
        body["deadline"] = None
    if not body:
        raise client.Usage("Нечего править: назови хотя бы одно поле — --text, "
                           "--description, --deadline, --importance, --needs-comment …")
    answer = _call("PATCH", f"/api/pc/tasks/{args.task}", env, body=body)
    task = answer.get("task") or {}
    print("Поправлено:" if answer.get("changed") else "Ничего не изменилось — у задачи уже так:")
    print("\n".join(card(task, _names(env, [task]))))
    return client.EXIT_OK


def drop(args, env: dict) -> int:
    answer = _call("POST", f"/api/pc/tasks/{args.task}/drop", env)
    task = answer.get("task") or {}
    print("Снято:" if answer.get("changed") else "Задача уже снята — ничего не изменилось:")
    print("\n".join(card(task, _names(env, [task]))))
    return client.EXIT_OK


WRITES = {"add": add, "edit": edit, "drop": drop}


def main(argv=None) -> int:
    client.setup_console()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        # argparse выходит кодом 2 на негодный вызов, а 2 у клиентов — «сервер
        # отказал» (тот же довод, что у `fetch_slice.py`).
        return client.EXIT_OK if not stop.code else client.EXIT_USAGE
    env = client.settings(SCRIPT)
    key = env.get(client.KEY_ENV)
    try:
        if args.command in WRITES:
            # Слово — ПЕРВЫМ, до ключа и сети; в облаке — и по журналу окна.
            client.task_ordered_by(args.word)
            strazh.require_word_in_cloud(strazh.TASKS)
            return WRITES[args.command](args, env)
        return people(env) if args.command == "people" else mine(env)
    except client.ClientError as error:
        return client.fail(error, key)
    except Exception:                     # трассировка — только очищенная от ключа
        return client.crash(key)


if __name__ == "__main__":
    sys.exit(main())

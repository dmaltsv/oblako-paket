# -*- coding: utf-8 -*-
"""fetch_tasks.py — свежая выгрузка задач перед разбором планёрки (блок 4.3).

Симметричен `send_package.py`, но в обратную сторону: тот СДАЁТ разбор на
сервер, а этот ЗАБИРАЕТ снимок задач С сервера. Разбор всегда идёт по боевой
базе: она живёт на сервере, и собирать разбор по чему-то ещё нельзя — id и
тексты задач не совпадут, сервер откажет пакету.

Личность НЕ НАЗЫВАЕТСЯ: её предъявляет ключ доступа из `.env`, и сервер сам
знает, чей это круг. Выгружаются только сам предъявитель ключа и его люди:
руководитель — себя и членов своих команд, собственник — всю компанию.

Отдел (`--team`) НЕобязателен: без него — все свои люди, с ним — состав одного
отдела, чтобы планёрка одного не тянула задачи второго.

ЗДЕСЬ ЖЕ СВЕРЯЕТСЯ ВЕРСИЯ ФОРМАТА (блок 6). Снимок несёт версию сервера, а
выгрузка — первый шаг разбора: расхождение обязано выясниться ДО работы над
встречей, а не после неё. Разошлись — файл не пишется вовсе и код 1.

Режимы:
  (без ключей)  боевой: `GET /api/pc/export-tasks` по ключу доступа.
  --local       выгрузка из локальной базы командой сервера `bot.cli
                export-tasks` — работает только внутри репозитория проекта и
                требует `--actor <id>` (или `OBLAKO_ACTOR_ID` в `.env`).

Коды выхода — общие у обоих клиентов, см. `oblako_client`.

Примеры:
  python fetch_tasks.py --out "Разборы/13.07.26/tasks.json"
  python fetch_tasks.py --out "Разборы/13.07.26/tasks.json" --team Продажи
  python fetch_tasks.py --out "Разборы/13.07.26/tasks.json" --local --actor 1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import oblako_client as client

SCRIPT = Path(__file__).resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Выгрузка своих людей и их открытых задач для разбора планёрки")
    parser.add_argument("--out", required=True, help="куда сохранить снимок (tasks.json)")
    parser.add_argument("--team", help="отдел: номер или имя (без него — все свои люди)")
    parser.add_argument("--local", action="store_true",
                        help="выгрузить из локальной базы (только внутри репозитория проекта)")
    parser.add_argument("--actor", type=int, default=0,
                        help="id того, от чьего имени выгрузка — только для --local")
    return parser


def stamped(snapshot: dict, url: str) -> dict:
    """Снимок со штампом «откуда снят». Штамп стоит ПЕРЕД списком людей.

    Тот же порядок, что у серверной команды: шапку читают глазами, и длинный
    список людей не должен стоять между двумя её строками. Ключа в штампе нет —
    только адрес сервера и время.
    """
    people = snapshot.pop("people", [])
    snapshot["source"] = {"url": url, "at": datetime.now().isoformat(timespec="seconds")}
    snapshot["people"] = people
    return snapshot


def describe(snapshot: dict) -> str:
    """Шапка снимка словами — по ней сверяют, что разбирают свою планёрку."""
    actor = snapshot.get("actor") or {}
    team = snapshot.get("team")
    people = snapshot.get("people") or []
    tasks = sum(len(person.get("open_tasks") or []) for person in people)
    where = f"отдел «{team['name']}»" if team else "все свои отделы"
    return (f"Снимок от имени: {actor.get('name', '?')} (id {actor.get('id', '?')}) · "
            f"{where} · людей: {len(people)} · открытых задач: {tasks}")


def fetch(args, env: dict) -> int:
    key = client.access_key(env)
    url = client.base_url(env)
    query = {"team": args.team} if args.team else None
    snapshot = client.call("GET", "/api/pc/export-tasks", url=url, key=key,
                           timeout=client.TIMEOUT_READ_SEC, query=query)
    # Версия формата — ДО записи файла: снимок чужой версии нельзя ни разбирать,
    # ни оставлять на диске. Оставленный, он завтра прошёл бы за «снят сегодня»
    # (`meeting.py tasks` пропускает свежий снимок) и увёл бы разбор молча.
    client.check_export(snapshot)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stamped(snapshot, url), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"Выгрузка сохранена: {out}")
    print(describe(snapshot))
    print("Сверь, что это тот человек, чью планёрку разбираешь.")
    return client.EXIT_OK


def local(args, env: dict) -> int:
    """Локальная выгрузка: та же серверная команда, запущенная здесь.

    Путь файла разворачивается в абсолютный: команда выполняется из корня
    репозитория, и относительный путь лёг бы не туда, откуда его звали.
    """
    argv = ["export-tasks", "--actor", str(client.actor_id(env, args.actor)),
            "--out", str(Path(args.out).expanduser().resolve())]
    if args.team:
        argv += ["--team", args.team]
    Path(args.out).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return client.run_local(SCRIPT, argv)


def main(argv=None) -> int:
    client.setup_console()
    args = _parser().parse_args(argv)
    env = client.settings(SCRIPT)
    key = env.get(client.KEY_ENV)
    try:
        return local(args, env) if args.local else fetch(args, env)
    except client.ClientError as error:
        return client.fail(error, key)
    except OSError as error:
        return client.fail(client.Usage(f"Не удалось записать файл: {error}"), key)
    except Exception:                     # трассировка — только очищенная от ключа
        return client.crash(key)


if __name__ == "__main__":
    sys.exit(main())

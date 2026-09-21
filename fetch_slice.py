# -*- coding: utf-8 -*-
"""fetch_slice.py — срезы своих людей за период: закрыто, снято, перенесено, на сейчас.

Отвечает на вопрос руководителя и собственника «что сделал отдел за неделю»
(#540, спека #534, Р13). Близнец `fetch_tasks.py`: та же дорога к серверу —
личный ключ через `oblako_client`, — те же коды выхода 0 / 1 / 2 / 3 и тот же
штамп источника. Разница в том, ЧТО забирается: там открытые задачи для разбора
планёрки, здесь срез за период, который читают глазами. В пакет разбора срез не
входит, поэтому и версия формата у него своя (`oblako_client.SLICE_VERSION`).

СКИЛЛА У СРЕЗА НЕТ (Р13): агент находит команду в путеводителе пакета
(`AGENTS.md`) по фразам вроде «выгрузи закрытые задачи розницы за неделю», сам
переводит «за неделю» и «с прошлой пятницы» в две даты и пересказывает человеку
файл. Документа «Сводка недели» пакет не строит.

Личность НЕ НАЗЫВАЕТСЯ — её предъявляет ключ, а круг людей судит сервер: без
`--team` — все свои люди и сам предъявитель ключа (собственнику — вся компания),
с `--team` — состав одного отдела. Срез одного человека — это его запись в
выгрузке круга: отдельного вызова на человека нет. Личных задач в срезе нет ни у
кого, включая самого предъявителя ключа.

Даты обязательны, обе включительно, вида 2026-09-16; период не длиннее 92
дней. Судит их сервер, и второго судьи дат здесь нет: отказ приедет его фразой
с кодом 2.

ФАЙЛ ПИШЕТСЯ ТОЛЬКО ПОСЛЕ СВЕРКИ ФОРМАТА, как у выгрузки задач: ответ чужой
версии или старого сервера на диске не остаётся. Без `--out` он ложится в
`Срезы/` корня рабочей копии, и эта папка закрыта от git: в срезе задачи людей,
а пакет публикуется.

Коды выхода — общие у всех клиентов сервера, см. `oblako_client`.

Примеры:
  python fetch_slice.py --from 2026-09-13 --to 2026-09-19 --team Розница
  python fetch_slice.py --from 2026-09-12 --to 2026-09-19
  python fetch_slice.py --from 2026-09-16 --to 2026-09-17 --out "Срезы/Оля.json"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import fetch_tasks
import oblako_client as client

SCRIPT = Path(__file__).resolve()
SLICES_DIR = "Срезы"                 # папка выгрузок в корне рабочей копии (в git не едет)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Срезы своих людей за период: закрыто, снято, перенесено, на сейчас")
    parser.add_argument("--from", dest="date_from", required=True, metavar="ГГГГ-ММ-ДД",
                        help="первый день периода, например 2026-09-13")
    parser.add_argument("--to", dest="date_to", required=True, metavar="ГГГГ-ММ-ДД",
                        help="последний день периода, включительно")
    parser.add_argument("--team", metavar="ОТДЕЛ",
                        help="номер или имя отдела (без него — все свои люди)")
    parser.add_argument("--out", metavar="ФАЙЛ",
                        help=f"куда сохранить (без него — {SLICES_DIR}/ в корне работы)")
    return parser


def default_out(answer: dict) -> Path:
    """Путь без `--out`: `Срезы/<с>_<по>[ <отдел>].json` в корне рабочей копии.

    Период и отдел берутся ИЗ ОТВЕТА, а не из аргументов: сервер называет период
    каноническими датами, а отдел — именем, поэтому «--team 3» и «--team Розница»
    ложатся в один файл, а не в два. Символы, которых не терпит имя файла на
    Windows, заменяются: имя отдела заводит человек, и оно бывает любым.
    """
    period = answer.get("period") or {}
    name = f"{period.get('from')}_{period.get('to')}"
    team = answer.get("team")
    if team:
        name += f" {team.get('name')}"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return client.work_root(SCRIPT) / SLICES_DIR / f"{name}.json"


def describe(answer: dict) -> str:
    """Итог выгрузки: чей круг, за какой период и сколько чего.

    Счёт идёт по разделам «за период»: закрыто и снято — задачами, перенесено —
    задачами, а не переносами (одну задачу двигали трижды — она одна).

    СУЖЕННЫЕ СРЕЗЫ НАЗВАНЫ ПОИМЁННО второй строкой (#538, #563): у собственника
    другой видит только свои поручения ему и задачи с общих встреч, и такой срез,
    пересказанный как полный, выдал бы часть за целое. Судит сервер
    (`assignments_only`), здесь — только показ.
    """
    actor = answer.get("actor") or {}
    team = answer.get("team")
    period = answer.get("period") or {}
    people = answer.get("people") or []

    def tasks(section: str) -> int:
        return sum(len(day.get("tasks") or [])
                   for one in people for day in one.get(section) or [])

    moved = sum(len(one.get("moved") or []) for one in people)
    where = f"отдел «{team['name']}»" if team else "все свои люди"
    said = (f"Срезы от имени: {actor.get('name', '?')} (id {actor.get('id', '?')}) · "
            f"{where} · {period.get('from', '?')} — {period.get('to', '?')} · "
            f"людей: {len(people)} · закрыто: {tasks('closed')} · "
            f"снято: {tasks('dropped')} · перенесено: {moved}")
    narrowed = [(one.get("person") or {}).get("name", "?")
                for one in people if one.get("assignments_only")]
    if narrowed:
        said += ("\nПоказаны только твои поручения и задачи с общих встреч: "
                 f"{', '.join(narrowed)}")
    return said


def fetch(args, env: dict) -> int:
    key = client.access_key(env)
    url = client.base_url(env)
    answer = client.export_slice(url=url, key=key, date_from=args.date_from,
                                 date_to=args.date_to, team=args.team)
    out = Path(args.out).expanduser() if args.out else default_out(answer)
    out.parent.mkdir(parents=True, exist_ok=True)
    # `newline="\n"`: на Windows `write_text` иначе пишет CRLF, и один и тот же
    # срез давал бы на двух машинах два разных файла.
    out.write_text(json.dumps(fetch_tasks.stamped(answer, url), ensure_ascii=False, indent=2),
                   encoding="utf-8", newline="\n")
    print(f"Срезы сохранены: {out}")
    print(describe(answer))
    return client.EXIT_OK


def main(argv=None) -> int:
    client.setup_console()
    try:
        args = _parser().parse_args(argv)
    except SystemExit as stop:
        # argparse выходит кодом 2 на негодный вызов, а 2 у клиентов — «сервер
        # отказал». Забытую дату агент отправил бы проверять ключ и отдел.
        return client.EXIT_OK if not stop.code else client.EXIT_USAGE
    env = client.settings(SCRIPT)
    key = env.get(client.KEY_ENV)
    try:
        return fetch(args, env)
    except client.ClientError as error:
        return client.fail(error, key)
    except OSError as error:
        return client.fail(client.Usage(f"Не удалось записать файл: {error}"), key)
    except Exception:                     # трассировка — только очищенная от ключа
        return client.crash(key)


if __name__ == "__main__":
    sys.exit(main())

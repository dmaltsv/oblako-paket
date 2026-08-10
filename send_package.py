# -*- coding: utf-8 -*-
"""send_package.py — сдача разбора планёрки на сервер Oblako (блок 4.3).

Пакет — это JSON с задачами-кандидатами, собранный при разборе расшифровки
планёрки после команды человека «запиши». Здесь он уезжает на сервер по HTTP
личным ключом доступа: `ssh` и `scp` из контура ПК ушли целиком (решение
3.5.24), второго пути к серверу не остаётся ни у кого.

АВТОР РАЗБОРА — ПРЕДЪЯВИТЕЛЬ КЛЮЧА. Поля `author_id`/`author_name` внутри файла
не значат ничего: сервер подставляет автора сам (вторая половина инварианта 9).
Называть себя ключом командной строки поэтому нечем и незачем.

ОТДЕЛ (`--team`) ОБЯЗАТЕЛЕН: по составу названного отдела судятся пункты пакета,
и в его чат уходит итог. Угадывать отдел система права не имеет — руководитель
вправе вести несколько (решение 3.5.21).

ГЕЙТ «ЗАПИШИ» ДЕРЖИТ И ЗДЕСЬ. Рядом с файлом пакета обязано лежать
`Подтверждение.json` с тем же отпечатком и тем же отделом — иначе отправки нет.
Дверей к серверу две (эта и `meeting.py send`), и гейт, стоящий у одной,
держался бы честным словом инструкции. Проверку ведёт `oblako_client.
require_confirmation` — она одна на обоих клиентов.

ПРИМЕНЕНИЕ И ПУБЛИКАЦИЯ ИДУТ ОДНИМ ВЫЗОВОМ. Ручка сервера применяет пакет,
рассылает уведомления и публикует итог в чате отдела; отдельного «применить, не
публикуя» у неё нет. Флаг `--publish` поэтому нужен только локальному режиму,
где работает серверная команда со своими ключами.

Режимы:
  --package ФАЙЛ   сдать разбор: `POST /api/pc/meeting-package?team=…`
  --publish-only   ТОЛЬКО досдать итог последней планёрки отдела:
                   `POST /api/pc/publish-package?team=…`. Нужен, когда пост в
                   группу ушёл наполовину или файла пакета уже нет под рукой:
                   повторная сдача того же файла итог НЕ досдаёт — сервер
                   честно отдаёт сохранённый исход и в чат второй раз не идёт.
  --dry-run        показать, что уедет, и не отправлять ничего
  --local          выполнить серверной командой здесь же (только внутри
                   репозитория проекта), нужен `--actor <id>`

Повторная сдача того же файла безопасна: сервер узнаёт применённый пакет и
второй раз задачи не заводит. Исправленный разбор подаётся НОВЫМ файлом —
«одна открытая задача — одна строка», и доприменять пакет по частям нечем.

Коды выхода — общие у обоих клиентов, см. `oblako_client`. Отдельно стоит
четвёртый: пакет применён, а итог опубликован не полностью — это не успех и не
повод повторять применение.

Примеры:
  python send_package.py --package "Разборы/13.07.26/package.json" --team Продажи
  python send_package.py --package "Разборы/13.07.26/package.json" --team 1 --dry-run
  python send_package.py --publish-only --team Продажи
  python send_package.py --package "…/package.json" --team 1 --local --actor 1 --publish
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import oblako_client as client

SCRIPT = Path(__file__).resolve()

# Как досдать итог — одной строкой, годной для копирования. Печатается ровно
# там, где публикация не доведена: человеку в этот момент нужна команда, а не
# рассказ о том, что бывает.
HINT_PUBLISH_ONLY = 'Досдать итог: python send_package.py --publish-only --team "{team}"'


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Сдача разбора планёрки на сервер Oblako")
    parser.add_argument("--package", help="путь к package.json")
    parser.add_argument("--publish-only", action="store_true", dest="publish_only",
                        help="только опубликовать итог последней планёрки отдела")
    # Отдел обязателен в обоих режимах и проверяется здесь, а не на сервере:
    # сказать об этом до отправки честнее, чем после.
    parser.add_argument("--team", help="отдел разбора: номер или имя (обязателен)")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="показать, что уедет, и ничего не отправлять")
    # Пара называет ОЖИДАЕМУЮ встречу у досдачи: сервер иначе публикует последний
    # применённый пакет отдела, каким бы он ни был. Обе или ни одной.
    parser.add_argument("--meeting-date", dest="meeting_date",
                        help="досдача: дата встречи из пакета (ISO)")
    parser.add_argument("--meeting-kind", dest="meeting_kind",
                        help="досдача: вид встречи из пакета")
    parser.add_argument("--publish", action="store_true",
                        help="локальный режим: опубликовать итог (по ключу он публикуется всегда)")
    parser.add_argument("--local", action="store_true",
                        help="выполнить серверной командой здесь (только внутри репозитория)")
    parser.add_argument("--actor", type=int, default=0,
                        help="id того, от чьего имени разбор — только для --local")
    return parser


def check_args(args) -> None:
    """Взаимоисключающее и обязательное — до чтения файлов и до сети."""
    if args.publish_only and args.package:
        raise client.Usage("--publish-only и --package вместе не работают: "
                           "досдача итога пакета не касается")
    if not args.publish_only and not args.package:
        raise client.Usage("Нечего сдавать: назови файл пакета --package <файл> "
                           "или досдай итог --publish-only")
    client.team(args.team)


def load_package(path: str) -> tuple[bytes, dict]:
    """Байты файла и разобранный пакет. Уезжают именно БАЙТЫ, не пересборка.

    Из исходных байтов сервер считает отпечаток пакетов, применённых до блока
    4.2, — пересериализованный файл перестал бы узнаваться, и старый разбор
    завёл бы все задачи заново. Разбор здесь нужен только для превью и проверки
    «это вообще JSON».
    """
    file = Path(path).expanduser()
    try:
        raw = file.read_bytes()
    except OSError as error:
        raise client.Usage(f"Пакет не прочитать: {error}") from None
    if len(raw) > client.MAX_PACKAGE_BYTES:
        raise client.Usage(
            f"Пакет больше предела сервера ({len(raw)} б > {client.MAX_PACKAGE_BYTES} б) — "
            f"раздели планёрку на два пакета")
    try:
        package = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise client.Usage(f"Пакет не разобрать: {file} — это не JSON") from None
    if not isinstance(package, dict):
        raise client.Usage(f"Пакет не того вида: {file} — ожидается объект JSON")
    return raw, package


def preview(package: dict, team: str, where: str) -> str:
    """Что уедет — словами, без отправки. Ответ на `--dry-run`.

    ПРЕВЬЮ МЕСТНОЕ И НИЧЕГО НЕ ПРОВЕРЯЕТ. Прежний `-DryRun` звал
    `apply-package --dry-run` и показывал план по боевой базе; у ручки контура
    ПК режима «покажи, но не применяй» нет, и выдумывать его клиент не вправе.
    Пакет по-прежнему судит сервер — целиком, до первой записи и со списком
    причин, — поэтому «отправить и получить отказ» ничего не портит. Прежний
    план по базе остался у `--local --dry-run`.
    """
    meeting = package.get("meeting") or {}
    items = package.get("items") or []
    by_op: dict[str, int] = {}
    for item in items:
        by_op[str(item.get("op", "?"))] = by_op.get(str(item.get("op", "?")), 0) + 1
    parts = ", ".join(f"{op}: {count}" for op, count in sorted(by_op.items())) or "пусто"
    return (f"Уехало бы: {meeting.get('kind', 'встреча')} {meeting.get('date', '')} · "
            f"отдел «{team}» · пунктов {len(items)} ({parts})\n"
            f"Адрес: {where}\n"
            f"Ничего не отправлено (--dry-run); пакет проверит сервер при отправке.")


def publication_lines(publication: dict, team: str) -> tuple[list, int]:
    """Исход публикации словами и код выхода. Ровно те же три исхода, что у сервера.

    Неполный исход — свой код возврата, а не успех: задачи в списках, а итог в
    группе неполон, и починить это можно только досдачей.

    ЧЕТВЁРТЫЙ ИСХОД, `skipped`, ДОСДАЧЕЙ НЕ ЧИНИТСЯ. Так отвечает отчёт, который
    публиковать нельзя в принципе: применён до блока E, снят по другому отделу
    или незнакомой версии. Подсказка про `--publish-only` здесь была бы дорогой в
    тупик — та же дверь ответит тем же отказом.
    """
    status = publication.get("status")
    sent = publication.get("parts_sent", 0)
    total = publication.get("parts_total", 0)
    if status == "ok":
        if publication.get("repeat"):
            return [f"Итог уже был опубликован раньше (частей: {total})."], client.EXIT_OK
        return [f"Итог опубликован в группе (частей: {total})."], client.EXIT_OK
    if status == "partial":
        line = f"Опубликовано {sent} из {total} — загляни в группу перед повтором."
    elif status == "unknown":
        line = (f"Подтверждено {sent} из {total} — исход следующей части неизвестен, "
                f"загляни в группу перед повтором.")
    else:
        return ([f"Итог не опубликован: {publication.get('reason', 'причина не названа')}.",
                 "Досдать его нечем — этот отчёт не публикуется ни одной командой; "
                 "задачи при этом применены."], client.EXIT_PUBLISH_INCOMPLETE)
    return [line, HINT_PUBLISH_ONLY.format(team=team)], client.EXIT_PUBLISH_INCOMPLETE


def report_lines(body: dict) -> list:
    """Отчёт применения: что легло в списки и кому ушли уведомления."""
    report = body.get("report") or {}
    meeting = report.get("meeting") or {}
    team = (body.get("team") or {}).get("name", "?")
    counts = report.get("counts") or {}
    if body.get("already_applied"):
        return [f"Этот пакет уже применялся ({body.get('applied_at', 'когда — не записано')}) "
                f"— задачи не тронуты."]
    lines = [f"Пакет применён: {meeting.get('kind', 'встреча')} {meeting.get('date', '')} · "
             f"отдел «{team}»",
             f"  себе: {counts.get('own', 0)} · другим: {counts.get('assigned', 0)}"]
    delivery = body.get("delivery")
    if delivery:
        lines.append(f"  уведомления: доставлено {delivery.get('sent', 0)}, "
                     f"не дошло {delivery.get('failed', 0)}, "
                     f"без Telegram {delivery.get('unreachable', 0)}")
        if delivery.get("failed"):
            lines.append("  недоставленные уведомления не страшны: задачи в списках, "
                         "получатели увидят их в утреннем брифе.")
    return lines


def send(args, env: dict) -> int:
    # Ключ спрашивается ПОСЛЕ ветки превью: `--dry-run` обещает «показать и не
    # отправлять», и на ещё не настроенной машине это обещание обязано работать.
    url = client.base_url(env)
    raw, package = load_package(args.package)
    if args.dry_run:
        print(preview(package, args.team, url + "/api/pc/meeting-package"))
        return client.EXIT_OK
    # Гейт «запиши» — ДО ключа и до сети. Дверей к серверу две, и держать он
    # обязан у обеих: инструкция «пиши только в черновик» гейтом не является.
    client.require_confirmation(Path(args.package).expanduser(), args.team)
    key = client.access_key(env)
    body = client.call("POST", "/api/pc/meeting-package", url=url, key=key,
                       timeout=client.TIMEOUT_PACKAGE_SEC,
                       query={"team": args.team}, body=raw)
    lines = report_lines(body)
    team = (body.get("team") or {}).get("name") or args.team
    published, code = publication_lines(body.get("publication") or {}, team)
    print("\n".join(lines + published))
    return code


def publish_only(args, env: dict) -> int:
    url = client.base_url(env)
    if args.dry_run:
        # Показать сам пост здесь нечем: он собирается из СОХРАНЁННОГО на
        # сервере отчёта, а ручки «покажи пост» у контура ПК нет. Превью
        # честно говорит, что уйдёт и куда, и предупреждает о повторе.
        print(f"Уехал бы запрос на публикацию итога отдела «{args.team}»\n"
              f"Адрес: {url}/api/pc/publish-package\n"
              f"Досдача публикует ЗАНОВО: уже долетевшие части появятся в чате "
              f"второй раз — загляни в группу до запуска.\n"
              f"Ничего не отправлено (--dry-run).")
        return client.EXIT_OK
    key = client.access_key(env)
    # Ожидаемая встреча едет вместе с отделом, когда её знают. Сервер публикует
    # ПОСЛЕДНИЙ применённый пакет отдела, а это не всегда пакет того разбора,
    # из которого пришли: планёрку и 1:1 одного отдела разбирают в один день.
    query = {"team": args.team}
    if args.meeting_date and args.meeting_kind:
        query["meeting_date"] = args.meeting_date
        query["meeting_kind"] = args.meeting_kind
    body = client.call("POST", "/api/pc/publish-package", url=url, key=key,
                       timeout=client.TIMEOUT_PUBLISH_SEC, query=query)
    meeting = body.get("meeting") or {}
    team = (body.get("team") or {}).get("name") or args.team
    published, code = publication_lines(body.get("publication") or {}, team)
    print("\n".join([f"Итог планёрки: {meeting.get('kind', 'встреча')} "
                     f"{meeting.get('date', '')} · отдел «{team}»"] + published))
    return code


def local(args, env: dict) -> int:
    """Тот же серверный CLI, запущенный здесь. Флаги — один в один его."""
    if args.publish_only:
        argv = ["publish-package", "--team", args.team]
        if args.dry_run:
            argv.append("--dry-run")
        return client.run_local(SCRIPT, argv)
    argv = ["apply-package", str(Path(args.package).expanduser().resolve()),
            "--actor", str(client.actor_id(env, args.actor)), "--team", args.team]
    if args.dry_run:
        argv.append("--dry-run")
    if args.publish:
        argv.append("--publish")
    return client.run_local(SCRIPT, argv)


def main(argv=None) -> int:
    client.setup_console()
    args = _parser().parse_args(argv)
    env = client.settings(SCRIPT)
    key = env.get(client.KEY_ENV)
    try:
        check_args(args)
        if args.local:
            return local(args, env)
        return publish_only(args, env) if args.publish_only else send(args, env)
    except client.ClientError as error:
        return client.fail(error, key)
    except Exception:                     # трассировка — только очищенная от ключа
        return client.crash(key)


if __name__ == "__main__":
    sys.exit(main())

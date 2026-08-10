# -*- coding: utf-8 -*-
"""install_skills.py — подключение команд разбора к Claude Code и к Codex (блок 5).

СОДЕРЖИМОЕ ОБЩЕЕ, ПОДКЛЮЧЕНИЕ — СВОЁ У КАЖДОГО КЛИЕНТА. Инструкции живут в одной
папке `Скиллы/` и правятся в одном месте. Клиенты ищут скиллы каждый в своей
папке (`.claude/skills/` и `.codex/skills/`), поэтому «одна папка и одна ссылка
на оба» не работает — работают два тонких подключения поверх общего содержимого.

ПОДКЛЮЧЕНИЕ — УКАЗАТЕЛЬ, А НЕ КОПИЯ. В папку клиента кладётся `SKILL.md` из
шапки общей инструкции и одной строки «читай вот этот файл». Копия расходилась бы
с оригиналом молча: поправил одну — вторая осталась прежней, и два клиента стали
бы работать по-разному. Симлинк тоже не годится: на Windows он требует особых
прав, а пакет разворачивают на чужой машине без администратора.

Формат `SKILL.md` у обоих клиентов один — YAML-шапка с `name` и `description`, —
поэтому шапка общей инструкции переносится в указатель дословно, и второго места,
где описан скилл, не заводится.

    python install_skills.py            подключить в этой рабочей копии
    python install_skills.py --check    что подключено и куда
    python install_skills.py --home     подключить глобально (все проекты)

Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import oblako_client as client

SCRIPT = Path(__file__).resolve()
SKILLS_DIR = SCRIPT.parent / "Скиллы"

# Папка скиллов у каждого клиента своя — это и есть весь список различий.
CLIENTS = {"Claude Code": ".claude/skills", "Codex": ".codex/skills"}

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
NAME = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)

POINTER = """---
{head}
---

Инструкция целиком — в общей папке команд:

    {source}

Прочитай этот файл и исполняй его. Здесь её текста нет намеренно: содержимое
общее для всех клиентов, а это — только подключение. По памяти не пересказывай.

Скрипты, которые она зовёт, лежат в папке:

    {home}

Команды в инструкции написаны ОТ НЕЁ: `python meeting.py …` значит
`python "{home}{sep}meeting.py" …`. Подставляй этот путь — рабочая папка у тебя
может быть любой, а папка команд одна.
"""


def read_skill(path: Path) -> tuple:
    """(имя, шапка) общей инструкции. Имя задаёт папку скилла у клиента."""
    text = path.read_text(encoding="utf-8")
    head = FRONTMATTER.match(text)
    if head is None:
        raise client.Usage(f"{path.name}: нет YAML-шапки — клиент такой скилл не увидит")
    name = NAME.search(head.group(1))
    if name is None:
        raise client.Usage(f"{path.name}: в шапке нет строки «name:»")
    return name.group(1), head.group(1)


def skills() -> list:
    """Общие инструкции: (имя, шапка, файл)."""
    found = [(*read_skill(path), path) for path in sorted(SKILLS_DIR.glob("*.md"))]
    if not found:
        raise client.Usage(f"В {SKILLS_DIR} нет ни одной инструкции")
    return found


def targets(home: bool) -> Path:
    """Куда подключаем: домашняя папка (все проекты) или эта рабочая копия.

    Рабочую копию ищет `oblako_client.work_root` — она же отвечает на этот
    вопрос механике разбора. «Родитель папки скриптов» тут не годится: в
    установочном пакете скрипты лежат в КОРНЕ, и такой ответ увёл бы папки
    скиллов выше клона — агент, открытый в клоне, не увидел бы ни одной команды,
    а запись прошла бы успешно.
    """
    return Path.home() if home else client.work_root(SCRIPT)


def pointers(root: Path):
    """Указатели, которые ДОЛЖНЫ лежать: (клиент, файл, нужный текст, совпадает).

    Совпадение проверяется по СОДЕРЖИМОМУ, а не по наличию файла: указатель несёт
    абсолютный путь этой машины, и перенос рабочей копии в другую папку оставляет
    файл на месте, а ведёт он уже в никуда.

    Отделено от печати ради проверки установки (`setup_check.py`), которой нужен
    счёт, а не восемь строк в чужом отчёте. Второй счётчик, свой у проверки,
    однажды разошёлся бы с этим — и она хвалила бы неподключённое.
    """
    for name, head, source in skills():
        # Путь до папки команд подставляет ТО ЖЕ место, что знает путь до самой
        # инструкции. Иначе он попал бы в текст скилла литералом — а он разный:
        # в установочном пакете скрипты лежат в корне, в репозитории проекта —
        # в `Пакет/`, и написанный литералом путь врал бы в одном из двух.
        body = POINTER.format(head=head, source=source,
                              home=SCRIPT.parent, sep=os.sep)
        for agent, folder in CLIENTS.items():
            target = root / folder / name / "SKILL.md"
            same = target.is_file() and target.read_text(encoding="utf-8") == body
            yield agent, target, body, same


def install(root: Path, dry: bool) -> int:
    """Разложить указатели по папкам клиентов. `dry` — только показать состояние."""
    stale = 0
    for agent, target, body, same in pointers(root):
        if dry:
            stale += 0 if same else 1
            mark = "✔" if same else ("устарел" if target.is_file() else "нет")
            print(f"  {agent:12} {mark:8} {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(f"  {agent:12} {'уже подключён' if same else 'подключён'}: {target}")
    return stale


def main(argv=None) -> int:
    client.setup_console()
    parser = argparse.ArgumentParser(description="Подключение команд разбора к клиентам")
    parser.add_argument("--home", action="store_true",
                        help="подключить глобально, а не в этой рабочей копии")
    parser.add_argument("--check", action="store_true", help="только показать состояние")
    args = parser.parse_args(argv)

    try:
        root = targets(args.home)
        print(f"Команды: {', '.join(name for name, _, _ in skills())}")
        print(f"Куда: {root}")
        stale = install(root, dry=args.check)
    except client.ClientError as error:
        return client.fail(error)
    except OSError as error:
        return client.fail(client.Usage(f"Не удалось записать подключение: {error}"))
    if args.check:
        print("Подключено всё." if not stale
              else f"Не подключено или устарело: {stale}. Запусти без --check.")
        return client.EXIT_OK if not stale else client.EXIT_USAGE
    print("Клиент подхватит их при следующем запуске — перезапусти его.")
    return client.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
import os
import sys
import glob
import json
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oblako_client                      # noqa: E402  — путь к соседям задан строкой выше

# ============================================================================
#  Расшифровка аудио через Deepgram (Nova-3) — БЕЗ имён говорящих.
#
#  Одиночная запись: диктофон, 1:1 без Zoom, кусок разговора. Спикеры выходят
#  безымянными («Спикер 1/2/3») — имена умеет только `zoom_deepgram_merge.py`,
#  и планёрку разбирают им, а не этим файлом.
#
#      python transcribe.py "<аудиофайл или папка>"
#      python transcribe.py            # без аргумента — папка "Аудио" рядом
#
#  Зависимостей нет — нужен только установленный Python (3.8+). Windows и macOS
#  — один и тот же путь: запускалок под одну ОС здесь нет.
#  Ключ Deepgram — переменная окружения DEEPGRAM_API_KEY или `.env` (ищется от
#  папки скрипта вверх, как у клиентов сервера).
# ============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def pause():
    """Ждёт Enter только при интерактивном запуске (двойной клик по лаунчеру).
    Под управлением ИИ-агента или в пайпе stdin не TTY — тогда не зависаем."""
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nНажмите Enter для выхода...")
    except Exception:
        pass


def load_api_key():
    """DEEPGRAM_API_KEY: переменная окружения, затем ближайший `.env` вверх.

    `.env` читает `oblako_client`, а не свой разбор: у пакета один формат файла
    на все скрипты, и второй парсер разошёлся бы с первым молча — на кавычках,
    на BOM или на пробеле вокруг `=`.
    """
    key = os.environ.get("DEEPGRAM_API_KEY")
    if key:
        return key.strip()
    return oblako_client.settings(__file__).get("DEEPGRAM_API_KEY") or None


# --- Настройки распознавания (менять обычно не нужно) -----------------------
# nova-3 + multi = самая точная модель + ловит английские слова в русской речи.
MODEL = "nova-3"
LANGUAGE = "multi"
# Примерная цена для оценки в логе (Nova-3 Multilingual + диаризация).
PRICE_PER_MIN = 0.0092 + 0.0020

QUERY = (
    f"model={MODEL}"
    f"&language={LANGUAGE}"
    "&smart_format=true"   # пунктуация, числа, форматирование
    "&punctuate=true"
    "&diarize=true"        # разделение по спикерам
    "&utterances=true"     # реплики с привязкой к спикеру (для красивого вывода)
)

MIME_BY_EXT = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".ogg": "audio/ogg", ".flac": "audio/flac", ".amr": "audio/amr",
}


def deepgram_transcribe(file_path, api_key=None):
    """Отправляет аудиофайл целиком в Deepgram и возвращает разобранный JSON-ответ.
    Ключ: аргумент -> переменная окружения -> ближайший `.env` вверх от скрипта
    (импортируемо из других модулей)."""
    key = api_key or load_api_key()
    if not key:
        raise RuntimeError(
            f"не найден ключ DEEPGRAM_API_KEY (окружение или .env от {SCRIPT_DIR} вверх)"
        )
    with open(file_path, "rb") as f:
        audio_bytes = f.read()
    ext = os.path.splitext(file_path)[1].lower()
    mime = MIME_BY_EXT.get(ext, "audio/mpeg")
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?{QUERY}",
        data=audio_bytes,
        method="POST",
        headers={"Authorization": f"Token {key}", "Content-Type": mime},
    )
    # Таймаут с запасом: загрузка файла + обработка на сервере.
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)


def format_speakers(resp):
    """Склеивает реплики Deepgram в текст вида '**Спикер N:** ...',
    объединяя подряд идущие реплики одного говорящего в один абзац."""
    results = resp.get("results", {})
    utterances = results.get("utterances") or []
    if utterances:
        blocks, cur, buf = [], None, []
        for u in utterances:
            spk = u.get("speaker", 0)
            txt = (u.get("transcript") or "").strip()
            if not txt:
                continue
            if spk != cur:
                if buf:
                    blocks.append(f"**Спикер {cur + 1}:** " + " ".join(buf))
                buf, cur = [], spk
            buf.append(txt)
        if buf:
            blocks.append(f"**Спикер {cur + 1}:** " + " ".join(buf))
        return "\n\n".join(blocks)
    # Запасной вариант — сплошной текст без спикеров.
    try:
        return results["channels"][0]["alternatives"][0]["transcript"].strip()
    except Exception:
        return ""


# --- Видео-форматы: их Deepgram напрямую не принимает -----------------------
VIDEO_EXT = {".mkv", ".mp4", ".mov", ".avi", ".webm"}


def find_audio_in(folder):
    """Список аудиофайлов поддерживаемых форматов в одной папке."""
    files = []
    for ext in MIME_BY_EXT:
        files.extend(glob.glob(os.path.join(folder, f"*{ext}")))
    return files


def output_file_for(audio_file):
    """Путь транскрипта рядом с аудио (в той же папке сессии).
    Имя по умолчанию фиксированное — 'Транскрипт.md'. Если в папке больше одного
    аудио, используем '<имя аудио>.md', чтобы транскрипты не перезаписали друг друга."""
    folder = os.path.dirname(audio_file)
    if len(find_audio_in(folder)) > 1:
        basename = os.path.splitext(os.path.basename(audio_file))[0]
        return os.path.join(folder, f"{basename}.md")
    return os.path.join(folder, "Транскрипт.md")


def resolve_jobs(arg):
    """Превращает аргумент (файл ИЛИ папка) в список пар (аудиофайл, файл_транскрипта).
    Транскрипт всегда пишется рядом с аудио — в той же папке сессии.

    Поддерживает:
      • один аудиофайл -> транскрипт рядом с ним;
      • любую папку -> рекурсивный обход дерева, собрать ВСЁ аудио
        (режим «обновить всё»);
      • видео и неподдерживаемые форматы отсеиваются."""
    target = arg.strip().strip('"').strip("'")

    # --- Один файл ---------------------------------------------------------
    if os.path.isfile(target):
        ext = os.path.splitext(target)[1].lower()
        name = os.path.basename(target)
        if ext in VIDEO_EXT:
            print(f"'{name}' — это видео ({ext}), Deepgram принимает только аудио.")
            print("Возьмите звуковую дорожку встречи: у облачной записи Zoom это файл M4A,")
            print("у локальной — audio_only.m4a рядом с видео.")
            return []
        if ext not in MIME_BY_EXT:
            print(f"Формат {ext} не поддерживается. Нужен mp3/wav/m4a/ogg/flac/amr.")
            return []
        return [(target, output_file_for(target))]

    if not os.path.isdir(target):
        print(f"Ошибка: '{target}' — не существует (ни файл, ни папка).")
        return []

    # --- Любая другая папка: рекурсивный обход всего дерева ----------------
    audio = []
    for root, _, _ in os.walk(target):
        audio.extend(find_audio_in(root))
    return [(f, output_file_for(f)) for f in audio]


def main():
    """Запуск из командной строки / лаунчера. При импорте модуля не выполняется."""
    if not load_api_key():
        print("ОШИБКА: не найден ключ DEEPGRAM_API_KEY.")
        print("Ищу в переменной окружения и в .env от папки скрипта вверх.")
        print(f"Создайте файл .env (папка: {SCRIPT_DIR}) с одной строкой:")
        print("DEEPGRAM_API_KEY=ваш_ключ_от_deepgram")
        pause()
        return 1

    # --- Сбор заданий -------------------------------------------------------
    if len(sys.argv) > 1 and sys.argv[1].strip():
        jobs = resolve_jobs(sys.argv[1])
    else:
        # Без аргумента — старое поведение: папка 'Аудио' рядом со скриптом,
        # транскрипты в соседнюю 'Расшифровки' (по имени аудио).
        default_audio = os.path.join(SCRIPT_DIR, "Аудио")
        os.makedirs(default_audio, exist_ok=True)
        default_out = os.path.join(SCRIPT_DIR, "Расшифровки")
        jobs = [
            (f, os.path.join(default_out, os.path.splitext(os.path.basename(f))[0] + ".md"))
            for f in find_audio_in(default_audio)
        ]

    if not jobs:
        print("\nНечего расшифровывать — новых аудиофайлов не найдено.")
        pause()
        return 0

    print(f"\nК обработке файлов: {len(jobs)}\n")

    for file_path, output_file in jobs:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        basename = os.path.splitext(os.path.basename(file_path))[0]

        if os.path.exists(output_file):
            print(f"[Пропуск] '{basename}' уже расшифрован (.md существует).")
            continue

        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"[{basename}] Отправляю в Deepgram ({size_mb:.0f} МБ)... подождите ~минуту.")

        try:
            resp = deepgram_transcribe(file_path)
        except urllib.error.HTTPError as e:
            print(f"[{basename}] Ошибка Deepgram: HTTP {e.code} {e.reason}")
            print("   " + e.read().decode(errors="replace")[:400])
            continue
        except Exception as e:
            print(f"[{basename}] Ошибка: {e}")
            continue

        text = format_speakers(resp)
        if len(text.strip()) < 100:
            print(f"[{basename}] ВНИМАНИЕ: пустой/слишком короткий ответ. Файл не сохранён.")
            continue

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(text)

        try:
            dur = float(resp.get("metadata", {}).get("duration", 0))
            cost = (dur / 60.0) * PRICE_PER_MIN
            print(f"[{basename}] Готово! Сохранено ({len(text)} симв., {dur/60:.0f} мин). ~${cost:.3f}")
        except Exception:
            print(f"[{basename}] Готово! Сохранено ({len(text)} симв.).")

    print("\nВся работа завершена!")
    pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())

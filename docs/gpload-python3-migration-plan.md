# План миграции gpload на Python 3.10.15

Документ фиксирует анализ `script/gpload.py` и пошаговый план переноса на Python 3.10.15.

- Исходник: `script/gpload.py` (2747 строк, Python 2).
- Резервная копия для сравнения: `script/gpload.py.py2-backup`.
- Контрольная сумма обеих копий на момент создания: `b1220ef47b62c1b98929b789be5e1cc597155e22cc1f21b5e1c31b8af5d30f7f`.
- Миграция выполняется в отдельном репозитории; этот файл и backup используются как baseline для diff.

## Принятые решения

1. **Кластер Greenplum пока недоступен.** Начинаем с unit-тестов, fake `pg` и fake `gpfdist`. Реальный интеграционный прогон — отдельная фаза, когда появится кластер.
2. **Кроссплатформенность сохраняем.** Ветки Windows/Unix/HP-UX не вырезаем, а адаптируем под Python 3.
3. **PyGreSQL** — Python-драйвер PostgreSQL/Greenplum, который gpload использует для подключения (`from pygresql import pg`). Версию выбираем на отдельном spike-шаге под Python 3.10.15 и фиксируем в `requirements.txt`.
4. **Поддерживаем только Python 3.** Обратная совместимость с Python 2 не нужна.
5. **Имена reusable-объектов важны.** `shortname`, `jenkins` и md5-схему имён `staging_gpload_reusable_*` сохраняем; hash-поведение проверяем тестами.
6. **Мёртвый код удаляем.** `keywords`, `is_keyword`, `Progress` — удалить. `jenkins`/`shortname` оставить, даже если сейчас не вызываются, из-за п.5.

## 1. Как работает gpload целиком

Точка входа (`script/gpload.py:2744`):

```python
g = gpload(sys.argv[1:])
g.run()
sys.exit(g.exitValue)
```

Логический конвейер:

```
CLI-аргументы
  -> загрузка и двукратная проверка YAML
  -> нормализация конфига (unicode + lower keys)
  -> read_config (table/schema + параметры подключения)
  -> setup_connection (PyGreSQL)
  -> read_table_metadata (колонки/типы/serial)
  -> read_columns / read_mapping
  -> start_gpfdists (запуск gpfdist, сбор URL)
  -> do_method (insert / update / merge)
  -> cleanup (drop temp, kill gpfdist, потоки)
```

### Блок A. Заголовок, импорты, проверки (1–65)
- shebang `#!/usr/bin/env python` и проверка `sys.hexversion < 2.4.4`.
- обязательный `yaml`; `pygresql.pg` с отдельной диагностикой для 64-битного Windows.
- импорты `hashlib`, `datetime`, `getpass`, `os`, `signal`, `socket`, `subprocess`, `threading`, `time`, `traceback`, `uuid`.
- `windowsPlatform` и `select` только для не-Windows.
- Глобали: `EXECNAME`, `NUM_WARN_ROWS`, позже `received_kill`.

### Блок B. Грамматика control-файла (71–543)
- `valid_tokens` — словарь допустимых ключей YAML: для каждого ключа указано, где он может находиться (`parent`) и надо ли проверять вложенные ключи (`parse_children`).
- `keywords` — огромный список SQL-слов и `is_keyword()`. Фактически мёртвый код.
- `_abbrevs` — суффиксы для `bytestr`.

### Блок C. Работа с SQL-идентификаторами (546–695)
- `caseInsensitiveDictLookup` — регистронезависимый поиск ключа.
- `sqlIdentifierCompare` — сравнение по правилам SQL: без кавычек — lower, в кавычках — как есть.
- `isDelimited`, `convertListToDelimited`, `quote_ident`, `quote_unident`.
- `splitUpMultipartIdentifier` — разбор `schema.table` с учётом кавычек.
- `splitIntoLiteralsAndNonLiterals` — лексер строковых литералов (для `update_condition`).

### Блок D. NOTICE, сигналы, размеры, потоки (698–866)
- `notice_processor` читает `db.notices()` и вытаскивает число ошибок форматирования из `NOTICE: Found N data formatting errors`.
- `handle_kill` — SIGINT/SIGTERM/SIGQUIT → `exitValue=2`, `sys.exit(2)`; глобальная `g` используется как глобальный объект.
- `bytestr` — человекочитаемый размер (`1.5 MB`).
- `CatThread` — поток, читающий stdout/stderr `gpfdist`; использует `select.select` и общий `Lock`, чтобы не было дедлока.
- `Progress` — HTTP-опрос `gpfdist/status`, но не используется (закомментирован в `do_insert`).

### Блок E. CLI-help, SQL-quoting, pgpass, валидация YAML (867–980)
- `cli_help` читает `../docs/cli_help/gpload_help`, иначе `__doc__`.
- `usage` печатает help и выходит с кодом 2.
- `quote` — SQL-строка: `'` → `''`, `\` → `\\`.
- `splitPgpassLine` — разбор `.pgpass` с экранированием `:`.
- `test_key` — проверяет ключ и его родителя.
- `yaml_walk` — обход `yaml.compose()` дерева и валидация всех ключей.

### Блок F. Нормализация конфига (982–1016)
- `changeToUnicode` рекурсивно переводит строки/списки/словари в `unicode`.
- `dictKeyToLower` рекурсивно приводит ключи к lower-case, значения — к unicode.
- В `__init__` сохраняются две версии: `configOriginal` (для регистрозависимых имён) и `config` (lower keys).

### Блок G. Jenkins hash (1022–1103)
- `jenkinsmix`, `jenkins`, `shortname`.
- `shortname` — детерминированное короткое имя таблицы; сохраняем совместимость алгоритма.

### Блок H. `__init__`: CLI, лог, YAML (1105–1281)
- Ручной разбор аргументов: `-h -p -U -d -W -q -D -v -V -l -f --no_auto_trans --gpfdist_timeout --version -?`.
- Генерирует уникальные имена:
  - `temp_staging_gpload_<uuid1>`
  - `ext_gpload_<uuid1>`
- Дефолтный лог: `$HOME/gpAdminLogs/gpload_YYYYMMDD.log`.
- Открывает конфиг, читает YAML дважды:
  1. `yaml.load(doc)` — данные;
  2. `yaml.compose(doc)` + `yaml_walk` — проверка ключей.
- Проверяет `version == '1.0.0.1'`.
- Обрабатывает `ScannerError`, `ReaderError`, `MarkedYAMLError`.

### Блок I. Логирование и `getconfig` (1283–1388)
- `log(level, msg)` форматирует `время|LEVEL|сообщение`, пишет в stdout и лог-файл, при `ERROR` делает `sys.exit(2)`.
- `getconfig('a:b:c')` — доступ по пути в словаре; поддерживает индекс `a(index)` для списков; проверяет тип (`list`, `dict`, `unicode/str`, `int`); умеет вернуть original-case или lower-case.

### Блок J. `read_config` (1390–1462)
- Проверяет, что `gpload:output` — список.
- Разбирает `OUTPUT.TABLE` на `schema.table` с корректным квотированием.
- Приоритет параметров: CLI > YAML > env:
  - host: `-h` > `HOST` > `PGHOST` > `localhost`
  - port: `-p` > `PORT` > `PGPORT` > `5432`
  - user: `-U` > `USER` > `PGUSER` > `USER/LOGNAME/USERNAME`
  - database: `-d` > `DATABASE` > `PGDATABASE` > user
- Запрещает `ERROR_TABLE`.

### Блок K. Сборка аргументов gpfdist (1464–1610)
Отдельные методы добавляют в `popenList`:
- `-p/-P` — порт или диапазон, проверка доступности;
- `-f` — список файлов (в кавычках);
- `-t` — timeout;
- `-v/-V` — verbose в зависимости от `qv`;
- `-m` — max line length;
- `-c` — transform config, `#transform=...` во фрагмент URL;
- `--ssl <certificates_path>`.

### Блок L. `start_gpfdists` (1612–1737)
Для каждого `INPUT.SOURCE`:
1. Определяет `local_hostname` (или FQDN).
2. Собирает команду `gpfdist`.
3. На Unix запускает через shell:
   ```bash
   source $GPHOME_LOADERS/greenplum_loaders_path.sh ; exec gpfdist ...
   ```
4. Читает stdout до строки `Serving HTTP on port <N>` / `Serving HTTPS on port <N>`, извлекает порт.
5. stderr и остаток stdout уходят в `CatThread`.
6. Формирует локации `gpfdist://host:port/path` (или `gpfdists://`), с `%20` вместо пробелов и `[IPv6]`.

### Блок M. Пароль и подключение (1739–1809)
- `-W` → `getpass`.
- Иначе пароль: YAML → `PGPASSWORD` → `.pgpass` (`PGPASSFILE` или `~/.pgpass`).
- `pg.DB(dbname, host, port, user, passwd)`.
- При ошибке `no password supplied` — повторный запрос пароля, максимум 10 попыток.

### Блок N. Метаданные, колонки, mapping (1811–1969)
- `read_table_metadata`:
  - если schema не задана — ищет по `pg_table_is_visible`;
  - читает `pg_attribute`/`pg_class`/`pg_namespace`;
  - определяет serial-колонки и наличие sequence (`has_sequence`);
  - строит `into_columns = [[quoted_name, type, mapto, has_sequence], ...]` и `into_columns_dict`;
  - если 0 колонок — различает «нет прав» и «нет таблицы».
- `read_columns`:
  - если `COLUMNS` заданы — берёт типы оттуда, недостающие — из target;
  - `bigserial → bigint`, `serial → int4`;
  - иначе `from_columns = into_columns`.
- `read_mapping`:
  - пользовательский `MAPPING` или identity-mapping по совпадению имён;
  - ошибка, если входной колонке некуда маппиться.

### Блок O. Запросы для reuse (1971–2107)
- `get_reuse_exttable_query` — ищет существующую `ext_gpload_reusable_%` с тем же форматом, локациями, колонками и error handling.
- `get_staging_conditions_string` + `hashlib.md5` — ключ для reusable staging table.
- `get_reuse_staging_table_query`, `get_table_oid`, `get_ext_schematable`.

### Блок P. `create_external_table` (2112–2251)
- Собирает `FORMAT`, `DELIMITER`, `NULL`, `ESCAPE`, `QUOTE`, `HEADER`, `FORCE_NOT_NULL`, `ENCODING`, `LOG ERRORS`, `SEGMENT REJECT LIMIT`.
- Учитывает `EXTERNAL.SCHEMA` (`%` = schema target).
- Если `PRELOAD.reuse_tables: true` — ищет готовую external table; иначе создаёт `ext_gpload_<uuid>` / `ext_gpload_reusable_<uuid>`.
- Добавляет `DROP EXTERNAL TABLE` в `cleanupSql`, если reuse выключен.

### Блок Q. `create_staging_table` (2258–2332)
- Только для `update`/`merge`.
- Берёт `MATCH_COLUMNS` как distribution key.
- `including defaults` по умолчанию.
- При reuse ищет `staging_gpload_reusable_<md5>`, при находке делает `TRUNCATE`.
- Иначе создаёт `TEMP TABLE` (или обычную при reuse).

### Блок R. Ошибки (2335–2364)
- `count_errors`: `gp_read_error_log(...)` + `notice_processor`.
- `report_errors`: количество bad rows, для reuse — подсказка с `cmdtime`.
- `exitValue = 1` при предупреждениях.

### Блок S. Способы загрузки (2367–2588)
- insert: `INSERT INTO target (cols) SELECT mapped FROM external_table`.
- update:
  1. создать staging;
  2. залить external → staging;
  3. `UPDATE target FROM staging WHERE match_columns...` + опциональный `update_condition`;
  4. в `update_condition` подставляется alias `into_table.` через regex/лексер.
- merge: update + `INSERT` только тех строк, которых нет в target, с `row_number() OVER (PARTITION BY match_columns)`.
- Ошибки SQL логируются; при ошибке insert пытается вытащить `error file`/`error line`.

### Блок T. Оркестрация (2591–2661)
- `do_truncate`.
- `do_method`:
  - читает `PRELOAD`, `MODE`, `LOG_ERRORS`;
  - `BEGIN` только для не-insert и если не `--no_auto_trans`;
  - preload truncate;
  - `SQL.BEFORE`;
  - вызов insert/update/merge;
  - truncate staging;
  - `SQL.AFTER`;
  - `COMMIT`.

### Блок U. `run`, cleanup, main (2664–2747)
- `run2`: config → connection → metadata → columns → mapping → gpfdist → method.
- `run`:
  - ставит обработчики сигналов;
  - ловит исключения, пишет traceback в лог;
  - в `finally`: удаляет временные объекты, убивает gpfdist, join-ит потоки, печатает итоги.

## 2. Что именно мешает Python 3.10.15

### 2.1 Синтаксис: файл даже не скомпилируется

| Проблема | Строки | Замена |
|---|---|---|
| `except E, e:` | 40, 863, 1228, 1240, 1261, 1264, 1274, 1321, 1573, 1681, 1798, 2098, 2245, 2392, 2491, 2584, 2597, 2633, 2656 | `except E as e:` |
| `print ...` | 882 | `print(...)` |
| backticks `` `size/float(factor)` `` | 737 | `repr(size/float(factor))` |
| long-литералы `1<<50L` | 133–138 | убрать `L` |
| `"\N"` (невалидный escape) | 2150 | `r"\N"` |
| проверка `sys.hexversion < 0x2040400` | 27 | удалить/заменить на ≥3.10 |

### 2.2 Удалённые builtins/типы
- `unicode` — 40+ вхождений (1251, 1379, 1401, 1904, 1909, 1931, 2118, 2122, 2143, 2246, 2394, 2493, 2586, 2603, 2626 и т.д.) → `str`.
- `xrange` — 1492, 1619 → `range`.
- `dict.iteritems()` — 990, 1009, 1938 → `.items()`.
- `d.keys()[0]` — 1819, 1823 → `next(iter(d))`.
- `str.encode` + запись в текстовый stdout/logfile — 1312–1319.
- `hashlib.md5(str)` — 2297 → `md5(str.encode('utf-8'))`.

### 2.3 Изменившаяся семантика итераторов
- `map`/`filter` в Python 3 — ленивые.
- Опаснее всего `filter` на `script/gpload.py:1955`: результат проверяется через `if not i` / `if i`. В Python 3 пустой `filter` всегда truthy → логика сломается. Нужно `list(filter(...))`.
- Остальные `map/filter` (2068, 2120, 2227, 2264, 2324, 2372, 2377, 2380, 2381, 2568, 2570, 2571) попадают в `join`/`map`, но для единообразия лучше сделать списками.

### 2.4 str/bytes
- YAML в Python 3 уже возвращает `str`, поэтому `changeToUnicode`/`dictKeyToLower` можно упростить.
- `log()` кодирует в UTF-8 и пишет в текстовые потоки → `TypeError`.
- `subprocess.Popen` без `text=True` отдаёт `bytes`; `line.strip('\n')`, `line == ''`, `startswith('Serving...')` сломаются.
- `socket.sendall('GET ...')`, `s.makefile()` и разбор строк в `Progress` — тоже bytes.
- `delimiterValue.decode('unicode-escape')` — у `str` нет `decode`; нужен `codecs.decode(..., 'unicode_escape')`.
- `open(config)` лучше делать с `encoding='utf-8'` или в binary и отдавать YAML; лог-файл — `encoding='utf-8'`.

### 2.5 PyYAML 6
- `yaml.load(doc)` без `Loader` теперь ошибка → `yaml.safe_load`.
- `yaml.compose` лучше с `SafeLoader`.
- `yaml.reader.ReaderError.character` в Python 3 — int, а код проверяет `isinstance(e.character, str)` и затем делает `ord(e.character)` → `TypeError`. Проверено на PyYAML 6.0.1.

### 2.6 PyGreSQL
- В текущем окружении `pg`/`pgdb` не установлены — нужен отдельный шаг выбора и фиксации версии.
- Нужно проверить: принимает ли `DB.query` `str` или требует `bytes`; возвращает ли `getresult()`/`dictresult()` `str` или `bytes`; `db.notices()`; `pg.escape_string`.
- `unicode(row['column_name'], 'utf-8')` (1909) в Python 3 невалидно: нужен helper.
- `unicode(row['has_sequence']) != unicode('f')` (1911) — важное смысловое изменение: PyGreSQL в Python 3 может вернуть `bool`, а не `'t'/'f'`. Нужно `has_seq = bool(row['has_sequence'])`.

### 2.7 Прочее
- `bytestr` использует `repr` через backticks — поправить.
- Дублирующиеся `import re`, `import socket` — безвредно, но можно убрать.
- `is_keyword`, `keywords`, `Progress` — мёртвый код; удалить.
- Windows/HP-UX-ветки сохраняем и адаптируем.

## 3. План миграции: маленькие шаги, один логический change = один commit

Сначала страховочная сетка, потом синтаксис, потом текст/bytes, потом БД/процессы, в конце — интеграция и упаковка.

### Фаза 0. Подготовка и baseline

**Шаг 0.1. Зафиксировать окружение**
- Создать новый репозиторий `gpload-py3` и ветку `migration`.
- Скопировать туда `script/gpload.py` и `script/gpload.py.py2-backup` (baseline).
- `python3.10.15` через pyenv/uv, venv.
- Добавить `requirements.txt`: `PyYAML==6.x`, `PyGreSQL==<выбранная>`.
- Зафиксировать версию gpfdist/ОС.
- Проверка: `python3.10 -V`, `pip freeze`.

**Шаг 0.2. Снять baseline поведения**
- Сохранить эталонные control-файлы: insert/update/merge, csv/text, columns/mapping, reuse_tables, ssl, sql before/after, delimiter escape, log_errors, `-D`.
- Сделать fake `pg`-модуль, который записывает SQL, и fake `gpfdist` в `PATH`, который печатает `Serving HTTP on port N` и живёт.
- Собрать golden-логи/SQL текущей версии (если есть Python 2.7) или хотя бы зафиксировать ожидаемые SQL вручную.
- Проверка: тесты падают/проходят одинаково при повторном запуске.

**Шаг 0.3. Каркас тестов**
- `pytest` + unit-тесты чистых функций: `quote`, `quote_ident/unident`, `splitUpMultipartIdentifier`, `splitIntoLiteralsAndNonLiterals`, `splitPgpassLine`, `bytestr`, `jenkins/shortname`, `valid_tokens/yaml_walk`.
- Smoke: `python -m py_compile script/gpload.py` и `gpload -?`.
- Проверка: тесты запускаются одной командой.

### Фаза 1. Сделать файл синтаксически валидным для Python 3

Каждый шаг — отдельный commit. До завершения фазы `py_compile` будет падать, это нормально.

**Шаг 1.1. Shebang и version guard**
- `#!/usr/bin/env python3`.
- Удалить проверку `sys.hexversion < 0x2040400`.

**Шаг 1.2. `except E, e` → `except E as e`**
- Механически по всем 19 вхождениям.
- Проверка: `grep` не находит `except .*,`.

**Шаг 1.3. `print` statement → функция**
- Строка 882.

**Шаг 1.4. Long-литералы**
- `1<<50L` → `1<<50` и т.д.

**Шаг 1.5. Backticks**
- `bytestr`: `repr(size/float(factor))`.

**Шаг 1.6. `"\N"` → `r"\N"`**
- Строка 2150.

**Шаг 1.7. Milestone: компиляция**
- `python3.10 -m py_compile script/gpload.py` проходит.
- `gpload -?` печатает help (пусть с runtime-ошибками дальше).

### Фаза 2. Текстовая модель str/unicode и YAML

**Шаг 2.1. `unicode` → `str` в проверках типов**
- Заменить `type(x) == unicode` / `type(x) != unicode` на `isinstance(x, str)`.
- Места: 1379, 1513, 1726, 1939, 2154, 2179, 2423 и др.
- `unicode(x)` → `str(x)`.
- Проверка: unit-тесты конфига.

**Шаг 2.2. Упростить `changeToUnicode`**
- В Python 3 YAML уже отдаёт `str`; функция должна рекурсивно обрабатывать только контейнеры и не ломать `None`/`int`.
- Проверка: `configOriginal` сохраняет регистр, `config` — lower.

**Шаг 2.3. `iteritems` → `items`**
- 990, 1009, 1938.

**Шаг 2.4. `keys()[0]` → `next(iter(...))`**
- 1819, 1823.

**Шаг 2.5. `xrange` → `range`**
- 1492, 1619.

**Шаг 2.6. Ленивые `map`/`filter`**
- Сначала критичный `filter` на 1955 → `list(filter(...))`.
- Затем остальные `map`/`filter`, где результат переиспользуется или проверяется на truthiness.
- Проверка: golden SQL для mapping не изменился.

**Шаг 2.7. `bytestr`**
- Убедиться, что вывод совпадает с baseline (`1.5 MB` и т.п.).

**Шаг 2.8. PyYAML 6**
- `yaml.load(doc)` → `yaml.safe_load(doc)`.
- `yaml.compose(doc, Loader=yaml.SafeLoader)`.
- Переписать обработку `ReaderError` под `character: int`.
- Открывать конфиг как UTF-8.
- Проверка: валидный YAML, битый YAML, непечатаемый символ, неверная версия схемы.

**Шаг 2.9. `hashlib.md5`**
- `conditions_str.encode('utf-8')`.
- Зафиксировать в тесте, что для ASCII-имён хеш совпадает с Python 2; для не-ASCII — задокументировать изменение имени reusable-таблицы.

**Шаг 2.10. `unicode_escape` для delimiter**
- Заменить `decode('unicode-escape')` на helper на `codecs.decode`.
- Сохранить поведение `\x1c`, `E'\x1c'`, `\u001c`.
- Проверка: unit-тесты на delimiter.

**Шаг 2.11. Логирование в текстовом режиме**
- Убрать `str.encode('utf-8')` в `log`.
- `open(logfile, 'a', encoding='utf-8')`.
- `sys.stdout.write` текстом.
- Проверка: `-v`/`-V`/`-q`, не-ASCII сообщения.

### Фаза 3. Процессы, gpfdist и база

**Шаг 3.1. `subprocess.Popen` в text mode**
- `text=True`, `encoding='utf-8'`, `errors='replace'`.
- Адаптировать `CatThread`, `line == ''`, `strip('\n')`, `startswith`.
- Сохранить `close_fds` и shell-ветку Unix.
- Проверка: fake gpfdist и реальный gpfdist.

**Шаг 3.2. `Progress` и сокеты**
- Удалить `Progress` (мёртвый код) отдельным commit.
- Если удаление откладывается: `sendall(b'GET ...')`, `makefile('r', encoding='utf-8')`.

**Шаг 3.3. PyGreSQL: spike и выбор версии**
- Установить PyGreSQL, проверить на Python 3.10:
  - тип аргумента `DB.query`;
  - тип результата `getresult`, `dictresult`;
  - `notices`, `escape_string`;
  - поведение bool-колонок и `column_name`.
- Зафиксировать версию в `requirements.txt`.

**Шаг 3.4. Ввести два helper-а для БД**
- `to_db_text(sql)` — то, что реально ждёт выбранная версия PyGreSQL.
- `to_text(value)` — декодирование результата.
- Заменить все `sql.encode('utf-8')` и `unicode(row[...])` на helper-ы.
- Отдельно исправить `has_sequence`: `has_seq = bool(row['has_sequence'])` (или эквивалент для 't'/'f').
- Проверка: golden SQL байт-в-байт, insert/update/merge.

**Шаг 3.5. Удалить мёртвый код**
- Удалить `keywords`, `is_keyword`, `Progress`.
- `jenkins`/`shortname` оставить (см. принятые решения).
- Проверка: все тесты зелёные.

**Шаг 3.6. Кроссплатформенные ветки**
- Адаптировать Windows-ветки `Popen`/`taskkill`/`CatThread` под Python 3.
- Оставить HP-UX sleep.
- Проверка: статический анализ/юнит-тесты; реальный Windows-прогон — при наличии стенда.

### Фаза 4. Сквозная проверка и упаковка

**Шаг 4.1. Golden SQL для всех режимов**
- insert / update / merge;
- reuse external;
- reuse staging;
- `SQL.BEFORE` / `SQL.AFTER`;
- `LOG_ERRORS` + `ERROR_LIMIT`;
- SSL / transform / max_line_length;
- `-D` не выполняет изменения, но строит те же SQL.

**Шаг 4.2. E2E с fake pg + fake gpfdist**
- `load.sh`-сценарий: успешная загрузка, ошибка, warning-rows, failed CSV.
- Проверить exit codes 0/1/2 и раскладку файлов в `failed/`.

**Шаг 4.3. Реальная интеграция с Greenplum**
- Матрица: insert/update/merge, csv/text, кавычки/делимитеры, serial-колонки, `.pgpass`, `PGPASSWORD`, reuse, error limit.
- Сравнить строки/SQL/логи с baseline.

**Шаг 4.4. Упаковка**
- Обновить `Makefile`/shebang, добавить `requirements.txt`.
- Проверить, что `load.sh` вызывает именно Python 3 gpload.
- Обновить документацию/README.

**Шаг 4.5. Финальный прогон**
- `python3.10 -m py_compile`.
- `pytest`.
- `grep` на остатки Python 2 (`unicode`, `xrange`, `iteritems`, `except ,`, `print `, backticks, `L`-суффиксы).
- Smoke `gpload -?`, `--version`, `-D` на эталонном конфиге.

## 4. Ключевые риски

1. PyGreSQL — главный неизвестный фактор. Нужен отдельный spike до массовых правок БД-слоя.
2. `has_sequence` — незаметное изменение семантики, может привести к загрузке в serial-колонки.
3. `filter` на строке 1955 — тихая логическая поломка mapping.
4. Reusable-таблицы — md5 от `str` vs `bytes`; при не-ASCII именах имена таблиц изменятся.
5. Кодировки — конфиг, лог, имена колонок, ошибки БД; нужен единый UTF-8.
6. `gpfdist` output — bytes vs text; ошибки проявятся только при реальном запуске.
7. Windows/HP-UX — сохраняем поддержку, но проверить нечем до появления стендов.

## 5. Открытые вопросы

1. Когда появится кластер Greenplum/gpfdist для интеграционных тестов и какой версии?
2. Есть ли доступ к Windows-стенду для проверки кроссплатформенных веток?
3. Какую версию PyGreSQL разрешает целевая ОС (5.x/6.x, пакет из репозитория или pip)?
4. Нужно ли сохранять байт-в-байт md5-имена `staging_gpload_reusable_*` для не-ASCII идентификаторов?
5. Есть ли внешние скрипты, которые импортируют `gpload.py` как модуль или парсят его лог?

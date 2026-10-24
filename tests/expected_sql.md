# Baseline SQL

Ожидаемые SQL-запросы, снятые вручную с Python 2-версии `script/gpload.py`
(шаг 0.2). Python 2.7 в окружении отсутствует, поэтому эталон зафиксирован по
исходному коду; фактический захват выполняет `tests/run_baseline.py`, когда
файл станет исполним под Python 3.

Обозначения:

- `<UUID>` — случайный `unique_suffix` из `uuid.uuid1()`.
- `<METADATA_QUERY>` — запрос к `pg_catalog.pg_class`/`pg_namespace`/`pg_attribute`
  из `read_table_metadata`; возвращает колонки `id integer`, `name text`,
  `amount numeric` без serial.
- `<REUSE_EXTERNAL_QUERY>` — длинный каталоговый запрос из
  `get_reuse_exttable_query`, который ищет `ext_gpload_reusable_*`.
- Fake `pg` по умолчанию отдаёт `has_sequence` в legacy-виде `'t'/'f'`, как
  старый PyGreSQL под Python 2. Стиль можно переключить через
  `FAKE_PG_HAS_SEQUENCE_STYLE=bool` на шаге 3.4.

Порядок запросов соответствует коду: metadata → gpfdist → загрузка → cleanup.

## insert_text

```sql
<METADATA_QUERY>
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/insert.txt') format'text' (null '\\N' escape '\\' ) 
INSERT INTO "public"."load_test" ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
drop external table if exists ext_gpload_<UUID>
```

## insert_csv

```sql
<METADATA_QUERY>
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/insert.csv') format'csv' (delimiter ',' null '' escape '"' quote '"' header ) 
INSERT INTO "public"."load_test" ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
drop external table if exists ext_gpload_<UUID>
```

## columns_mapping

`COLUMNS` задаёт четыре входные колонки, `MAPPING` перекладывает `name` в
`extra`; `id` не маппится и в INSERT не попадает.

```sql
<METADATA_QUERY>
create external table ext_gpload_<UUID>(id integer,name text,extra text,amount numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/columns.csv') format'csv' (delimiter ',' null '' escape '"' quote '"' ) 
INSERT INTO "public"."load_test" ("name","amount") SELECT "extra","amount" FROM ext_gpload_<UUID>
drop external table if exists ext_gpload_<UUID>
```

## update

```sql
BEGIN
select attname from pg_attribute a, gp_distribution_policy p , pg_class c, pg_namespace n where a.attrelid = c.oid and a.attrelid = p.localoid and a.attnum = any (p.attrnums) and c.relnamespace = n.oid and n.nspname = 'public' and c.relname = 'load_test'; 
SELECT * FROM pg_class WHERE relname LIKE 'temp_gpload_reusable_%%';
CREATE TEMP TABLE temp_staging_gpload_<UUID> (id integer,name text,amount numeric) DISTRIBUTED BY (id)
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/update.csv') format'csv' (delimiter ',' null '' escape '"' quote '"' ) 
INSERT INTO temp_staging_gpload_<UUID> ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
update "public"."load_test" into_table set "name"=from_table."name","amount"=from_table."amount" from temp_staging_gpload_<UUID> from_table where into_table."id"=from_table."id"
truncate temp_staging_gpload_<UUID>
COMMIT
DROP TABLE IF EXISTS temp_staging_gpload_<UUID>
drop external table if exists ext_gpload_<UUID>
```

## merge

```sql
BEGIN
select attname from pg_attribute a, gp_distribution_policy p , pg_class c, pg_namespace n where a.attrelid = c.oid and a.attrelid = p.localoid and a.attnum = any (p.attrnums) and c.relnamespace = n.oid and n.nspname = 'public' and c.relname = 'load_test'; 
SELECT * FROM pg_class WHERE relname LIKE 'temp_gpload_reusable_%%';
CREATE TEMP TABLE temp_staging_gpload_<UUID> (id integer,name text,amount numeric) DISTRIBUTED BY (id)
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/merge.csv') format'csv' (delimiter ',' null '' escape '"' quote '"' ) 
INSERT INTO temp_staging_gpload_<UUID> ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
update "public"."load_test" into_table set "name"=from_table."name","amount"=from_table."amount" from temp_staging_gpload_<UUID> from_table where into_table."id"=from_table."id"
INSERT INTO "public"."load_test" ("id","name","amount") (SELECT from_table."id",from_table."name",from_table."amount" FROM (SELECT *, row_number() OVER (PARTITION BY id) AS gpload_row_number FROM temp_staging_gpload_<UUID>) AS from_table LEFT OUTER JOIN "public"."load_test" into_table ON into_table."id"=from_table."id" WHERE into_table."id" IS NULL AND gpload_row_number=1)
truncate temp_staging_gpload_<UUID>
COMMIT
DROP TABLE IF EXISTS temp_staging_gpload_<UUID>
drop external table if exists ext_gpload_<UUID>
```

## reuse_tables

```sql
<METADATA_QUERY>
<REUSE_EXTERNAL_QUERY>
create external table ext_gpload_reusable_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/reuse.csv') format'csv' (delimiter ',' null '' escape '"' quote '"' ) 
INSERT INTO "public"."load_test" ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_reusable_<UUID>
```

`DROP EXTERNAL TABLE` не выполняется.

## ssl

```sql
<METADATA_QUERY>
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdists://gpload-test:8000/tests/fixtures/data/ssl.csv') format'csv' (delimiter ',' null '' escape '"' quote '"' ) 
INSERT INTO "public"."load_test" ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
drop external table if exists ext_gpload_<UUID>
```

## sql_before_after

```sql
<METADATA_QUERY>
select 'before'
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/sql_before_after.txt') format'text' (null '\\N' escape '\\' ) 
INSERT INTO "public"."load_test" ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
select 'after'
drop external table if exists ext_gpload_<UUID>
```

## delimiter_escape

```sql
<METADATA_QUERY>
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/delimiter.txt') format'text' (delimiter '\x1c' null '\\N' escape '\\' ) 
INSERT INTO "public"."load_test" ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
drop external table if exists ext_gpload_<UUID>
```

## log_errors

```sql
<METADATA_QUERY>
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/log_errors.csv') format'csv' (delimiter ',' null '' escape '"' quote '"' ) log errors segment reject limit 10 
INSERT INTO "public"."load_test" ("id","name","amount") SELECT "id","name","amount" FROM ext_gpload_<UUID>
select count(*) from gp_read_error_log('ext_gpload_<UUID>')
drop external table if exists ext_gpload_<UUID>
```

## dry_run (`-D`)

`create_external_table` выполняется даже с `-D`; сам INSERT пропускается,
cleanup внешней таблицы всё равно выполняется.

```sql
<METADATA_QUERY>
create external table ext_gpload_<UUID>("id" integer,"name" text,"amount" numeric) location('gpfdist://gpload-test:8000/tests/fixtures/data/dry_run.txt') format'text' (null '\\N' escape '\\' ) 
drop external table if exists ext_gpload_<UUID>
```

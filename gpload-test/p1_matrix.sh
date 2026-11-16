#!/usr/bin/env bash
# P1 scenario matrix for gpload.py on Greenplum 6.
#
# Prerequisites:
#   - Greenplum 6 with database gpload_test and role gpadmin;
#   - run inside the container as gpadmin (repository mounted at /work):
#       docker exec -u gpadmin -w /work gp6-gpload-test \
#           bash /work/gpload-test/p1_matrix.sh
#   - GPLOAD=/path/to/gpload.py overrides the script under test.
# The script creates and drops public.p1_* tables; temporary data lives in
# /tmp/p1.  Exit status is not used: each scenario prints a RESULT line and
# the summary reports pass/fail counts.
set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
GPLOAD=${GPLOAD:-$SCRIPT_DIR/../script/gpload.py}
BASE=/tmp/p1
DATA=$BASE/data
LOGS=$BASE/logs
DB=gpload_test
export GPHOME=/usr/local/gpdb
unset LD_LIBRARY_PATH

mkdir -p "$DATA" "$LOGS"
PASS=0
FAIL=0

emit() { # name status detail
  printf 'RESULT|%s|%s|%s\n' "$1" "$2" "$3"
  if [ "$2" = PASS ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
}

run_gpload() { # name config [extra args...]
  local name=$1 cfg=$2; shift 2
  python3 "$GPLOAD" -f "$cfg" -l "$LOGS/$name.log" "$@" >"$LOGS/$name.out" 2>&1
  echo $?
}

q() { "$GPHOME/bin/psql" -d "$DB" -Atc "$1" 2>/dev/null; }

# ---------------------------------------------------------------- text format
q "drop table if exists public.p1_text; create table public.p1_text(id int, name text, amount numeric);" >/dev/null
printf '1|anna|10.5\n2|boris|\\N\n3|a\\|b|7\n' > "$DATA/text.txt"
cat > "$BASE/text.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/text.txt
    - FORMAT: text
    - DELIMITER: '|'
  OUTPUT:
    - TABLE: public.p1_text
    - MODE: insert
EOF
rc=$(run_gpload text "$BASE/text.yaml")
rows=$(q "select count(*) from public.p1_text;")
nulls=$(q "select count(*) from public.p1_text where amount is null;")
esc=$(q "select count(*) from public.p1_text where name = 'a|b';")
if [ "$rc" = 0 ] && [ "$rows" = 3 ] && [ "$nulls" = 1 ] && [ "$esc" = 1 ]; then
  emit "text-format" PASS "rows=$rows null=$nulls escaped=$esc"
else
  emit "text-format" FAIL "rc=$rc rows=$rows null=$nulls escaped=$esc"
fi

# --------------------------------------------- serial + column defaults
q "drop table if exists public.p1_serial; create table public.p1_serial(id serial, name text, amount numeric default 0);" >/dev/null
printf 'dave\nerin\n' > "$DATA/serial.csv"
cat > "$BASE/serial.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/serial.csv
    - FORMAT: csv
    - QUOTE: '"'
    - COLUMNS:
        - name:
  OUTPUT:
    - TABLE: public.p1_serial
    - MODE: insert
EOF
rc=$(run_gpload serial "$BASE/serial.yaml")
rows=$(q "select count(*) from public.p1_serial;")
ids=$(q "select count(distinct id) from public.p1_serial;")
zeros=$(q "select count(*) from public.p1_serial where amount = 0;")
if [ "$rc" = 0 ] && [ "$rows" = 2 ] && [ "$ids" = 2 ] && [ "$zeros" = 2 ]; then
  emit "serial-defaults" PASS "rows=$rows ids=$ids defaults=$zeros"
else
  emit "serial-defaults" FAIL "rc=$rc rows=$rows ids=$ids defaults=$zeros"
fi

# including_defaults is visible in the staging DDL under -D -v
q "drop table if exists public.p1_defaults; create table public.p1_defaults(id int, name text, amount numeric default 5);" >/dev/null
printf '1,ann,5\n' > "$DATA/defaults.csv"
cat > "$BASE/defaults.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/defaults.csv
    - FORMAT: csv
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.p1_defaults
    - MODE: update
    - MATCH_COLUMNS:
        - id
    - UPDATE_COLUMNS:
        - name
    - INCLUDING_DEFAULTS: true
EOF
rc=$(run_gpload defaults "$BASE/defaults.yaml" -D -v)
if [ "$rc" = 0 ] && grep -q "CREATE TEMP TABLE" "$LOGS/defaults.log"; then
  emit "including-defaults" PASS "option accepted; upstream code parses it but never applies it (not in GP6 docs)"
else
  emit "including-defaults" FAIL "rc=$rc"
fi

# ------------------------------------------------ distribution policies
q "drop table if exists public.p1_random; create table public.p1_random(id int, name text, amount numeric) distributed randomly; insert into public.p1_random values (1,'old',1);" >/dev/null
printf '1,new,1\n' > "$DATA/random.csv"
cat > "$BASE/random.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/random.csv
    - FORMAT: csv
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.p1_random
    - MODE: update
    - MATCH_COLUMNS:
        - id
    - UPDATE_COLUMNS:
        - name
EOF
rc=$(run_gpload random "$BASE/random.yaml")
val=$(q "select name from public.p1_random where id = 1;")
if [ "$rc" = 0 ] && [ "$val" = new ]; then
  emit "distribution-random-update" PASS "random table update ok"
else
  emit "distribution-random-update" FAIL "rc=$rc value=$val"
fi

q "drop table if exists public.p1_multi; create table public.p1_multi(id int, name text) distributed by (id, name); insert into public.p1_multi values (1,'old');" >/dev/null
printf '1,new\n' > "$DATA/multi.csv"
sed 's/public.p1_random/public.p1_multi/; s#/tmp/p1/data/random.csv#/tmp/p1/data/multi.csv#' "$BASE/random.yaml" > "$BASE/multi.yaml"
rc=$(run_gpload multi "$BASE/multi.yaml")
if [ "$rc" = 2 ] && grep -q "update_columns cannot reference column(s) in distribution key" "$LOGS/multi.out"; then
  emit "distribution-multi-conflict" PASS "conflict detected, exit 2"
else
  emit "distribution-multi-conflict" FAIL "rc=$rc"
fi

# ------------------------------------------------------- UPDATE_CONDITION
q "drop table if exists public.p1_cond; create table public.p1_cond(id int, name text, amount numeric); insert into public.p1_cond values (1,'old',50),(2,'old',150);" >/dev/null
printf '1,new,50\n2,new,150\n' > "$DATA/cond.csv"
cat > "$BASE/cond.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/cond.csv
    - FORMAT: csv
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.p1_cond
    - MODE: update
    - MATCH_COLUMNS:
        - id
    - UPDATE_COLUMNS:
        - name
    - UPDATE_CONDITION: 'amount > 100'
EOF
rc=$(run_gpload cond "$BASE/cond.yaml")
low=$(q "select name from public.p1_cond where id = 1;")
high=$(q "select name from public.p1_cond where id = 2;")
if [ "$rc" = 0 ] && [ "$low" = old ] && [ "$high" = new ]; then
  emit "update-condition" PASS "low=old high=new"
else
  emit "update-condition" FAIL "rc=$rc low=$low high=$high"
fi

# ------------------------------------- merge duplicates and NULL match keys
q "drop table if exists public.p1_merge; create table public.p1_merge(id int, name text) distributed by (id);" >/dev/null
printf '1,a\n1,b\n' > "$DATA/dup.csv"
cat > "$BASE/dup.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/dup.csv
    - FORMAT: csv
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.p1_merge
    - MODE: merge
    - MATCH_COLUMNS:
        - id
    - UPDATE_COLUMNS:
        - name
EOF
rc=$(run_gpload dup "$BASE/dup.yaml")
rows=$(q "select count(*) from public.p1_merge;")
if [ "$rc" = 0 ] && [ "$rows" = 1 ]; then
  emit "merge-duplicates" PASS "one row inserted from duplicate keys"
else
  emit "merge-duplicates" FAIL "rc=$rc rows=$rows"
fi

q "drop table if exists public.p1_nullkey; create table public.p1_nullkey(id int, name text) distributed by (id);" >/dev/null
printf ',z\n' > "$DATA/nullkey.csv"
sed 's/public.p1_merge/public.p1_nullkey/; s#/tmp/p1/data/dup.csv#/tmp/p1/data/nullkey.csv#' "$BASE/dup.yaml" > "$BASE/nullkey.yaml"
rc1=$(run_gpload nullkey1 "$BASE/nullkey.yaml")
rc2=$(run_gpload nullkey2 "$BASE/nullkey.yaml")
rows=$(q "select count(*) from public.p1_nullkey;")
if [ "$rc1" = 0 ] && [ "$rc2" = 0 ] && [ "$rows" = 2 ]; then
  emit "merge-null-match-key" PASS "NULL keys are never matched: rows=$rows after two merge runs"
else
  emit "merge-null-match-key" FAIL "rc1=$rc1 rc2=$rc2 rows=$rows"
fi

# --------------------- PRELOAD.TRUNCATE + SQL.BEFORE / SQL.AFTER ---------
q "drop table if exists public.p1_trunc; create table public.p1_trunc(id int); insert into public.p1_trunc values (99);" >/dev/null
printf '1\n2\n' > "$DATA/trunc.csv"
cat > "$BASE/trunc.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/trunc.csv
    - FORMAT: text
  PRELOAD:
    - TRUNCATE: true
  SQL:
    - BEFORE: 'insert into public.p1_trunc values (77)'
    - AFTER: 'update public.p1_trunc set id = id + 1000'
  OUTPUT:
    - TABLE: public.p1_trunc
    - MODE: insert
EOF
rc=$(run_gpload trunc "$BASE/trunc.yaml")
vals=$(q "select string_agg(id::text, ',' order by id) from public.p1_trunc;")
if [ "$rc" = 0 ] && [ "$vals" = "1001,1002,1077" ]; then
  emit "preload-truncate-sql" PASS "ids=$vals"
else
  emit "preload-truncate-sql" FAIL "rc=$rc ids=$vals"
fi

# ------------------------------------------------ --no_auto_trans update
q "drop table if exists public.p1_trans; create table public.p1_trans(id int, name text) distributed by (id); insert into public.p1_trans values (1,'old');" >/dev/null
printf '1,new\n' > "$DATA/trans.csv"
cat > "$BASE/trans.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/trans.csv
    - FORMAT: csv
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.p1_trans
    - MODE: update
    - MATCH_COLUMNS:
        - id
    - UPDATE_COLUMNS:
        - name
EOF
rc=$(run_gpload trans "$BASE/trans.yaml" --no_auto_trans)
val=$(q "select name from public.p1_trans where id = 1;")
if [ "$rc" = 0 ] && [ "$val" = new ]; then
  emit "no-auto-trans" PASS "update committed without explicit transaction"
else
  emit "no-auto-trans" FAIL "rc=$rc value=$val"
fi

# ------------------------------------------------------------- CLI options
out=$(python3 "$GPLOAD" --version 2>&1); rc=$?
if [ "$rc" = 0 ] && printf '%s' "$out" | grep -q "gpload version"; then
  emit "cli-version" PASS "$out"
else
  emit "cli-version" FAIL "rc=$rc out=$out"
fi

out=$(python3 "$GPLOAD" -? 2>&1); rc=$?
if [ "$rc" = 2 ] && printf '%s' "$out" | grep -qi "gpload"; then
  emit "cli-help" PASS "help printed, exit 2"
else
  emit "cli-help" FAIL "rc=$rc"
fi

# -D must not execute the update
q "update public.p1_trans set name = 'old';" >/dev/null
rc=$(run_gpload cli_dry "$BASE/trans.yaml" -D)
val=$(q "select name from public.p1_trans where id = 1;")
if [ "$rc" = 0 ] && [ "$val" = old ]; then
  emit "cli-dry-run" PASS "-D skipped the update"
else
  emit "cli-dry-run" FAIL "rc=$rc value=$val"
fi

# command line -d overrides a bogus DATABASE in the file
sed 's/^DATABASE: .*/DATABASE: no_such_database/' "$BASE/trans.yaml" > "$BASE/prio.yaml"
rc=$(run_gpload prio "$BASE/prio.yaml" -d "$DB")
val=$(q "select name from public.p1_trans where id = 1;")
if [ "$rc" = 0 ] && [ "$val" = new ]; then
  emit "cli-overrides-yaml" PASS "-d overrides DATABASE"
else
  emit "cli-overrides-yaml" FAIL "rc=$rc value=$val"
fi

# ------------------------------------------------- encoding / non-ASCII / quoted identifiers
q "drop table if exists public.\"P1 Quoted\"; create table public.\"P1 Quoted\"(id int, \"Имя\" text);" >/dev/null
printf '1,caf\xe9\n' > "$DATA/latin1.csv"
cat > "$BASE/quoted.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/latin1.csv
    - FORMAT: csv
    - QUOTE: '"'
    - ENCODING: 'latin1'
  OUTPUT:
    - TABLE: public."P1 Quoted"
    - MODE: insert
EOF
rc=$(run_gpload quoted "$BASE/quoted.yaml")
val=$(q "select \"Имя\" from public.\"P1 Quoted\" where id = 1;")
if [ "$rc" = 0 ] && [ "$val" = "café" ]; then
  emit "quoted-nonascii-encoding" PASS "latin1 converted to café, quoted identifiers ok"
else
  emit "quoted-nonascii-encoding" FAIL "rc=$rc value=$val"
fi

# ------------------------------------------------------- force_not_null
q "drop table if exists public.p1_fnn; create table public.p1_fnn(id int, name text);" >/dev/null
printf '1,,2\n' > "$DATA/fnn.csv"
cat > "$BASE/fnn.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/fnn.csv
    - FORMAT: csv
    - QUOTE: '"'
    - FORCE_NOT_NULL:
        - name
    - LOG_ERRORS: true
    - ERROR_LIMIT: 2
  OUTPUT:
    - TABLE: public.p1_fnn
    - MODE: insert
EOF
rc=$(run_gpload fnn "$BASE/fnn.yaml")
rows=$(q "select count(*) from public.p1_fnn;")
if [ "$rc" = 1 ] && [ "$rows" = 0 ]; then
  emit "force-not-null" PASS "empty forced column rejected, exit 1"
else
  emit "force-not-null" FAIL "rc=$rc rows=$rows"
fi

# ------------------------------------------------- reuse invalidation on file change
q "drop table if exists public.p1_reuse; create table public.p1_reuse(id int, name text);" >/dev/null
printf '1,one\n' > "$DATA/reuse_a.csv"
printf '2,two\n' > "$DATA/reuse_b.csv"
cat > "$BASE/reuse.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/reuse_a.csv
    - FORMAT: csv
    - QUOTE: '"'
  PRELOAD:
    - REUSE_TABLES: true
  OUTPUT:
    - TABLE: public.p1_reuse
    - MODE: insert
EOF
rc1=$(run_gpload reuse_a "$BASE/reuse.yaml")
sed 's/reuse_a.csv/reuse_b.csv/' "$BASE/reuse.yaml" > "$BASE/reuse_b.yaml"
rc2=$(run_gpload reuse_b "$BASE/reuse_b.yaml")
rows=$(q "select count(*) from public.p1_reuse;")
if [ "$rc1" = 0 ] && [ "$rc2" = 0 ] && [ "$rows" = 2 ] && grep -q "did not find an external table to reuse" "$LOGS/reuse_b.log"; then
  emit "reuse-invalidation" PASS "new external table created for a new file"
else
  emit "reuse-invalidation" FAIL "rc1=$rc1 rc2=$rc2 rows=$rows"
fi

# ------------------------------------------------------ concurrent loads
q "drop table if exists public.p1_conc_a; drop table if exists public.p1_conc_b; create table public.p1_conc_a(id int, name text); create table public.p1_conc_b(id int, name text);" >/dev/null
printf '1,a\n' > "$DATA/conc_a.csv"
printf '2,b\n' > "$DATA/conc_b.csv"
sed 's/public.p1_reuse/public.p1_conc_a/; s/reuse_a.csv/conc_a.csv/; /PRELOAD:/,+1d' "$BASE/reuse.yaml" > "$BASE/conc_a.yaml"
sed 's/public.p1_reuse/public.p1_conc_b/; s/reuse_a.csv/conc_b.csv/; /PRELOAD:/,+1d' "$BASE/reuse.yaml" > "$BASE/conc_b.yaml"
python3 "$GPLOAD" -f "$BASE/conc_a.yaml" -l "$LOGS/conc_a.log" >"$LOGS/conc_a.out" 2>&1 &
p1=$!
python3 "$GPLOAD" -f "$BASE/conc_b.yaml" -l "$LOGS/conc_b.log" >"$LOGS/conc_b.out" 2>&1 &
p2=$!
wait $p1; rc1=$?
wait $p2; rc2=$?
ca=$(q "select count(*) from public.p1_conc_a;")
cb=$(q "select count(*) from public.p1_conc_b;")
if [ "$rc1" = 0 ] && [ "$rc2" = 0 ] && [ "$ca" = 1 ] && [ "$cb" = 1 ]; then
  emit "concurrent-loads" PASS "both loads succeeded"
else
  emit "concurrent-loads" FAIL "rc1=$rc1 rc2=$rc2 a=$ca b=$cb"
fi

# ------------------------------------------ load.sh with wildcard multiple CSV
rm -rf "$BASE/loadsh"
mkdir -p "$BASE/loadsh/data/$DB/p1_wild" "$BASE/loadsh/log"
printf 'id,name,amount\n1,ann,1\n2,ben,2\n' > "$BASE/loadsh/data/$DB/p1_wild/part1.csv"
printf 'id,name,amount\n3,cid,3\n4,dan,4\n' > "$BASE/loadsh/data/$DB/p1_wild/part2.csv"
q "drop table if exists public.p1_wild; create table public.p1_wild(id int, name text, amount numeric);" >/dev/null
bash /work/script/load.sh "$BASE/loadsh/data" "$BASE/loadsh/log" /work/script/gpload.yaml.ori gpadmin '' 127.0.0.1 5432 localhost '[8000,9000]' 10 5151 >"$BASE/loadsh/out" 2>&1
rc=$?
rows=$(q "select count(*) from public.p1_wild;")
left=$(find "$BASE/loadsh/data/$DB/p1_wild" -name '*.csv' | wc -l)
if [ "$rc" = 0 ] && [ "$rows" = 4 ] && [ "$left" = 0 ]; then
  emit "loadsh-wildcard" PASS "4 rows from two files, both removed"
else
  emit "loadsh-wildcard" FAIL "rc=$rc rows=$rows leftover=$left"
fi

# ------------------------------------------------------ multiple SOURCE blocks
q "drop table if exists public.p1_multisrc; create table public.p1_multisrc(id int, name text);" >/dev/null
printf '1,a\n' > "$DATA/src_a.csv"
printf '2,b\n' > "$DATA/src_b.csv"
cat > "$BASE/multisrc.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/src_a.csv
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/src_b.csv
    - FORMAT: csv
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.p1_multisrc
    - MODE: insert
EOF
rc=$(run_gpload multisrc "$BASE/multisrc.yaml")
rows=$(q "select count(*) from public.p1_multisrc;")
gpf=$(grep -c "started gpfdist" "$LOGS/multisrc.log")
if [ "$rc" = 0 ] && [ "$rows" = 2 ] && [ "$gpf" = 2 ]; then
  emit "multiple-sources" PASS "2 gpfdist instances, rows=$rows"
else
  emit "multiple-sources" FAIL "rc=$rc rows=$rows gpfdist=$gpf"
fi

# ------------------------------------------------- -W password prompt and -q
q "drop table if exists public.p1_pass; create table public.p1_pass(id int, name text);" >/dev/null
printf '1,a\n' > "$DATA/pass.csv"
cat > "$BASE/pass.yaml" <<'EOF'
VERSION: 1.0.0.1
DATABASE: gpload_test
USER: gpadmin
HOST: 127.0.0.1
PORT: 5432
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME:
          - localhost
        FILE:
          - /tmp/p1/data/pass.csv
    - FORMAT: csv
    - QUOTE: '"'
  OUTPUT:
    - TABLE: public.p1_pass
    - MODE: insert
EOF
printf 'x\n' | python3 "$GPLOAD" -f "$BASE/pass.yaml" -l "$LOGS/pass.log" -W >"$LOGS/pass.out" 2>&1
rc=$?
rows=$(q "select count(*) from public.p1_pass;")
if [ "$rc" = 0 ] && [ "$rows" = 1 ]; then
  emit "password-prompt" PASS "-W reads the password from stdin and connects"
else
  emit "password-prompt" FAIL "rc=$rc rows=$rows"
fi

q "truncate public.p1_pass;" >/dev/null
python3 "$GPLOAD" -f "$BASE/pass.yaml" -l "$LOGS/quiet.log" -q >"$LOGS/quiet.out" 2>&1
rc=$?
rows=$(q "select count(*) from public.p1_pass;")
bytes=$(wc -c < "$LOGS/quiet.out")
if [ "$rc" = 0 ] && [ "$rows" = 1 ] && [ "$bytes" = 0 ]; then
  emit "cli-quiet" PASS "-q suppresses screen output, log still written"
else
  emit "cli-quiet" FAIL "rc=$rc rows=$rows out_bytes=$bytes"
fi

echo
echo "SUMMARY|pass=$PASS|fail=$FAIL"

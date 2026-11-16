#!/bin/bash
DATA_DIR=${1:-/path/for/gpstall/data}
LOG_DIR=${2:-/path/for/gpstall/log}
ORI_CONF=${3:-./gpload.yaml.ori}
GP_USER=$4
PASSWD=$5
GP_HOST=$6
GP_PORT=$7
GPD_HOST=$8
GPD_PORT_RANGE=$9
ERROR_LIMIT=${10}
TMP_CONF=/tmp/gpload.yaml.tmp.${11}

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
GPLOAD_SCRIPT=${GPLOAD_SCRIPT:-$SCRIPT_DIR/gpload.py}
PYTHON=${PYTHON:-python3}

# greenplum_path.sh puts $GPHOME/lib first in LD_LIBRARY_PATH.  The system
# python3 psycopg2 is linked against the OS libpq and fails to import against
# the older Greenplum libpq ("undefined symbol: PQsslAttribute").  gpload.py
# starts gpfdist from its own shell which sources greenplum_path.sh again, so
# removing the GPHOME entries here only affects the Python process.
clean_ld_library_path() {
  [ -n "$GPHOME" ] || return 0
  local dir clean
  local IFS=:
  for dir in $LD_LIBRARY_PATH; do
    case "$dir" in
      "$GPHOME"/*) ;;
      *) clean="${clean:+$clean:}$dir" ;;
    esac
  done
  export LD_LIBRARY_PATH="$clean"
}

echo "================================"
echo "  start at    :  `date '+%Y-%m-%d %H:%M:%S'` ..."
echo "  data_path   :  $DATA_DIR"
echo "  log_path    :  $LOG_DIR"
echo "  gpload.yaml :  $ORI_CONF"
echo "  gp_host     :  $GP_HOST"
echo "  gp_user     :  $GP_USER"
echo "  gp_port     :  $GP_PORT"
echo "  gpdist_host :  $GPD_HOST"
echo "  gpdist_port_range :  $GPD_PORT_RANGE"
echo "  error_limit :  $ERROR_LIMIT"
#echo "  passwd      :  $PASSWD"
echo "--------------------------------"
echo ""

load_ret=0
export PGPASSWORD=$PASSWD
#echo "env: "
#printenv 
for database in `ls $DATA_DIR` ; do
  #echo "Database: $database"
  for table in `ls $DATA_DIR"/"$database` ; do
    echo "================================"
    echo "   Database: $database table=$table"
    echo "--------------------------------"
    data_path=$DATA_DIR/$database/$table/

    cnt=`find $data_path -maxdepth 1 -name "*csv" | wc -l`
    if [ $cnt -gt 0 ]; then
      first_file=`find $data_path -maxdepth 1 -name "*csv" -print -quit`
      first_line=$(head -n 1 $first_file)
      #echo "first file: $first_file"
      #echo "first line: $first_line"

      IFS="," read -ra attributes <<< "$first_line"

      column="- HEADER: true\\n    - COLUMNS:"
      #column=$'    - HEADER: true\n    - COLUMNS:\n'
      for attr in "${attributes[@]}" ; do
        column+="\\n         - ${attr}:"
        #echo "attr: $attr"
        #echo "$column"
      done

      files=`find $data_path -maxdepth 1 -name "*csv"`
      #echo "files: $files"

      pattern="\\n          - ${data_path}/*.csv"
      echo "pattern: ${pattern}"

      cp -f $ORI_CONF $TMP_CONF
      sed -i "s|{DATABASE}|${database}|g" $TMP_CONF
      sed -i "s|{TABLE}|${table}|g" $TMP_CONF
      sed -i "s|{FILE}|${pattern}|g" $TMP_CONF
      sed -i "s|{HEADER}|${column}|g" $TMP_CONF
      sed -i "s|{GPUSER}|${GP_USER}|g" $TMP_CONF
      sed -i "s|{GPHOST}|${GP_HOST}|g" $TMP_CONF
      sed -i "s|{GPPORT}|${GP_PORT}|g" $TMP_CONF
      sed -i "s|{GPDHOST}|${GPD_HOST}|g" $TMP_CONF
      sed -i "s|{GPDPORT_RANGE}|${GPD_PORT_RANGE}|g" $TMP_CONF
      sed -i "s|{ERROR_LIMIT}|${ERROR_LIMIT}|g" $TMP_CONF

      if [ ! -d $LOG_DIR ] ; then
        mkdir -p $LOG_DIR
      fi

      echo '------------------------------' >> $LOG_DIR/gpload.log
      clean_ld_library_path
      if [ -f "$GPLOAD_SCRIPT" ]; then
        timeout 600 "$PYTHON" "$GPLOAD_SCRIPT" -f "$TMP_CONF" -l "$LOG_DIR/gpload.log"
      else
        timeout 600 gpload -f "$TMP_CONF" -l "$LOG_DIR/gpload.log"
      fi
      retv=$?
      if [ $retv -eq 0 ] ; then
        for file in $files ; do
          #echo " OK! we rm csv    -  - " $file
          # we rm successful csv
          rm -f $file
        done

      elif [ $retv -ge 1 ] ; then
        # exit 1 means "succeeded with warnings": some rows were rejected.
        # Quarantine the file instead of leaving it in place, otherwise the
        # next run would load the accepted rows again and duplicate data.
        if [ $retv -eq 1 ] ; then
          load_ret=1
        else
          load_ret=2
        fi
        rm -f ${LOG_DIR}/latest_failed_file
        failed_path=${data_path}/failed/
        mkdir -p $failed_path

        csvfile=$(tail -n 12 $LOG_DIR/gpload.log | grep "error file" | cut -c 38-)
        errlineno=$(tail -n 12 $LOG_DIR/gpload.log | grep "error line" | cut -c 38-)
        filename=${data_path}/${csvfile}
        if [ "$errlineno" = "" ]; then
          for file in $files ; do
            mv $file $failed_path
          done
          for f in $(ls $failed_path); do
            echo ${failed_path}/${f} >> ${LOG_DIR}/latest_failed_file
          done
        else
          failname=${failed_path}/${csvfile}_${errlineno}
          echo "Failed! file_name: "$filename
          echo "Failed! err_line_no: "$errlineno
          echo "Failed! we mv csv -  - " $failname
          mv $filename $failname
          echo $failname > ${LOG_DIR}/latest_failed_file
        fi
      fi

      #rm -f $TMP_CONF 
      echo ""
    fi

  done
done
echo "--------------------------------"
echo "  finished at :  `date '+%Y-%m-%d %H:%M:%S'`"
echo "--------------------------------"
exit $load_ret

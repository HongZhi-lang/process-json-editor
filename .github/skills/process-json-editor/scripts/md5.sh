#!/bin/bash

set -euo pipefail

usage() {
    cat >&2 <<'EOF'
用法:
  ./md5.sh -d <流程目录> -e <环境ID> -v <版本号>
EOF
    exit 1
}

DIR=''
ENV_ID=''
VERSION=''

while getopts ':d:e:v:' option; do
    case "$option" in
        d) DIR=$OPTARG ;;
        e) ENV_ID=$OPTARG ;;
        v) VERSION=$OPTARG ;;
        *) usage ;;
    esac
done

if [[ -z "$DIR" || -z "$ENV_ID" || -z "$VERSION" || ! -d "$DIR" ]]; then
    usage
fi

consistency_path="$DIR/CONSISTENCY.MD5"
readme_path="$DIR/README.md"

export LC_ALL=C

printf 'env:%s\r\nversion:%s\r\n' "$ENV_ID" "$VERSION" > "$consistency_path"
: > "$readme_path"

ordered_files=()
for file in "$DIR"/*; do
    [[ -f "$file" ]] || continue
    name=${file##*/}
    [[ "$name" == 'CONSISTENCY.MD5' || "$name" == 'README.md' ]] && continue
    ordered_files+=("$file")
done

sorted_files=()
while IFS= read -r file; do
    sorted_files+=("$file")
done < <(printf '%s\n' "${ordered_files[@]}" | awk '
    {
        name = $0
        sub(/^.*\//, "", name)
        if (name ~ /^PROC_.*\.json$/) {
            group = 0
        } else if (name ~ /^ADV_.*\.json$/) {
            group = 1
        } else {
            group = 2
        }
        print group "\t" name "\t" $0
    }
' | sort -t $'\t' -k1,1n -k2,2 | cut -f3-)
ordered_files=("${sorted_files[@]}")

for file in "${ordered_files[@]}"; do
    export_name=${file##*/}
    hash=$(md5 -q "$file")
    printf '%s\r\n' "$export_name" >> "$readme_path"
    printf '%s:%s\r\n' "$export_name" "$hash" >> "$consistency_path"
done

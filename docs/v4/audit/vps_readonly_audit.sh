#!/usr/bin/env bash
# =============================================================================
# AMW AI Media Factory — VPS READ-ONLY audit  (feeds docs/v4/00_REPO_AND_SERVER_AUDIT.md)
#
# READ-ONLY: this script starts, stops, restarts, installs, edits or removes
# NOTHING. It never connects to any database, never prints environment
# variables or config-file contents, and never runs `docker inspect` on env.
# The only thing it writes is its own report files in $OUT_DIR (default: $HOME).
# Every command runs at lowest CPU/IO priority with a timeout.
#
# Usage:
#   bash vps_readonly_audit.sh                      # snapshot only (~1–2 min)
#   bash vps_readonly_audit.sh --sample 60          # snapshot + 60 min sampling, every 30 s
#   bash vps_readonly_audit.sh --sample 400 60      # snapshot + 400 min sampling, every 60 s
#   nohup bash vps_readonly_audit.sh --sample 400 60 >/dev/null 2>&1 &   # run in background
#
# Optional: `sudo bash vps_readonly_audit.sh` adds process names on ports,
# firewall status, Docker disk usage and kernel OOM history. It is still read-only.
# =============================================================================
set -u

SAMPLE_MIN=0
INTERVAL=30
if [ "${1:-}" = "--sample" ]; then
  SAMPLE_MIN="${2:-60}"
  INTERVAL="${3:-30}"
fi
case "$SAMPLE_MIN$INTERVAL" in *[!0-9]*) echo "minutes and interval must be integers"; exit 2;; esac

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR="${OUT_DIR:-$HOME}"
OUT="$OUT_DIR/amw_audit_${TS}.txt"
SAMPLES="$OUT_DIR/amw_audit_${TS}_samples.csv"

LOW="nice -n 19"
command -v ionice >/dev/null 2>&1 && LOW="$LOW ionice -c3"

has()    { command -v "$1" >/dev/null 2>&1; }
redact() { sed -E 's/((pass(word|wd)?|secret|token|api[_-]?key|access[_-]?key)[^=: ]*[=:][[:space:]]*)[^[:space:]]+/\1[REDACTED]/Ig'; }
sec()    { printf '\n===== %s =====\n' "$1"; }
run()    { printf '\n$ %s\n' "$1"; timeout "${T:-30}" $LOW bash -c "$1" 2>&1 | redact; }

echo "Writing snapshot to $OUT ..."
{
sec "0. Meta"
echo "audit_script_version=1"
echo "utc=$(date -u '+%F %T')"
echo "ist=$(TZ=Asia/Kolkata date '+%F %T')"
echo "run_as=$(id -un) euid=$EUID"
echo "sample_minutes=$SAMPLE_MIN interval_s=$INTERVAL"

sec "1. OS & kernel"
run 'grep -E "^(PRETTY_NAME|VERSION_ID)=" /etc/os-release'
run 'uname -r'
run 'uptime'
run 'timedatectl 2>/dev/null | grep -Ei "time zone|synchronized|ntp"'
run 'systemctl --version | head -1'
run 'systemd-detect-virt 2>/dev/null'

sec "2. CPU & memory"
run 'nproc'
run 'lscpu | grep -Ei "^(model name|cpu\(s\)|thread|core|socket|hypervisor|virtualization type)"'
run 'free -m'
run 'free -h'
run 'swapon --show'
run 'cat /proc/loadavg'
run 'for f in cpu memory io; do echo "$f: $(grep some /proc/pressure/$f 2>/dev/null)"; done'
T=45 run 'vmstat -w 5 6'

sec "3. Disk"
run 'df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay'
run 'df -i -x tmpfs -x devtmpfs -x squashfs -x overlay'
run 'lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,ROTA'
T=120 run 'du -xsh /opt/* /srv/* /home/* /var/log /var/lib/docker 2>/dev/null | sort -h | tail -30'
run 'journalctl --disk-usage 2>/dev/null'
run 'test -e /opt/amw-media-factory && echo "EXISTS: /opt/amw-media-factory" || echo "absent: /opt/amw-media-factory"'
has iostat && T=20 run 'iostat -dx 5 2'

sec "4. cgroups & slices"
run 'stat -fc %T /sys/fs/cgroup   # cgroup2fs = cgroup v2'
run 'cat /sys/fs/cgroup/cgroup.controllers 2>/dev/null'
run 'systemctl list-units --type=slice --no-pager --no-legend'
T=20 run 'systemd-cgtop -b -n 2 -d 3 --depth=3 2>/dev/null | tail -n 40'

sec "5. Services, timers, cron"
run 'systemctl list-units --type=service --state=running --no-pager --no-legend'
run 'systemctl list-unit-files --type=service --state=enabled --no-pager --no-legend'
run 'systemctl --failed --no-pager --no-legend'
run 'systemctl list-timers --all --no-pager'
run 'echo "/etc/cron.d:"; ls -1 /etc/cron.d 2>/dev/null; echo "user crontab active lines: $(crontab -l 2>/dev/null | grep -cvE "^[[:space:]]*(#|$)")"'

sec "6. Top processes"
run 'ps -eo pid,user,comm,%cpu,%mem,rss,etime --sort=-rss | head -25'
run 'ps -eo pid,user,comm,%cpu,%mem,rss,etime --sort=-%cpu | head -15'

sec "7. Databases, web servers, proxies (detected by process/binary; no connection made)"
run 'ps -eo comm= | sort | uniq -c | sort -rn | grep -Ei "postgres|mysql|mariadb|mongo|redis|memcache|nginx|caddy|traefik|haproxy|apache|httpd|gunicorn|uvicorn|node|python|java|php" || echo "none matched"'
run 'for c in "nginx -v" "caddy version" "traefik version" "apache2 -v" "haproxy -v" "psql --version" "mysql --version" "redis-server --version"; do b=${c%% *}; command -v $b >/dev/null && echo "$b: $($c 2>&1 | head -1)"; done; true'
run 'echo "nginx enabled sites (names only):"; ls -1 /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null; echo "caddy dir (names only):"; ls -1 /etc/caddy 2>/dev/null; true'

sec "8. Network"
run 'ss -tulnp'
run 'ufw status verbose 2>/dev/null || echo "ufw: not installed or needs sudo"'
has vnstat && run 'vnstat -m 2>/dev/null | tail -8'

sec "9. Docker"
if has docker; then
  run 'docker version --format "client={{.Client.Version}} server={{.Server.Version}} api={{.Server.APIVersion}}"'
  run 'docker info --format "storage_driver={{.Driver}} cgroup_driver={{.CgroupDriver}} cgroup_version={{.CgroupVersion}} cpus={{.NCPU}} mem_bytes={{.MemTotal}} root={{.DockerRootDir}} containers={{.Containers}} running={{.ContainersRunning}}"'
  run 'docker compose version 2>/dev/null || docker-compose version 2>/dev/null'
  run 'docker compose ls -a 2>/dev/null'
  run 'docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"'
  T=45 run 'docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"'
  run 'docker ps -aq | xargs -r docker inspect --format "{{.Name}} project={{index .Config.Labels \"com.docker.compose.project\"}} restart={{.HostConfig.RestartPolicy.Name}} nano_cpus={{.HostConfig.NanoCpus}} cpu_shares={{.HostConfig.CpuShares}} mem_limit={{.HostConfig.Memory}} pids_limit={{.HostConfig.PidsLimit}} net={{.HostConfig.NetworkMode}}"'
  run 'docker network ls'
  run 'docker volume ls --format "{{.Name}}\t{{.Driver}}"'
  T=120 run 'docker system df'
else
  echo "docker: not found in PATH for this user (re-run with sudo if Docker is installed)"
fi

sec "10. Runtimes relevant to the factory"
run 'python3 --version 2>&1; git --version 2>&1; ffmpeg -version 2>/dev/null | head -1 || echo "ffmpeg: not installed"'

sec "11. Historical peak evidence (if available)"
if has sar; then
  run 'for f in $(ls -1t /var/log/sysstat/sa[0-9]* /var/log/sa/sa[0-9]* 2>/dev/null | head -7); do echo "## $f"; sar -u -f $f | tail -1; sar -r -f $f | tail -1; sar -q -f $f | tail -1; done'
else
  echo "sysstat (sar) not installed: no history; use --sample mode for peaks"
fi
run 'journalctl -k --since "-14 days" --no-pager 2>/dev/null | grep -Ei "out of memory|oom-kill|killed process" | tail -20; true'
run 'last -x reboot 2>/dev/null | head -5'
} > "$OUT" 2>&1

echo "Snapshot done: $OUT"

if [ "$SAMPLE_MIN" -gt 0 ]; then
  echo "Sampling for $SAMPLE_MIN min every ${INTERVAL}s -> $SAMPLES"
  echo "ts_ist,scope,load1,mem_used_mb,mem_avail_mb,swap_used_mb,psi_cpu_avg10,psi_mem_avg10,psi_io_avg10,cpu_pct,mem_usage" > "$SAMPLES"
  psi() { grep some "/proc/pressure/$1" 2>/dev/null | sed -E 's/.*avg10=([0-9.]+).*/\1/'; }
  end=$(( $(date +%s) + SAMPLE_MIN * 60 ))
  while [ "$(date +%s)" -lt "$end" ]; do
    t=$(TZ=Asia/Kolkata date '+%F %T')
    l=$(cut -d' ' -f1 /proc/loadavg)
    m=$(free -m | awk '/^Mem:/{print $3","$7} /^Swap:/{s=$3} END{print s}' | paste -sd,)
    echo "$t,HOST,$l,$m,$(psi cpu),$(psi memory),$(psi io),," >> "$SAMPLES"
    if has docker; then
      timeout 20 $LOW docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" 2>/dev/null \
        | awk -F, -v t="$t" '{print t",container:"$1",,,,,,,,"$2","$3}' >> "$SAMPLES"
    fi
    sleep "$INTERVAL"
  done
  echo "Sampling done: $SAMPLES"
fi

echo
echo "Please review the file(s) before sharing. They contain container names, ports and service names."
echo "No passwords or env values are collected; obvious key=value secrets are masked anyway."

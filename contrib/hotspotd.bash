# bash completion for hotspotd

# mapfile rather than COMPREPLY=( $(compgen ...) ): the latter re-splits on
# IFS and globs the result, which mangles any candidate containing a space.
_hotspotd_reply() {
    local candidates=$1 current=$2
    mapfile -t COMPREPLY < <(compgen -W "$candidates" -- "$current")
}

_hotspotd_interfaces() {
    local name
    for name in /sys/class/net/*; do
        [[ -e $name ]] && printf '%s\n' "${name##*/}"
    done
}

_hotspotd() {
    local cur prev commands global i command
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD - 1]}
    commands="doctor up down status enable disable"
    global="--no-color -i --interface --help"

    case $prev in
        -i | --interface | --uplink)
            _hotspotd_reply "$(_hotspotd_interfaces)" "$cur"
            return
            ;;
        --ap-interface | --subnet | -p | --password | -c | --channel)
            return          # free-form values; nothing sensible to offer
            ;;
    esac

    command=
    for ((i = 1; i < COMP_CWORD; i++)); do
        case ${COMP_WORDS[i]} in
            doctor | up | down | status | enable | disable)
                command=${COMP_WORDS[i]}
                break
                ;;
        esac
    done

    case $command in
        "")
            _hotspotd_reply "$commands --version $global" "$cur"
            ;;
        doctor)
            _hotspotd_reply "--json $global" "$cur"
            ;;
        up)
            _hotspotd_reply "-p --password --open -c --channel --uplink \
                --ap-interface --subnet --no-nat --no-dhcp --hidden --save $global" "$cur"
            ;;
        status)
            _hotspotd_reply "--json --no-color --help" "$cur"
            ;;
        *)
            _hotspotd_reply "--no-color --help" "$cur"
            ;;
    esac
}

complete -F _hotspotd hotspotd

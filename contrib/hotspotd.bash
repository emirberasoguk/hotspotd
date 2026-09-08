# bash completion for hotspotd
_hotspotd() {
    local cur prev commands
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD-1]}
    commands="doctor up down status enable disable"

    case "$prev" in
        -i|--interface|--uplink)
            COMPREPLY=($(compgen -W "$(ls /sys/class/net 2>/dev/null)" -- "$cur"))
            return
            ;;
        --ap-interface|--subnet|-p|--password|-c|--channel)
            return
            ;;
    esac

    local i command=
    for ((i = 1; i < COMP_CWORD; i++)); do
        case "${COMP_WORDS[i]}" in
            doctor|up|down|status|enable|disable) command=${COMP_WORDS[i]}; break ;;
        esac
    done

    if [[ -z $command ]]; then
        COMPREPLY=($(compgen -W "$commands --help --version --no-color -i --interface" -- "$cur"))
        return
    fi

    case "$command" in
        doctor) COMPREPLY=($(compgen -W "--json --no-color -i --interface --help" -- "$cur")) ;;
        up)     COMPREPLY=($(compgen -W "-p --password --open -c --channel --uplink \
                             --ap-interface --subnet --no-nat --no-dhcp --hidden --save \
                             --no-color -i --interface --help" -- "$cur")) ;;
        status) COMPREPLY=($(compgen -W "--json --no-color --help" -- "$cur")) ;;
        *)      COMPREPLY=($(compgen -W "--no-color --help" -- "$cur")) ;;
    esac
}
complete -F _hotspotd hotspotd

"""Argument handling and the profile precedence rules."""
from hotspotd import cli, config


def parse(*argv):
    return cli.build_parser().parse_args(list(argv))


def test_options_are_accepted_before_and_after_the_command():
    # `hotspotd up Home --subnet 10.0.0` is what people actually type
    for args in (parse("up", "Home", "--subnet", "10.0.0"),
                 parse("--subnet", "10.0.0", "up", "Home")):
        assert args.subnet == "10.0.0"
        assert args.ssid == "Home"

    for args in (parse("status", "--no-color"), parse("--no-color", "status")):
        assert args.no_color is True


def test_unset_options_stay_none_so_the_profile_can_fill_them():
    args = parse("up", "Home")
    assert args.subnet is None
    assert args.hidden is None
    assert args.channel is None


def test_defaults_are_applied_when_there_is_no_profile():
    saved, config.load = config.load, lambda: {}
    try:
        args = parse("up", "Home")
        cli.apply_profile(args)
        assert args.subnet == "192.168.12"
        assert args.ap_interface == "ap0"
        assert args.hidden is False
        assert args.open is False
    finally:
        config.load = saved


def test_profile_fills_what_the_command_line_left_out():
    saved, config.load = config.load, lambda: {
        "ssid": "Saved", "channel": 6, "subnet": "10.42.0", "hidden": True,
        "password": "fromprofile",
    }
    try:
        args = parse("up")
        assert cli.apply_profile(args) is True
        assert args.ssid == "Saved"
        assert args.channel == 6
        assert args.subnet == "10.42.0"
        assert args.hidden is True
        assert args.password == "fromprofile"
    finally:
        config.load = saved


def test_the_command_line_beats_the_profile():
    saved, config.load = config.load, lambda: {"ssid": "Saved", "subnet": "10.42.0"}
    try:
        args = parse("up", "Override", "--subnet", "172.16.9")
        cli.apply_profile(args)
        assert args.ssid == "Override"
        assert args.subnet == "172.16.9"
    finally:
        config.load = saved


def test_every_command_is_reachable():
    for name in ("doctor", "up", "down", "status", "enable", "disable"):
        argv = [name, "Home"] if name == "up" else [name]
        assert callable(parse(*argv).fn)


def test_human_time_reads_like_a_person_wrote_it():
    assert cli.human_time(5) == "5s"
    assert cli.human_time(75) == "1m 15s"
    assert cli.human_time(3700) == "1h 1m"


def test_color_is_dropped_when_asked():
    assert cli.colors(False) == {k: "" for k in cli.C}

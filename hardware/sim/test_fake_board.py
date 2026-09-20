#!/usr/bin/env python3
"""Tests for the fake board: does it speak the protocol, and does it break as asked?

Standard library only, no network, no sleeping: the board's clock is passed in, so a
twenty-minute session runs in milliseconds.

    python3 -m unittest discover -s hardware/sim
"""

from __future__ import annotations

import json
import os
import unittest

from fake_board import (COLOURS, Board, Corrupter, Replay, build_parser, parse_faults)

DATA = os.path.join(os.path.dirname(__file__), "..", "data")


def run(board: Board, seconds: float) -> list[str]:
    """Advance the board and return the lines it printed, endings stripped."""
    board.advance_to(board.now_ms + seconds * 1000)
    return board.drain().decode("latin-1").splitlines()


def data_lines(lines: list[str]) -> list[dict]:
    return [json.loads(line) for line in lines
            if line.startswith("{") and "diag" not in line[:10]]


def diag_lines(lines: list[str]) -> list[dict]:
    return [json.loads(line)["diag"] for line in lines if line.startswith('{"diag"')]


class Protocol(unittest.TestCase):
    def test_boot_banner_matches_the_firmware(self):
        board = Board()
        lines = board.drain().decode("latin-1")
        # println ends in CRLF, printf in LF: a parser that splits on \n and strips \r
        # handles both, and this is what the real board does.
        self.assertTrue(lines.startswith("\r\n"))
        self.assertIn("# 17_stream ready.", lines)
        self.assertIn("# commands: b blank, z mark t=0", lines)
        self.assertIn("# esp-now up on channel 1", lines)
        self.assertIn("# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer\r\n",
                      lines)

    def test_one_data_line_a_second_with_every_field(self):
        board = Board()
        board.drain()
        lines = run(board, 5)
        rows = data_lines(lines)
        # One at t=0, as the firmware reports on its first loop, then one a second.
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(
                set(row), {"t", "trans", "scat", "absT", "absS", "tC", "sweep", "sweepS",
                           "dark", "stir", "swept"})
            self.assertEqual(list(row["sweep"]), list(COLOURS))
            self.assertEqual(list(row["sweepS"]), list(COLOURS))
            self.assertEqual(set(row["dark"]), {"trans", "scat"})

    def test_first_line_carries_the_boot_sweep_and_the_rest_do_not(self):
        board = Board()
        board.drain()
        rows = data_lines(run(board, 12))
        self.assertTrue(rows[0]["swept"])
        self.assertEqual([row["swept"] for row in rows[1:10]], [False] * 9)
        # The sweep runs every 10 s.
        self.assertTrue(rows[10]["swept"])

    def test_a_swept_line_disturbs_both_fast_channels(self):
        board = Board()
        board.drain()
        rows = data_lines(run(board, 3))
        self.assertTrue(rows[0]["swept"])
        self.assertLess(rows[0]["trans"], 200)
        self.assertGreater(rows[1]["trans"], 2000)

    def test_fields_are_null_not_nan_before_a_blank(self):
        board = Board()
        board.drain()
        row = data_lines(run(board, 2))[0]
        self.assertIsNone(row["absT"])
        self.assertIsNone(row["absS"])
        self.assertEqual(row["t"], -1.0)

    def test_blank_then_absorbance(self):
        board = Board()
        board.drain()
        run(board, 3)
        board.command("b")
        lines = run(board, 2)
        self.assertTrue(any(line.startswith("# blank stored: transmission") for line in lines))
        row = data_lines(run(board, 2))[-1]
        self.assertIsNotNone(row["absT"])
        self.assertAlmostEqual(row["absT"], 0.0, places=1)

    def test_every_command_is_answered(self):
        board = Board()
        board.drain()
        run(board, 2)
        for char, expected in [("z", "# t = 0 marked"), ("a", "# auto t=0 off"),
                               ("s", "# run stopped"), ("m", "# stirrer off")]:
            board.command(char)
            self.assertIn(expected, board.drain().decode("latin-1"))

    def test_t_counts_up_from_a_z_command(self):
        board = Board()
        board.drain()
        run(board, 2)
        board.command("z")
        rows = data_lines(run(board, 3))
        self.assertEqual([row["t"] for row in rows], [1.0, 2.0, 3.0])

    def test_d_asks_for_diagnostics(self):
        board = Board()
        board.drain()
        run(board, 3)  # the boot diag line
        board.command("d")
        diag = diag_lines(run(board, 2))
        self.assertEqual(len(diag), 1)
        self.assertEqual(set(diag[0]["diode"]), set(COLOURS))
        self.assertEqual(diag[0]["reset"], "POWERON")
        self.assertTrue(diag[0]["probe"]["present"])
        self.assertEqual(diag[0]["radio"]["ch"], 1)

    def test_auto_zero_fires_on_the_transmission_drop(self):
        board = Board()
        board.drain()
        run(board, 2)
        board.command("b")
        run(board, 1)
        board.faults["LID_OPEN"] = ""  # any sudden change in the light path
        board.faults.clear()
        board.command("z")
        self.assertIsNotNone(board.zero_ms)


class Faults(unittest.TestCase):
    def signature(self, seconds=6.0, **kwargs) -> tuple[list[dict], list[dict], str]:
        board = Board(**kwargs)
        boot = board.drain().decode("latin-1")
        lines = run(board, seconds)
        return data_lines(lines), diag_lines(lines), boot + "\n".join(lines)

    def test_sensor_unpowered_reads_below_the_adc_floor(self):
        rows, _, _ = self.signature(faults={"SENSOR_UNPOWERED": "trans"})
        self.assertTrue(all(row["trans"] == 12 for row in rows))
        self.assertTrue(all(row["scat"] > 30 for row in rows[1:]))

    def test_sensor_saturated_pins_at_full_scale(self):
        rows, _, _ = self.signature(faults={"SENSOR_SATURATED": "both"})
        self.assertTrue(all(row["trans"] == 3100 and row["scat"] == 3100 for row in rows))

    def test_sensor_noisy_widens_the_reported_spread(self):
        _, diag, _ = self.signature(faults={"SENSOR_NOISY": ""})
        self.assertGreater(diag[0]["noise"]["trans"], 60)

    def test_lid_open_raises_the_dark_reading(self):
        rows, diag, _ = self.signature(faults={"LID_OPEN": ""})
        self.assertGreater(rows[0]["dark"]["trans"], 250)
        self.assertGreater(diag[0]["dark"]["trans"], 250)

    def test_probe_missing_reports_null_temperature_every_line(self):
        rows, diag, boot = self.signature(faults={"PROBE_MISSING": ""})
        self.assertTrue(all(row["tC"] is None for row in rows))
        self.assertFalse(diag[0]["probe"]["present"])
        self.assertIn("absent, reporting null", boot)

    def test_probe_error_reports_the_sentinel(self):
        rows, _, _ = self.signature(faults={"PROBE_ERROR": "-127"})
        self.assertTrue(all(row["tC"] == -127.0 for row in rows))

    def test_temp_jitter_moves_more_than_half_a_degree_a_second(self):
        rows, _, _ = self.signature(seconds=20, faults={"TEMP_JITTER": ""})
        jumps = [abs(b["tC"] - a["tC"]) for a, b in zip(rows, rows[1:])]
        self.assertGreater(max(jumps), 0.5)

    def test_led_open_reads_about_3v3_and_never_lights(self):
        rows, diag, _ = self.signature(faults={"LED_OPEN": "blue"})
        self.assertGreater(diag[0]["diode"]["blue"], 3000)
        self.assertLess(abs(rows[0]["sweep"]["blue"]), 15)
        self.assertGreater(rows[0]["sweep"]["green"], 1000)

    def test_led_short_reads_near_zero(self):
        _, diag, _ = self.signature(faults={"LED_SHORT": "red"})
        self.assertLess(diag[0]["diode"]["red"], 50)

    def test_led_swapped_inverts_two_forward_drops(self):
        _, diag, _ = self.signature(faults={"LED_SWAPPED": "green:blue"})
        self.assertGreater(diag[0]["diode"]["green"], diag[0]["diode"]["blue"])

    def test_not_assembled_makes_every_sweep_value_negative(self):
        rows, _, _ = self.signature(faults={"NOT_ASSEMBLED": ""})
        self.assertTrue(all(mv < 0 for mv in rows[0]["sweep"].values()))

    def test_bench_mode_is_the_same_as_not_assembled(self):
        rows, _, _ = self.signature(assembled=False)
        self.assertTrue(all(mv < 0 for mv in rows[0]["sweep"].values()))

    def test_motor_coupling_shifts_both_channels_together(self):
        board = Board(faults={"MOTOR_COUPLING": "dc"})
        board.drain()
        before = data_lines(run(board, 3))[-1]
        board.command("m")  # stirrer off
        after = data_lines(run(board, 3))[-1]
        self.assertGreater(before["trans"] - after["trans"], 500)
        self.assertGreater(before["scat"] - after["scat"], 500)

    def test_stream_stale_prints_the_banner_and_then_nothing(self):
        rows, _, boot = self.signature(faults={"STREAM_STALE": ""})
        self.assertEqual(rows, [])
        self.assertIn("# 17_stream ready.", boot)

    def test_line_gap_delays_a_line_past_the_report_period(self):
        board = Board(faults={"LINE_GAP": ""})
        board.drain()
        board.advance_to(20000)
        # 20 s of stream with two extra 1.2 s stalls in it.
        self.assertLess(len(data_lines(board.drain().decode("latin-1").splitlines())), 19)

    def test_radio_drift_announces_itself_once(self):
        _, _, text = self.signature(seconds=10, faults={"RADIO_DRIFT": ""})
        self.assertEqual(text.count("# radio had drifted"), 1)

    def test_radio_down_climbs_the_send_failure_count(self):
        _, diag, _ = self.signature(faults={"RADIO_DOWN": ""})
        board = Board(faults={"RADIO_DOWN": ""})
        board.drain()
        run(board, 10)
        board.command("d")
        self.assertGreater(diag_lines(run(board, 2))[0]["radio"]["fail"], 20)

    def test_wrong_firmware_prints_something_else_entirely(self):
        rows, diag, text = self.signature(faults={"WRONG_FIRMWARE": ""})
        self.assertEqual(rows, [])
        self.assertEqual(diag, [])
        self.assertIn("# 18_selftest ready.", text)
        self.assertIn("trans", text)

    def test_brownout_reboots_and_forgets_the_run(self):
        board = Board()
        board.drain()
        run(board, 2)
        board.command("b")
        board.command("z")
        run(board, 2)
        board.brownout()
        text = board.drain().decode("latin-1")
        self.assertIn("# 17_stream ready.", text)
        self.assertIsNone(board.zero_ms)
        self.assertIsNone(board.blank_t)
        board.command("d")
        self.assertEqual(diag_lines(run(board, 2))[0]["reset"], "BROWNOUT")

    def test_unknown_fault_ids_are_rejected(self):
        with self.assertRaises(SystemExit):
            parse_faults(["NOT_A_FAULT"])


class Transport(unittest.TestCase):
    def test_chunking_preserves_the_byte_stream(self):
        payload = b'{"t":1.0}\r\n# note\n'
        for size in (1, 3, 64):
            chunks = Corrupter(chunk=size)(payload)
            self.assertTrue(all(len(c) <= size for c in chunks))
            self.assertEqual(b"".join(chunks), payload)

    def test_junk_prefix_looks_like_joining_a_running_board(self):
        out = b"".join(Corrupter(junk=True)(b'{"t":1.0}\n'))
        self.assertTrue(out.startswith(b'0,"swept":false}'))
        self.assertIn(b"ESP-ROM:esp32s3", out)
        self.assertTrue(out.endswith(b'{"t":1.0}\n'))


class ReplayCapture(unittest.TestCase):
    path = os.path.join(DATA, "session_full_cycle.jsonl")

    def test_replays_only_the_xiao_side_in_order(self):
        replay = Replay(self.path)
        out = replay.advance_to(10_000_000).decode("latin-1").splitlines()
        with open(self.path, encoding="utf-8") as handle:
            expected = [json.loads(line)["line"] for line in handle
                        if json.loads(line).get("src") == "xiao"]
        self.assertEqual(out, expected)

    def test_replay_respects_the_recorded_timing(self):
        replay = Replay(self.path)
        first = replay.advance_to(700).decode("latin-1").splitlines()
        self.assertEqual(len(first), 1)
        self.assertEqual(len(replay.advance_to(1700).decode("latin-1").splitlines()), 1)

    def test_the_simulator_is_a_superset_of_the_captured_line(self):
        with open(self.path, encoding="utf-8") as handle:
            captured = next(json.loads(line)["line"] for line in handle
                            if json.loads(line).get("src") == "xiao"
                            and json.loads(line)["line"].startswith("{"))
        board = Board()
        board.drain()
        mine = data_lines(run(board, 2))[0]
        theirs = json.loads(captured)
        # The capture is four-colour firmware; this board sweeps six. Every key the real
        # board sent is one this board sends, with the same type.
        for key, value in theirs.items():
            self.assertIn(key, mine)
            if value is not None and mine[key] is not None:
                self.assertEqual(type(value) is dict, type(mine[key]) is dict, key)
        for colour in theirs["sweep"]:
            self.assertIn(colour, mine["sweep"])


class Cli(unittest.TestCase):
    def test_every_documented_flag_parses(self):
        args = build_parser().parse_args(
            ["--tcp", "0", "--control", "0", "--fault", "LED_OPEN:blue", "--fault-at", "5",
             "--brownout-at", "9", "--disconnect-after", "12", "--chunk", "1", "--junk",
             "--bench", "--no-diag", "--speed", "50", "--seed", "3", "--for", "2"])
        self.assertEqual(args.tcp, 0)
        self.assertEqual(parse_faults(args.fault), {"LED_OPEN": "blue"})
        self.assertTrue(args.junk)


if __name__ == "__main__":
    unittest.main()

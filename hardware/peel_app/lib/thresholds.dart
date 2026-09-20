/// Every number the fault engine compares against, in one place.
///
/// Each one names the measurement in `hardware/docs/BASELINES.md` (or the firmware
/// behaviour in `hardware/docs/FAULTS.md`) it comes from. Nothing here is invented, and
/// nothing here is fitted to a run: if a threshold has to move, the measurement behind it
/// is the argument for moving it.
class Thresholds {
  const Thresholds._();

  /// MOTOR_COUPLING. Both channels move together on a stirrer toggle. Measured: +150 mV and
  /// erratic with the TT motor (`session_full_cycle.csv` 52-58 s), +2000 mV steady with a DC
  /// motor on the same rail (`motor_coupling_dc.csv`).
  static const motorCouplingMv = 100.0;
  static const motorCouplingSevereMv = 500.0;

  /// How long after a stirrer toggle the shift is attributed to the motor. The firmware's
  /// own before/after means use 1 s either side.
  static const motorWindow = Duration(seconds: 2);

  /// NOT_ASSEMBLED. With no optical path every sweep value is negative, -66 to -345 mV
  /// (`data/README.md`). Assembled, a lit LED reads hundreds of mV above dark.
  static const sweepLitMv = 15.0;
  static const sweepsBeforeNotAssembled = 3;

  /// LED_OPEN / LED_SHORT / LED_SWAPPED, from the diode check. Healthy drops are
  /// 246-1763 mV and monotonic in photon energy; open or reversed is about 3300 mV and
  /// shorted is under 50 mV (`diode_check.csv`).
  static const diodeOpenMv = 3000.0;
  static const diodeShortMv = 50.0;
  static const diodeInversionMv = 100.0;

  /// SENSOR_UNPOWERED. The ADC's own floor on a covered TEMT6000 is 91-150 mV, so anything
  /// below 30 mV is not a dark sensor, it is no sensor (`selftest_lockin_100ms.log`).
  /// The lowest reading ever seen on a live sensor is 21 mV on `scat`, on swept lines only,
  /// which is why swept lines are excluded.
  static const sensorFloorMv = 30.0;
  static const sensorFloorFor = Duration(seconds: 5);

  /// SENSOR_SATURATED. Full scale is about 3100 mV at 11 dB, 12 bit.
  static const sensorSaturatedMv = 3000.0;
  static const sensorSaturatedFor = Duration(seconds: 3);

  /// SENSOR_NOISY. A still sensor spreads 38-51 mV peak to peak across 100 ms means
  /// (`selftest_lockin_100ms.log`); hand-held it read 207-267 mV.
  static const sensorNoiseMv = 60.0;

  /// LID_OPEN. Shaded bench reads 140-160 mV, open bench 300-830 mV (`light_response.csv`).
  static const darkMv = 250.0;

  /// PROBE_MISSING. The firmware reports null for every line when no probe answered at boot.
  static const probeNullLines = 3;

  /// PROBE_ERROR. DallasTemperature's sentinels.
  static const probeSentinels = [-127.0, 85.0];

  /// TEMP_JITTER. With the radio off the same probe is steady to 0.06-0.13 C between
  /// consecutive reads; with the radio on it moves by up to +-1.5 C (`BASELINES.md`).
  static const tempJitterC = 0.5;

  /// The measured line period, 1.016 s (`BASELINES.md`). Used as slack when asking whether
  /// a window of lines really covers the time a fault is supposed to persist for.
  static const reportPeriod = Duration(milliseconds: 1016);

  /// STREAM_STALE. The report period is 1.016 s and the longest healthy gap ever seen is
  /// 2.18 s, during the stirrer's start ramp.
  static const streamStale = Duration(seconds: 3);

  /// LINE_GAP. Anything longer than this is worth showing, but the stirrer ramp causes one.
  static const lineGap = Duration(milliseconds: 1500);

  /// WRONG_FIRMWARE. Boot to first line is about 2 s.
  static const bannerWithin = Duration(seconds: 5);

  /// RADIO_DOWN, as far as the phone can see it: the XIAO's own count of failed ESP-NOW
  /// sends. About 1 packet in 10 is lost at bench range (`espnow_link_test.log`), so a
  /// handful of failures is normal and a persistent climb is not.
  static const radioSendFailures = 20;

  /// How much history the engine keeps. 5 minutes at 1 Hz.
  static const historyLength = 300;
}

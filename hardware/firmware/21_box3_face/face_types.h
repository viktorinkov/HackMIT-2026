// Types the sketch needs before Arduino's auto-generated prototypes appear.
#pragma once
#include <Arduino.h>

struct __attribute__((packed)) PeelPacket {
  uint8_t  magic, version;
  float    t, trans, scat, absT, absS, tC;
  uint16_t sweep[4];
  uint8_t  stir, flags;
};

enum Mood { M_SLEEP, M_CURIOUS, M_READY, M_WATCH, M_SURPRISE, M_RUNNING, M_HAPPY, M_WORRIED };

// w,h are scales of the base pill; lids are fractions eaten off top/bottom; tilt is the inner
// corner drop that makes an expression read as focused, sad or cross.
struct Look { float w, h, lidTop, lidBot, tilt, gazeX, gazeY, gap; };

#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Separate from the instrument's existing 'P' telemetry and lowercase commands.
struct __attribute__((packed)) DisplayPacket {
  uint8_t magic; // 'D' request, 'A' acknowledgement after rendering
  uint8_t version;
  uint8_t scene; // 0 Hello!, 1 Peel, 2..9 mirror phone workflow stages
  uint8_t sequence;
};
static_assert(sizeof(DisplayPacket) == 4, "Display packet layout");

// Uppercase display lines are isolated from legacy single-character commands.
// In particular, malformed display text must never fall through to the motor.
class DisplayCommandParser {
 public:
  bool feed(char c, uint8_t &scene, char &legacy) {
    legacy = 0;
    if (!length && !discard && c != 'H' && c != 'P') {
      if (c != '\r' && c != '\n') legacy = c;
      return false;
    }
    if (c == '\r') return false;
    if (c == '\n') {
      buffer[length] = 0;
      bool hello = !discard && !strcmp(buffer, "HELLO");
      bool peel = !discard && !strcmp(buffer, "PEEL");
      bool phase = !discard && length == 6 && !memcmp(buffer, "PHASE", 5) &&
                   buffer[5] >= '0' && buffer[5] <= '7';
      uint8_t selected = phase ? 2 + buffer[5] - '0' : (peel ? 1 : 0);
      length = 0; discard = false;
      if (!hello && !peel && !phase) return false;
      scene = selected;
      return true;
    }
    if (!((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '7')) || length >= sizeof(buffer) - 1) discard = true;
    if (!discard) buffer[length++] = c;
    return false;
  }
 private:
  char buffer[16] = {};
  size_t length = 0;
  bool discard = false;
};

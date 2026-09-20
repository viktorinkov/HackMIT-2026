#include <assert.h>
#include <string>
#include <vector>
#include "../firmware/display_protocol.h"

int main() {
  DisplayCommandParser parser;
  std::vector<int> scenes;
  std::string instrument;
  auto feed = [&](const std::string &s) {
    for (char c : s) {
      uint8_t scene; char legacy;
      if (parser.feed(c, scene, legacy)) scenes.push_back(scene);
      if (legacy) instrument += legacy;
    }
  };
  feed("HEL"); feed("LO\r\nPEEL\n");
  assert((scenes == std::vector<int>{0, 1}));
  assert(instrument.empty());
  feed("Hbadzms123\n");
  feed("PEELXXXXXXXXXXXXXXXXXXXXXXXXXXXXz\n");
  assert(instrument.empty());
  assert(scenes.size() == 2);
  feed("bzsm\r\nHELLO\n");
  assert(instrument == "bzsm");
  assert(scenes.back() == 0);
  for (int n = 0; n < 8; n++) {
    feed("PHASE" + std::to_string(n) + "\n");
    assert(scenes.back() == n + 2);
  }
  size_t count = scenes.size();
  feed("PHASE9zm\nPHASE4z\n");
  assert(scenes.size() == count);
  assert(instrument == "bzsm");
}

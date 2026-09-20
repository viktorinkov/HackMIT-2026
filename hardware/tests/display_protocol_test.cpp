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
}

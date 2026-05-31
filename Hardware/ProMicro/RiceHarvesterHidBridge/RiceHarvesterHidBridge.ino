#include <Keyboard.h>
#include <Mouse.h>

String line;
unsigned long lastReadyAt = 0;

void setup() {
  Serial.begin(115200);
  Keyboard.begin();
  Mouse.begin();
}

void loop() {
  if (millis() - lastReadyAt > 1500) {
    Serial.println("RHID:READY");
    lastReadyAt = millis();
  }

  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\n') {
      handleLine(line);
      line = "";
    } else if (ch != '\r') {
      line += ch;
    }
  }
}

void handleLine(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd == "PING") {
    Serial.println("RHID:PONG");
    return;
  }

  if (cmd == "REL") {
    Keyboard.releaseAll();
    Mouse.release(MOUSE_LEFT);
    Mouse.release(MOUSE_RIGHT);
    Mouse.release(MOUSE_MIDDLE);
    return;
  }

  if (cmd.startsWith("KD ")) {
    int first = cmd.indexOf(' ');
    int second = cmd.indexOf(' ', first + 1);
    if (second < 0) return;
    byte mods = (byte)cmd.substring(first + 1, second).toInt();
    byte vk = (byte)cmd.substring(second + 1).toInt();
    pressModifiers(mods);
    int key = mapVirtualKey(vk);
    if (key != 0) Keyboard.press(key);
    return;
  }

  if (cmd == "KU") {
    Keyboard.releaseAll();
    return;
  }

  if (cmd.startsWith("MM ")) {
    int first = cmd.indexOf(' ');
    int second = cmd.indexOf(' ', first + 1);
    if (second < 0) return;
    int dx = cmd.substring(first + 1, second).toInt();
    int dy = cmd.substring(second + 1).toInt();
    Mouse.move(constrain(dx, -127, 127), constrain(dy, -127, 127), 0);
    return;
  }

  if (cmd.startsWith("MW ")) {
    int wheel = cmd.substring(3).toInt();
    Mouse.move(0, 0, constrain(wheel, -10, 10));
    return;
  }

  if (cmd.startsWith("MD ")) {
    Mouse.press(mapMouseButton((byte)cmd.substring(3).toInt()));
    return;
  }

  if (cmd.startsWith("MU ")) {
    Mouse.release(mapMouseButton((byte)cmd.substring(3).toInt()));
    return;
  }
}

void pressModifiers(byte mods) {
  if (mods & 0x01) Keyboard.press(KEY_LEFT_CTRL);
  if (mods & 0x02) Keyboard.press(KEY_LEFT_SHIFT);
  if (mods & 0x04) Keyboard.press(KEY_LEFT_ALT);
  if (mods & 0x08) Keyboard.press(KEY_LEFT_GUI);
  if (mods & 0x10) Keyboard.press(KEY_RIGHT_CTRL);
  if (mods & 0x20) Keyboard.press(KEY_RIGHT_SHIFT);
  if (mods & 0x40) Keyboard.press(KEY_RIGHT_ALT);
  if (mods & 0x80) Keyboard.press(KEY_RIGHT_GUI);
}

int mapMouseButton(byte button) {
  if (button == 0x02) return MOUSE_RIGHT;
  if (button == 0x04) return MOUSE_MIDDLE;
  return MOUSE_LEFT;
}

int mapVirtualKey(byte vk) {
  if (vk >= 0x41 && vk <= 0x5A) return 'a' + (vk - 0x41);
  if (vk >= 0x30 && vk <= 0x39) return '0' + (vk - 0x30);
  if (vk >= 0x70 && vk <= 0x7B) return KEY_F1 + (vk - 0x70);

  switch (vk) {
    case 0x08: return KEY_BACKSPACE;
    case 0x09: return KEY_TAB;
    case 0x0D: return KEY_RETURN;
    case 0x1B: return KEY_ESC;
    case 0x20: return ' ';
    case 0x21: return KEY_PAGE_UP;
    case 0x22: return KEY_PAGE_DOWN;
    case 0x23: return KEY_END;
    case 0x24: return KEY_HOME;
    case 0x25: return KEY_LEFT_ARROW;
    case 0x26: return KEY_UP_ARROW;
    case 0x27: return KEY_RIGHT_ARROW;
    case 0x28: return KEY_DOWN_ARROW;
    case 0x2D: return KEY_INSERT;
    case 0x2E: return KEY_DELETE;
    case 0xBA: return ';';
    case 0xBB: return '=';
    case 0xBC: return ',';
    case 0xBD: return '-';
    case 0xBE: return '.';
    case 0xBF: return '/';
    case 0xC0: return '`';
    case 0xDB: return '[';
    case 0xDC: return '\\';
    case 0xDD: return ']';
    case 0xDE: return '\'';
    default: return 0;
  }
}

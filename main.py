from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label

try:
    from jnius import autoclass
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Context = autoclass('android.content.Context')
    IR = PythonActivity.mActivity.getSystemService(Context.CONSUMER_IR_SERVICE)
except Exception:
    IR = None


# ---------- IR signal builders ----------
def nec(addr, cmd, header=(9000, 4500), ext=None):
    a2 = (~addr) & 0xFF if ext is None else ext
    data = [addr, a2, cmd, (~cmd) & 0xFF]
    p = list(header)
    for byte in data:
        for i in range(8):
            p.append(560)
            p.append(1690 if (byte >> i) & 1 else 560)
    p.append(560)
    return 38000, p


def samsung(addr, cmd):
    return nec(addr, cmd, header=(4500, 4500), ext=addr)


def sony(addr, cmd):
    p = [2400, 600]
    for i in range(7):
        p += [1200 if (cmd >> i) & 1 else 600, 600]
    for i in range(5):
        p += [1200 if (addr >> i) & 1 else 600, 600]
    p[-1] = 45000 - sum(p[:-1])
    return 40000, p * 3


def rc5(addr, cmd):
    bits = [1, 1, 0]
    bits += [(addr >> i) & 1 for i in range(4, -1, -1)]
    bits += [(cmd >> i) & 1 for i in range(5, -1, -1)]
    levels = []
    for b in bits:
        levels += [0, 1] if b else [1, 0]
    out = []
    prev = None
    for lv in levels:
        if lv == prev:
            out[-1] += 889
        else:
            out.append(889)
            prev = lv
    if levels[0] == 0:
        out = out[1:]
    if len(out) % 2 == 0:
        out.append(889)
    return 36000, out


BUILD = {'nec': nec, 'samsung': samsung, 'sony': sony, 'rc5': rc5}

# Full command sets for well-known brands
KNOWN = {
    ('samsung', 7): {'POWER': 0x02, 'VOL+': 0x07, 'VOL-': 0x0B,
                     'MUTE': 0x0F, 'CH+': 0x12, 'CH-': 0x10},
    ('nec', 4): {'POWER': 0x08, 'VOL+': 0x02, 'VOL-': 0x03,
                 'MUTE': 0x09, 'CH+': 0x00, 'CH-': 0x01},   # LG
    ('sony', 1): {'POWER': 0x15, 'VOL+': 0x12, 'VOL-': 0x13,
                  'MUTE': 0x14, 'CH+': 0x10, 'CH-': 0x11},
    ('rc5', 0): {'POWER': 12, 'VOL+': 16, 'VOL-': 17,
                 'MUTE': 13, 'CH+': 32, 'CH-': 33},         # Philips
}

NAMES = {('samsung', 7): 'Samsung', ('nec', 4): 'LG',
         ('sony', 1): 'Sony', ('rc5', 0): 'Philips'}


def build_scan_list():
    lst = [('samsung', 7, 0x02), ('nec', 4, 0x08),
           ('sony', 1, 0x15), ('rc5', 0, 12)]
    prio = [0x08, 0x02, 0x12, 0x00, 0x40, 0x1C, 0x18, 0x10, 0x0C, 0x14, 0x04, 0x01]
    for c in prio:
        for a in range(256):
            if ('nec', a) in KNOWN and c == KNOWN[('nec', a)]['POWER']:
                continue
            lst.append(('nec', a, c))
    return lst


SCAN = build_scan_list()


def send(proto, addr, cmd):
    if IR is None or not IR.hasIrEmitter():
        return False
    freq, pattern = BUILD[proto](addr, cmd)
    IR.transmit(freq, [int(x) for x in pattern])
    return True


class Remote(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation='vertical', padding=12, spacing=10, **kw)
        self.idx = 0
        self.locked = None
        self.event = None

        self.info = Label(text="Avto-skanni boshlang", font_size='18sp', size_hint_y=0.15)
        self.add_widget(self.info)

        self.scan_btn = Button(text="AVTO-SKAN BOSHLASH", font_size='20sp',
                               size_hint_y=0.15, background_color=(0.2, 0.6, 1, 1))
        self.scan_btn.bind(on_release=self.toggle_scan)
        self.add_widget(self.scan_btn)

        row = BoxLayout(size_hint_y=0.12, spacing=8)
        b1 = Button(text="< Oldingi")
        b1.bind(on_release=lambda *_: self.step(-1))
        b2 = Button(text="Keyingi >")
        b2.bind(on_release=lambda *_: self.step(1))
        row.add_widget(b1)
        row.add_widget(b2)
        self.add_widget(row)

        grid = GridLayout(cols=2, spacing=8, size_hint_y=0.55)
        for name in ['POWER', 'MUTE', 'VOL+', 'VOL-', 'CH+', 'CH-']:
            b = Button(text=name, font_size='20sp')
            b.bind(on_release=lambda w, n=name: self.press(n))
            grid.add_widget(b)
        self.add_widget(grid)

        if IR is None or not IR.hasIrEmitter():
            self.info.text = "IR topilmadi (faqat IR bor telefonda ishlaydi)"

    def current(self):
        return self.locked if self.locked else SCAN[self.idx]

    def label(self, entry):
        proto, addr, cmd = entry
        name = NAMES.get((proto, addr), f"{proto.upper()} manzil {addr}")
        return name

    def fire(self):
        proto, addr, cmd = self.current()
        ok = send(proto, addr, cmd)
        pos = "" if self.locked else f"  ({self.idx + 1}/{len(SCAN)})"
        self.info.text = ("Yuborildi: " if ok else "Xato: ") + self.label((proto, addr, cmd)) + pos

    def toggle_scan(self, *_):
        if self.event:
            self.event.cancel()
            self.event = None
            self.locked = SCAN[self.idx]
            self.scan_btn.text = "QAYTA SKAN"
            self.scan_btn.background_color = (0.2, 0.6, 1, 1)
            self.info.text = "QULFLANDI: " + self.label(self.locked)
        else:
            self.locked = None
            self.scan_btn.text = "TO'XTA (televizor o'chsa bosing)"
            self.scan_btn.background_color = (1, 0.3, 0.3, 1)
            self.event = Clock.schedule_interval(self.scan_tick, 1.2)
            self.scan_tick(0)

    def scan_tick(self, dt):
        self.fire()
        self.idx = (self.idx + 1) % len(SCAN)

    def step(self, d):
        if self.event:
            return
        self.locked = None
        self.idx = (self.idx + d) % len(SCAN)
        self.fire()

    def press(self, name):
        if self.event:
            return
        proto, addr, cmd = self.current()
        cmds = KNOWN.get((proto, addr))
        if cmds and name in cmds:
            send(proto, addr, cmds[name])
            self.info.text = f"{self.label((proto, addr, cmd))}: {name}"
        elif name == 'POWER':
            send(proto, addr, cmd)
            self.info.text = f"{self.label((proto, addr, cmd))}: POWER"
        else:
            self.info.text = "Bu marka uchun faqat POWER bor"


class RemoteApp(App):
    def build(self):
        return Remote()


if __name__ == '__main__':
    RemoteApp().run()
